"""Tests for StartupErrorNotifier used for error communication."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from gatekit.cli.startup_error_notifier import StartupErrorNotifier
from gatekit.protocol.errors import StartupError


class TestStartupErrorNotifier:
    """Test the startup error notifier for error communication."""

    @pytest.fixture
    def notifier(self):
        """Create a StartupErrorNotifier instance."""
        return StartupErrorNotifier()

    @pytest.fixture
    def mock_reader(self):
        """Create a mock async reader."""
        reader = AsyncMock()
        return reader

    @pytest.fixture
    def mock_writer(self):
        """Create a mock async writer."""
        writer = AsyncMock()
        return writer

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_send_error_response(self, notifier, mock_writer):
        """Test sending a JSON-RPC error response."""
        error = StartupError(
            code=-32001,
            message="Configuration file not found",
            details="The file /path/to/config.yaml does not exist",
            fix_instructions="Create the configuration file or specify a valid path",
        )

        await notifier.send_error_response(error, mock_writer, request_id=1)

        # Verify the response was sent
        mock_writer.write.assert_called_once()
        sent_data = mock_writer.write.call_args[0][0]

        # Parse the sent JSON
        response = json.loads(sent_data.decode())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["error"]["code"] == -32001
        assert (
            response["error"]["message"]
            == "Gatekit startup failed: Configuration file not found"
        )
        assert (
            response["error"]["data"]["details"]
            == "The file /path/to/config.yaml does not exist"
        )
        assert (
            response["error"]["data"]["fix_instructions"]
            == "Create the configuration file or specify a valid path"
        )

        # Verify drain was called
        mock_writer.drain.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_until_shutdown_sends_startup_error(self, notifier):
        """Test that run_until_shutdown sends startup error immediately."""
        # Set a startup error
        error = StartupError(
            code=-32002,
            message="Plugin loading failed",
            details="Unknown policy 'nonexistent_plugin'",
            fix_instructions="Available policies: tool_allowlist, pii_filter",
        )
        notifier.startup_error = error

        # Mock sys.stdin.readline() to return a JSON-RPC initialize request
        initialize_request = '{"jsonrpc": "2.0", "method": "initialize", "id": 42}\n'

        # Mock sys.stdin and sys.stdout
        with patch("sys.stdin") as mock_stdin, patch("sys.stdout") as mock_stdout:

            mock_stdin.readline.return_value = initialize_request

            # Run the notifier
            await notifier.run_until_shutdown()

            # Verify response was written to stdout
            mock_stdout.write.assert_called_once()
            mock_stdout.flush.assert_called_once()

            # Parse the response that was written
            written_content = mock_stdout.write.call_args[0][0]
            response = json.loads(written_content.strip())

            assert response["jsonrpc"] == "2.0"
            assert response["id"] == 42  # Should match the request ID
            assert response["error"]["code"] == -32002
            assert (
                response["error"]["message"]
                == "Gatekit startup failed: Plugin loading failed"
            )
            assert "nonexistent_plugin" in response["error"]["data"]["details"]

    @pytest.mark.asyncio
    async def test_run_until_shutdown_no_startup_error(self, notifier):
        """Test that run_until_shutdown exits gracefully when no startup error is set."""
        # No startup error set
        notifier.startup_error = None

        # Mock sys.stdout to verify no writing occurs
        with patch("sys.stdout") as mock_stdout:
            # Run the notifier
            await notifier.run_until_shutdown()

            # Verify no error response was sent (since no startup error)
            mock_stdout.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_categorize_startup_error_config_not_found(self, notifier):
        """Test categorizing configuration file not found errors."""
        error = FileNotFoundError("config.yaml")
        startup_error = notifier.categorize_error(
            error, context="Loading configuration from config.yaml"
        )

        assert startup_error.code == -32001
        assert "Configuration file not found" in startup_error.message
        assert "config.yaml" in startup_error.details
        assert "Create the file" in startup_error.fix_instructions

    @pytest.mark.asyncio
    async def test_categorize_startup_error_yaml_parse(self, notifier):
        """Test categorizing YAML parsing errors."""
        # Simulate a YAML error
        yaml_error = ValueError(
            "Invalid YAML syntax: expected <block end>, but found '-' at line 15"
        )
        startup_error = notifier.categorize_error(
            yaml_error, context="Parsing configuration file"
        )

        assert startup_error.code == -32001
        assert "Configuration error" in startup_error.message
        assert "Invalid YAML syntax" in startup_error.details
        assert "line 15" in startup_error.details

    @pytest.mark.asyncio
    async def test_categorize_startup_error_permission(self, notifier):
        """Test categorizing permission denied errors."""
        perm_error = PermissionError("[Errno 13] Permission denied: '/root/audit.log'")
        startup_error = notifier.categorize_error(
            perm_error, context="Creating log file"
        )

        assert startup_error.code == -32003
        assert "Permission denied" in startup_error.message
        assert "/root/audit.log" in startup_error.details
        assert "Check file permissions" in startup_error.fix_instructions

    @pytest.mark.asyncio
    async def test_categorize_startup_error_missing_directory(self, notifier):
        """Test categorizing missing directory errors."""
        dir_error = FileNotFoundError(
            "[Errno 2] No such file or directory: '/nonexistent/dir/file.log'"
        )
        startup_error = notifier.categorize_error(
            dir_error, context="Creating log file at /nonexistent/dir/file.log"
        )

        assert startup_error.code == -32001
        assert "directory" in startup_error.details.lower()
        # Accept both Unix and Windows path formats
        assert "nonexistent" in startup_error.details
        assert "dir" in startup_error.details
        assert "Create the directory" in startup_error.fix_instructions

    @pytest.mark.asyncio
    async def test_categorize_startup_error_plugin_policy(self, notifier):
        """Test categorizing unknown plugin policy errors."""
        plugin_error = ValueError(
            "Unknown policy 'fake_plugin'. Available policies: tool_allowlist, pii_filter"
        )
        startup_error = notifier.categorize_error(
            plugin_error, context="Loading plugin"
        )

        assert startup_error.code == -32002
        assert "Plugin loading failed" in startup_error.message
        assert "fake_plugin" in startup_error.details
        assert "Available policies" in startup_error.details
