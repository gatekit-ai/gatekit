"""Test configuration and fixtures for Gatekit tests."""

import logging
import time

import pytest
import pytest_asyncio
import sys
import asyncio
from pathlib import Path
from typing import Optional

# Add the gatekit package to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import plugin interfaces for fixtures
from gatekit.plugins.interfaces import AuditingPlugin, PluginResult, SecurityPlugin  # noqa: E402

# Configure pytest-asyncio
pytest_plugins = ["pytest_asyncio"]


# ============================================================================
# Slow/Smoke Test Collection
# ============================================================================
# By default, slow and smoke tests are NOT COLLECTED to keep the development loop fast.
# Use --run-slow to include them (e.g., before releases or after major changes).
# Tests are filtered from collection entirely (not marked as skipped) so the output
# shows all green with no skip noise.


def pytest_addoption(parser):
    """Add --run-slow option to pytest."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests (including smoke tests)",
    )


def pytest_collection_modifyitems(config, items):
    """Filter out tests that shouldn't be collected on this platform/configuration."""
    run_slow = config.getoption("--run-slow")

    filtered_items = []
    for item in items:
        # Filter out slow/smoke tests unless --run-slow is passed
        if not run_slow and ("slow" in item.keywords or "smoke" in item.keywords):
            continue

        # Filter out windows_only tests on non-Windows platforms
        if "windows_only" in item.keywords and sys.platform != "win32":
            continue

        # Filter out posix_only tests on Windows
        if "posix_only" in item.keywords and sys.platform == "win32":
            continue

        filtered_items.append(item)

    items[:] = filtered_items


@pytest_asyncio.fixture(autouse=True)
async def ensure_async_cleanup():
    """Ensure async tasks have time to clean up before logging system is torn down."""
    yield
    # Wait for all running tasks to complete before test teardown
    # This prevents logging errors when tasks try to log after logging system cleanup
    try:
        # Get all tasks except the current one
        current_task = asyncio.current_task()
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not current_task and not task.done()
        ]

        if tasks:
            # Cancel all remaining tasks
            for task in tasks:
                task.cancel()

            # Wait for them to finish cancellation with a reasonable timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=2.0
                )
            except asyncio.TimeoutError:
                # If tasks don't cancel within timeout, log warning but continue
                try:
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"Some async tasks did not cancel within timeout: {len(tasks)} tasks"
                    )
                except ValueError:
                    # If logging is already torn down, just continue
                    pass
    except Exception:
        # If cleanup fails, don't fail the test
        pass


# Mock Plugin Classes for Testing
class MockSecurityPlugin(SecurityPlugin):
    """Mock security plugin for testing (pipeline compatible)."""

    def __init__(self, config):
        super().__init__(config)
        self.config = config
        self.allowed = config.get("allowed", True)
        self.reason = config.get("reason", "Mock decision")
        self.blocked_methods = config.get("blocked_methods", [])
        self.blocked_keywords = config.get("blocked_keywords", [])

    async def process_request(self, request, server_name: Optional[str] = None):
        if request.method in self.blocked_methods:
            return PluginResult(
                allowed=False,
                reason=f"Request method '{request.method}' blocked by security policy",
                metadata={},
            )
        # Check for blocked keywords in params
        if self.blocked_keywords and hasattr(request, "params") and request.params:
            params_str = str(request.params)
            for keyword in self.blocked_keywords:
                if keyword.lower() in params_str.lower():
                    return PluginResult(
                        allowed=False,
                        reason=f"Request contains blocked keyword: {keyword}",
                        metadata={},
                    )
        # Simple allow/deny based on configured flag
        return PluginResult(
            allowed=self.allowed, reason=f"Request {self.reason}", metadata={}
        )

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        # Mirror request logic for tests
        if request.method in self.blocked_methods:
            return PluginResult(
                allowed=False,
                reason=f"Response for method '{request.method}' blocked by security policy",
                metadata={},
            )
        return PluginResult(
            allowed=self.allowed, reason=f"Response {self.reason}", metadata={}
        )

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        method = getattr(notification, "method", "unknown")
        if method in self.blocked_methods:
            return PluginResult(
                allowed=False,
                reason=f"Notification method '{method}' blocked by security policy",
                metadata={},
            )
        return PluginResult(
            allowed=self.allowed, reason=f"Notification {self.reason}", metadata={}
        )


class MockAuditingPlugin(AuditingPlugin):
    """Mock auditing plugin for testing (pipeline-based only)."""

    def __init__(self, config):
        self.config = config
        self.logged_requests = []  # (request, pipeline)
        self.logged_responses = []  # (request, response, pipeline)
        self.logged_notifications = []  # (notification, pipeline)
        # Simple logs mimicking prior structure for compatibility with some tests
        self.request_log = []
        self.response_log = []

    async def log_request(self, request, pipeline, server_name: Optional[str] = None):
        self.logged_requests.append((request, pipeline))
        self.request_log.append(
            {
                "method": getattr(request, "method", None),
                "id": getattr(request, "id", None),
                "pipeline_outcome": pipeline.pipeline_outcome.value,
                "had_security_plugin": pipeline.had_security_plugin,
            }
        )

    async def log_response(
        self, request, response, pipeline, server_name: Optional[str] = None
    ):
        self.logged_responses.append((request, response, pipeline))
        self.response_log.append(
            {
                "id": getattr(response, "id", None),
                "result": getattr(response, "result", None),
                "pipeline_outcome": pipeline.pipeline_outcome.value,
            }
        )

    async def log_notification(
        self, notification, pipeline, server_name: Optional[str] = None
    ):
        self.logged_notifications.append((notification, pipeline))


