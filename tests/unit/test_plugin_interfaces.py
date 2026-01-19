"""Tests for plugin interfaces and data structures."""

from typing import Optional
import pytest
from pathlib import Path
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginInterface,
    PluginResult,
    PathResolvablePlugin,
    ProcessingPipeline,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestPluginResult:
    """Test PluginResult data structure."""

    def test_policy_decision_creation(self):
        """Test PluginResult creation and defaults."""
        decision = PluginResult(allowed=True, reason="Test reason")

        assert decision.allowed is True
        assert decision.reason == "Test reason"
        assert decision.metadata == {}

    def test_policy_decision_with_metadata(self):
        """Test PluginResult creation with metadata."""
        metadata = {"tool": "read_file", "user": "test"}
        decision = PluginResult(allowed=False, reason="Not allowed", metadata=metadata)

        assert decision.allowed is False
        assert decision.reason == "Not allowed"
        assert decision.metadata == metadata

    def test_policy_decision_metadata_default(self):
        """Test metadata defaults to empty dict."""
        decision = PluginResult(allowed=True, reason="Test")
        assert decision.metadata == {}

        # Verify we can modify the metadata
        decision.metadata["key"] = "value"
        assert decision.metadata["key"] == "value"

    def test_policy_decision_none_metadata_initialization(self):
        """Test that None metadata is converted to empty dict."""
        decision = PluginResult(allowed=True, reason="Test", metadata=None)
        assert decision.metadata == {}


class TestSecurityPluginInterface:
    """Test SecurityPlugin interface."""

    def test_interface_compliance(self):
        """Test SecurityPlugin interface requirements."""
        # Verify SecurityPlugin inherits from PluginInterface
        assert issubclass(SecurityPlugin, PluginInterface)

        # Base class can be instantiated with default implementations
        plugin = SecurityPlugin({})
        assert plugin.is_critical() is True  # Default to critical

    @pytest.mark.asyncio
    async def test_default_implementations_allow_all(self):
        """Test default implementations allow all messages."""
        from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification

        plugin = SecurityPlugin({})

        # Default process_request allows
        request = MCPRequest(jsonrpc="2.0", method="test", id=1)
        result = await plugin.process_request(request, "test_server")
        assert result.allowed is True

        # Default process_response allows
        response = MCPResponse(jsonrpc="2.0", id=1, result={})
        result = await plugin.process_response(request, response, "test_server")
        assert result.allowed is True

        # Default process_notification allows
        notification = MCPNotification(jsonrpc="2.0", method="test")
        result = await plugin.process_notification(notification, "test_server")
        assert result.allowed is True

    def test_complete_implementation_works(self):
        """Test that complete implementation can be instantiated."""

        class CompleteSecurityPlugin(SecurityPlugin):
            """Complete plugin implementation."""

            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test plugin")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test plugin")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test plugin")

        # Should be able to instantiate complete implementation
        plugin = CompleteSecurityPlugin({"test": "config"})
        assert plugin.is_critical() is True  # Default to critical