class FailingAuditingPlugin(AuditingPlugin):
    """Auditing plugin that always fails for testing error handling (pipeline-based)."""

    def __init__(self, config):
        super().__init__(config)
        self.config = config

    async def log_request(self, request, pipeline, server_name: Optional[str] = None):
        raise RuntimeError("Request logging failure")

    async def log_response(
        self, request, response, pipeline, server_name: Optional[str] = None
    ):
        raise RuntimeError("Response logging failure")

    async def log_notification(
        self, notification, pipeline, server_name: Optional[str] = None
    ):
        raise RuntimeError("Notification logging failure")


class FailingSecurityPlugin(SecurityPlugin):
    """Security plugin that always fails for testing error handling."""

    def __init__(self, config):
        super().__init__(config)
        self.config = config

    async def process_request(self, request, server_name: Optional[str] = None):
        raise RuntimeError("Plugin failure simulation")

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        raise RuntimeError("Response check failure simulation")

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        raise RuntimeError("Notification check failure simulation")


"""(Removed duplicate older signature FailingAuditingPlugin)"""


# Plugin Fixtures
@pytest.fixture
def mock_security_plugin():
    """Create a mock security plugin that allows all requests."""
    return MockSecurityPlugin({"allowed": True, "reason": "Test approval"})


@pytest.fixture
def blocking_security_plugin():
    """Create a mock security plugin that blocks all requests."""
    return MockSecurityPlugin({"allowed": False, "reason": "Test blocked"})


@pytest.fixture
def mock_auditing_plugin():
    """Create a mock auditing plugin for testing."""
    return MockAuditingPlugin({})


@pytest.fixture
def failing_security_plugin():
    """Create a security plugin that raises errors for testing error handling."""
    return FailingSecurityPlugin({})


@pytest.fixture
def failing_auditing_plugin():
    """Create an auditing plugin that raises errors for testing error handling."""
    return FailingAuditingPlugin({})


# Configuration Fixtures
@pytest.fixture
def minimal_proxy_config_dict():
    """Minimal valid proxy configuration dictionary."""
    return {
        "proxy": {
            "transport": "stdio",
            "upstreams": [
                {"name": "test_server", "command": ["python", "-m", "my_mcp_server"]}
            ],
            "timeouts": {"connection_timeout": 30, "request_timeout": 60},
        }
    }


@pytest.fixture
def complete_proxy_config_dict():
    """Complete proxy configuration dictionary with all options."""
    return {
        "proxy": {
            "transport": "http",
            "upstreams": [
                {
                    "name": "test_server",
                    "command": ["python", "-m", "my_mcp_server"],
                    "restart_on_failure": True,
                    "max_restart_attempts": 5,
                }
            ],
            "timeouts": {"connection_timeout": 45, "request_timeout": 90},
            "http": {"host": "0.0.0.0", "port": 9090},
        }
    }


@pytest.fixture
def standard_proxy_config():
    """Standard ProxyConfig object for testing."""
    from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig

    return ProxyConfig(
        transport="stdio",
        upstreams=[
            UpstreamConfig(
                name="example_server", command=["python", "-m", "example_server"]
            )
        ],
        timeouts=TimeoutConfig(),
    )


@pytest.fixture
def plugin_yaml_config(tmp_path):
    """YAML configuration string with plugins for integration testing."""
    # Use a real temp path for cross-platform compatibility
    # Convert to posix format for YAML (backslashes are escape sequences)
    audit_file = (tmp_path / "test_audit.log").as_posix()
    return f"""
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["python", "-m", "test_server"]
  timeouts:
    connection_timeout: 30
    request_timeout: 60

plugins:
  middleware:
    test_server:
      - handler: "tool_manager"
        config:
          enabled: true
          tools:
            - tool: "test_tool"

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "{audit_file}"
          critical: false  # Allow temp path for testing
"""


# MCP Message Fixtures
@pytest.fixture
def sample_mcp_request():
    """Sample MCP request for testing."""
    return {"jsonrpc": "2.0", "method": "tools/list", "id": "req-1"}


@pytest.fixture
def sample_mcp_response():
    """Sample MCP response for testing."""
    return {
        "jsonrpc": "2.0",
        "id": "req-1",
        "result": {"tools": [{"name": "echo", "description": "Echo input"}]},
    }


@pytest.fixture
def sample_mcp_error_response():
    """Sample MCP error response for testing."""
    return {
        "jsonrpc": "2.0",
        "id": "req-1",
        "error": {"code": -32601, "message": "Method not found"},
    }


@pytest.fixture
def sample_initialize_request():
    """Sample MCP initialize request."""
    return {
        "jsonrpc": "2.0",
        "method": "initialize",
        "id": "init-1",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }


@pytest.fixture
def sample_tools_call_request():
    """Sample tools/call request."""
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": "tool-1",
        "params": {"name": "test_server__echo", "arguments": {"text": "Hello, World!"}},
    }


@pytest.fixture
def sample_resources_read_request():
    """Sample resources/read request."""
    return {
        "jsonrpc": "2.0",
        "method": "resources/read",
        "id": "resource-1",
        "params": {"uri": "file://test.txt"},
    }


@pytest.fixture
def blocked_tool_request():
    """Request that should be blocked by security policies."""
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": "blocked-1",
        "params": {"name": "dangerous_tool", "arguments": {"action": "delete_all"}},
    }


@pytest.fixture
def malicious_request():
    """Request containing malicious content for security testing."""
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": "malicious-1",
        "params": {
            "name": "file_operations",
            "arguments": {"content": "malicious payload"},
        },
    }


# ============================================================================
# Logging Cleanup Fixtures (Windows compatibility)
# ============================================================================
# On Windows, file handles must be released before files can be deleted.
# These fixtures ensure proper cleanup of logging handlers.


def close_all_logging_handlers():
    """Close all logging handlers to release file handles.

    On Windows, file handles must be closed before the file can be deleted.
    This function closes all handlers across all loggers in the logging system.
    """
    for logger_name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers[:]:
            try:
                handler.close()
            except Exception:
                pass
            logger.removeHandler(handler)

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        try:
            handler.close()
        except Exception:
            pass
        root_logger.removeHandler(handler)


def safe_unlink(filepath):
    """Safely unlink a file, with retries on Windows.

    On Windows, file handles may not be released immediately even after
    closing all handlers. This function retries deletion with a brief delay.

    Args:
        filepath: Path to the file to delete

    Raises:
        PermissionError: If file cannot be deleted after retries (non-Windows only)
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return

    # Try immediate deletion
    try:
        filepath.unlink()
        return
    except PermissionError:
        if sys.platform != "win32":
            raise

    # On Windows, retry with backoff
    for delay in [0.1, 0.2, 0.5]:
        time.sleep(delay)
        try:
            filepath.unlink()
            return
        except PermissionError:
            continue

    # If we still can't delete, log but don't fail
    # The file will be cleaned up by the system's temp file cleanup
    import warnings
    warnings.warn(
        f"Could not delete temp file {filepath} - will be cleaned up by system",
        ResourceWarning,
        stacklevel=2,
    )


# ============================================================================
# Test Isolation Fixtures (Platform-independent config isolation)
# ============================================================================
# These fixtures isolate tests from real user configurations by setting
# environment variables to temporary paths. This ensures tests don't
# accidentally find/modify real config files.


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Isolate tests from real user configs on all platforms.

    This fixture sets environment variables and patches functions to ensure
    tests don't accidentally find real config files (e.g., Claude Desktop,
    Claude Code configs that might exist on the developer's machine).

    Use this fixture in any test that calls detection functions or expects
    "no config found" behavior.

    Environment variables set:
        - HOME: Unix home directory
        - USERPROFILE: Windows home directory fallback
        - APPDATA: Windows AppData/Roaming directory

    Also patches:
        - gatekit.tui.guided_setup.detection.get_home_dir

    Returns:
        Path: The temporary directory used for isolation

    Example:
        def test_no_config_detected(isolated_home):
            # Detection will look in isolated_home, not real user dirs
            client = detect_claude_desktop()
            assert client is None
    """
    # Set all relevant environment variables to temp path
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    # Also patch get_home_dir for code that calls it directly
    monkeypatch.setattr(
        "gatekit.tui.guided_setup.detection.get_home_dir", lambda: tmp_path
    )

    return tmp_path


@pytest.fixture
def auditing_log_cleanup():
    """Fixture that cleans up logging handlers after tests.

    Use this fixture in tests that create auditing plugins with file output.
    The fixture ensures all logging handlers are closed after the test,
    allowing temp files to be deleted on Windows.

    Example:
        def test_my_auditing_plugin(tmp_path, auditing_log_cleanup):
            log_file = tmp_path / "test.log"
            plugin = MyPlugin({"output_file": str(log_file)})
            # ... test code ...
            # Cleanup happens automatically after yield
    """
    yield
    close_all_logging_handlers()


@pytest.fixture
def auditing_temp_file(tmp_path, auditing_log_cleanup):
    """Fixture that provides a temp file path and handles cleanup.

    This fixture provides a temporary file path for auditing plugins and
    ensures proper cleanup of both logging handlers and the file itself.

    Returns:
        Path: Path to a temporary file (not yet created)

    Example:
        def test_my_auditing_plugin(auditing_temp_file):
            plugin = MyPlugin({"output_file": str(auditing_temp_file)})
            # ... test code ...
            # Cleanup happens automatically
    """
    log_file = tmp_path / "audit_test.log"
    yield log_file
    # Logging cleanup happens via auditing_log_cleanup fixture
    # Additional file cleanup with retry
    safe_unlink(log_file)