class TestAuditingPluginInterface:
    """Test AuditingPlugin interface."""

    def test_interface_compliance(self):
        """Test AuditingPlugin interface requirements."""
        # Verify AuditingPlugin inherits from PluginInterface
        assert issubclass(AuditingPlugin, PluginInterface)

        # Base class can be instantiated with default implementations
        plugin = AuditingPlugin({})
        assert plugin.is_critical() is True  # All plugins default to critical (fail-closed)

    @pytest.mark.asyncio
    async def test_default_implementations_do_nothing(self):
        """Test default implementations are no-ops."""
        from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
        from gatekit.plugins.interfaces import ProcessingPipeline

        plugin = AuditingPlugin({})
        request = MCPRequest(jsonrpc="2.0", method="test", id=1)
        pipeline = ProcessingPipeline(original_content=request)

        # Default log_request does nothing (returns None)
        result = await plugin.log_request(request, pipeline, "test_server")
        assert result is None

        # Default log_response does nothing (returns None)
        response = MCPResponse(jsonrpc="2.0", id=1, result={})
        result = await plugin.log_response(request, response, pipeline, "test_server")
        assert result is None

        # Default log_notification does nothing (returns None)
        notification = MCPNotification(jsonrpc="2.0", method="test")
        result = await plugin.log_notification(notification, pipeline, "test_server")
        assert result is None

    def test_complete_implementation_works(self):
        """Test that complete implementation can be instantiated."""

        class CompleteAuditingPlugin(AuditingPlugin):
            """Complete plugin implementation."""

            def __init__(self, config):
                self.config = config

            async def log_request(
                self, request, pipeline, server_name: Optional[str] = None
            ):
                pass

            async def log_response(
                self, request, response, pipeline, server_name: Optional[str] = None
            ):
                pass

            async def log_notification(
                self, notification, pipeline, server_name: Optional[str] = None
            ):
                pass

        # Should be able to instantiate complete implementation
        plugin = CompleteAuditingPlugin({"test": "config"})
        assert plugin.config == {"test": "config"}

    def test_log_response_signature_requires_pipeline(self):
        """Test that log_response method signature includes pipeline parameter."""
        # This test verifies the interface signature
        import inspect

        # Get the log_response method signature
        log_response_method = AuditingPlugin.log_response
        signature = inspect.signature(log_response_method)

        # Should have parameters: self, request, response, pipeline
        param_names = list(signature.parameters.keys())
        assert "self" in param_names
        assert "request" in param_names
        assert "response" in param_names
        assert (
            "pipeline" in param_names
        ), "log_response should include pipeline parameter"

        # Check parameter types if annotations exist
        params = signature.parameters
        if (
            "request" in params
            and params["request"].annotation != inspect.Parameter.empty
        ):
            # Handle both string and class annotations (due to from __future__ import annotations)
            annotation = params["request"].annotation
            assert annotation == MCPRequest or annotation == "MCPRequest"
        if (
            "response" in params
            and params["response"].annotation != inspect.Parameter.empty
        ):
            annotation = params["response"].annotation
            assert annotation == MCPResponse or annotation == "MCPResponse"
        # pipeline parameter should be annotated as ProcessingPipeline
        if (
            "pipeline" in params
            and params["pipeline"].annotation != inspect.Parameter.empty
        ):
            from gatekit.plugins.interfaces import ProcessingPipeline as _PP

            annotation = params["pipeline"].annotation
            assert (
                annotation == _PP or annotation == "ProcessingPipeline"
            ), f"Expected ProcessingPipeline for pipeline parameter, got {annotation}"


class TestPluginInterfaceIntegration:
    """Test plugin interface integration with MCP protocol."""

    @pytest.mark.asyncio
    async def test_security_plugin_with_mcp_request(self):
        """Test SecurityPlugin with actual MCP request."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                # Simple test logic
                if request.method == "tools/call":
                    return PluginResult(allowed=False, reason="Tools blocked")
                return PluginResult(allowed=True, reason="Method allowed")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Response allowed")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Notification allowed")

        plugin = TestSecurityPlugin({})

        # Test with tool call request
        tool_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "read_file"},
        )

        decision = await plugin.process_request(tool_request)
        assert decision.allowed is False
        assert decision.reason == "Tools blocked"

        # Test with non-tool request
        other_request = MCPRequest(jsonrpc="2.0", method="initialize", id="test-2")

        decision = await plugin.process_request(other_request)
        assert decision.allowed is True
        assert decision.reason == "Method allowed"

    @pytest.mark.asyncio
    async def test_security_plugin_with_mcp_response(self):
        """Test SecurityPlugin with actual MCP response."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Request allowed")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                # Simple test logic
                if response.error:
                    return PluginResult(allowed=False, reason="Error response blocked")
                return PluginResult(allowed=True, reason="Success response allowed")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Notification allowed")

        plugin = TestSecurityPlugin({})

        # Create request and successful response
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "read_file"},
        )

        success_response = MCPResponse(
            jsonrpc="2.0", id="test-1", result={"content": "test content"}
        )

        decision = await plugin.process_response(request, success_response)
        assert decision.allowed is True
        assert decision.reason == "Success response allowed"

        # Test with error response
        error_response = MCPResponse(
            jsonrpc="2.0",
            id="test-1",
            error={"code": -32601, "message": "Method not found"},
        )

        decision = await plugin.process_response(request, error_response)
        assert decision.allowed is False
        assert decision.reason == "Error response blocked"

    @pytest.mark.asyncio
    async def test_security_plugin_with_mcp_notification(self):
        """Test SecurityPlugin with actual MCP notification."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Request allowed")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Response allowed")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                # Simple test logic
                if notification.method == "progress":
                    return PluginResult(
                        allowed=True, reason="Progress notification allowed"
                    )
                return PluginResult(allowed=False, reason="Other notifications blocked")

        plugin = TestSecurityPlugin({})

        # Test with progress notification
        progress_notification = MCPNotification(
            jsonrpc="2.0", method="progress", params={"percent": 50}
        )

        decision = await plugin.process_notification(progress_notification)
        assert decision.allowed is True
        assert decision.reason == "Progress notification allowed"

        # Test with other notification
        other_notification = MCPNotification(
            jsonrpc="2.0", method="other_event", params={"data": "test"}
        )

        decision = await plugin.process_notification(other_notification)
        assert decision.allowed is False
        assert decision.reason == "Other notifications blocked"

    @pytest.mark.asyncio
    async def test_auditing_plugin_with_mcp_messages(self):
        """Test AuditingPlugin with actual MCP messages."""

        class TestAuditingPlugin(AuditingPlugin):
            def __init__(self, config):
                self.config = config
                self.logged_requests = []
                self.logged_responses = []
                self.logged_notifications = []

            async def log_request(
                self, request, pipeline, server_name: Optional[str] = None
            ):
                self.logged_requests.append((request, pipeline))

            async def log_response(
                self, request, response, pipeline, server_name: Optional[str] = None
            ):
                self.logged_responses.append((request, response, pipeline))

            async def log_notification(
                self, notification, pipeline, server_name: Optional[str] = None
            ):
                self.logged_notifications.append((notification, pipeline))

        plugin = TestAuditingPlugin({})

        # Test request logging
        request = MCPRequest(jsonrpc="2.0", method="tools/call", id="test-1")
        pipeline_req = ProcessingPipeline(
            original_content=request, final_content=request
        )
        await plugin.log_request(request, pipeline_req)
        assert len(plugin.logged_requests) == 1
        assert plugin.logged_requests[0][0] == request

        # Test response logging
        response = MCPResponse(jsonrpc="2.0", id="test-1", result={"success": True})
        pipeline_resp = ProcessingPipeline(
            original_content=response, final_content=response
        )
        await plugin.log_response(request, response, pipeline_resp)
        assert len(plugin.logged_responses) == 1
        assert plugin.logged_responses[0][0] == request
        assert plugin.logged_responses[0][1] == response

        # Test notification logging
        notification = MCPNotification(
            jsonrpc="2.0", method="progress", params={"percent": 75}
        )
        pipeline_notif = ProcessingPipeline(
            original_content=notification, final_content=notification
        )
        await plugin.log_notification(notification, pipeline_notif)
        assert len(plugin.logged_notifications) == 1
        assert plugin.logged_notifications[0][0] == notification


class TestPathResolvablePluginInterface:
    """Test PathResolvablePlugin interface for path resolution."""

    def test_interface_compliance(self):
        """Test PathResolvablePlugin interface requirements."""
        # Verify PathResolvablePlugin exists
        assert hasattr(PathResolvablePlugin, "set_config_directory")
        assert hasattr(PathResolvablePlugin, "validate_paths")

        # Verify it's abstract
        with pytest.raises(TypeError):
            PathResolvablePlugin({})

    def test_abstract_methods(self):
        """Test abstract methods are properly defined."""
        # Check that set_config_directory is abstract
        assert hasattr(PathResolvablePlugin, "set_config_directory")
        assert getattr(
            PathResolvablePlugin.set_config_directory, "__isabstractmethod__", False
        )

        # Check that validate_paths is abstract
        assert hasattr(PathResolvablePlugin, "validate_paths")
        assert getattr(
            PathResolvablePlugin.validate_paths, "__isabstractmethod__", False
        )

    def test_concrete_implementation_requirements(self):
        """Test concrete implementation must implement all abstract methods."""

        class IncompletePathPlugin(PathResolvablePlugin):
            """Plugin missing required methods."""

            def __init__(self, config):
                pass

            # Missing set_config_directory and validate_paths

        # Should not be able to instantiate without implementing abstract methods
        with pytest.raises(TypeError):
            IncompletePathPlugin({})

    def test_complete_implementation_works(self):
        """Test that complete implementation can be instantiated."""

        class CompletePathPlugin(PathResolvablePlugin):
            """Complete plugin implementation."""

            def __init__(self, config):
                self.config = config
                self.config_directory = None
                self.path_errors = []

            def set_config_directory(self, config_directory):
                self.config_directory = config_directory

            def validate_paths(self):
                self.path_errors = []
                # Simple validation logic for testing
                if self.config.get("invalid_path"):
                    self.path_errors.append("Test path error")
                return self.path_errors

        # Should be able to instantiate complete implementation
        plugin = CompletePathPlugin({"test": "config"})
        assert plugin.config == {"test": "config"}
        assert plugin.config_directory is None

        # Test set_config_directory method
        plugin.set_config_directory(Path("/test/config"))
        assert plugin.config_directory == Path("/test/config")

        # Test validate_paths method returns empty list for valid config
        errors = plugin.validate_paths()
        assert errors == []

        # Test validate_paths method returns errors for invalid config
        plugin.config["invalid_path"] = True
        errors = plugin.validate_paths()
        assert errors == ["Test path error"]

    def test_path_plugin_with_security_mixin(self):
        """Test PathResolvablePlugin can be mixed with SecurityPlugin."""

        class PathAwareSecurityPlugin(SecurityPlugin, PathResolvablePlugin):
            """Plugin that implements both security and path interfaces."""

            def __init__(self, config):
                super().__init__(config)
                self.config_directory = None
                self.paths_validated = False

            def set_config_directory(self, config_directory):
                self.config_directory = config_directory

            def validate_paths(self):
                self.paths_validated = True
                return []  # No path errors for this test

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test plugin")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test plugin")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test plugin")

        # Should be able to instantiate with both interfaces
        plugin = PathAwareSecurityPlugin({"priority": 10})
        assert plugin.priority == 10
        assert plugin.config_directory is None
        assert plugin.paths_validated is False

        # Test path interface methods
        plugin.set_config_directory(Path("/config"))
        assert plugin.config_directory == Path("/config")

        errors = plugin.validate_paths()
        assert errors == []
        assert plugin.paths_validated is True

    def test_path_plugin_with_auditing_mixin(self):
        """Test PathResolvablePlugin can be mixed with AuditingPlugin."""

        class PathAwareAuditingPlugin(AuditingPlugin, PathResolvablePlugin):
            """Plugin that implements both auditing and path interfaces."""

            def __init__(self, config):
                super().__init__(config)
                self.config = config
                self.config_directory: Optional[Path] = None
                self.log_path: Optional[Path] = None

            def set_config_directory(self, config_directory):
                self.config_directory = config_directory
                if self.config_directory and "log_file" in self.config:
                    from gatekit.utils.paths import resolve_config_path

                    self.log_path = resolve_config_path(
                        self.config["log_file"], self.config_directory
                    )

            def validate_paths(self):
                errors = []
                if self.log_path and not self.log_path.parent.exists():
                    errors.append(
                        f"Log directory does not exist: {self.log_path.parent}"
                    )
                return errors

            async def log_request(
                self, request, pipeline, server_name: Optional[str] = None
            ):
                return None

            async def log_response(
                self, request, response, pipeline, server_name: Optional[str] = None
            ):
                return None

            async def log_notification(
                self, notification, pipeline, server_name: Optional[str] = None
            ):
                return None

        config = {"log_file": "audit.log", "priority": 20}
        plugin = PathAwareAuditingPlugin(config)
        assert not hasattr(plugin, "priority")
        assert plugin.config_directory is None
        assert plugin.log_path is None

        config_dir = Path("/config/dir")
        plugin.set_config_directory(config_dir)
        # Compare path parts to handle cross-platform differences
        # (On Windows, /config/dir becomes C:/config/dir)
        assert plugin.config_directory.parts[-2:] == ("config", "dir")
        assert plugin.log_path.name == "audit.log"
        assert plugin.log_path.parent.parts[-2:] == ("config", "dir")

        errors = plugin.validate_paths()
        assert len(errors) == 1
        assert "Log directory does not exist" in errors[0]
