"""Unit tests for guided setup error utilities and helper functions."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from gatekit.tui.guided_setup.error_handling import (
    DetectionResult,
    EditorOpener,
    get_no_clients_message,
    format_parse_error_message,
)
from gatekit.tui.guided_setup import client_registry
from gatekit.tui.guided_setup.models import DetectedClient


class TestDetectionResult:
    """Test DetectionResult model for detection outcomes."""

    def test_detection_result_with_clients(self):
        """DetectionResult should indicate success when clients found."""
        mock_client = MagicMock(spec=DetectedClient)
        result = DetectionResult(clients=[mock_client])

        assert result.has_clients()
        assert not result.is_empty()
        assert result.client_count == 1

    def test_detection_result_empty(self):
        """DetectionResult should indicate empty when no clients found."""
        result = DetectionResult(clients=[])

        assert not result.has_clients()
        assert result.is_empty()
        assert result.client_count == 0

    def test_detection_result_tracks_errors(self):
        """DetectionResult should track detection errors."""
        result = DetectionResult(
            clients=[],
            detection_errors=["Failed to read config", "Permission denied"],
        )

        assert result.has_errors()
        assert len(result.detection_errors) == 2

    def test_detection_result_filters_clients_with_servers(self):
        """DetectionResult should provide method to get only clients with servers."""
        client_with_servers = MagicMock(spec=DetectedClient)
        client_with_servers.has_servers.return_value = True

        client_without_servers = MagicMock(spec=DetectedClient)
        client_without_servers.has_servers.return_value = False

        result = DetectionResult(clients=[client_with_servers, client_without_servers])

        clients_with_servers = result.get_clients_with_servers()

        assert len(clients_with_servers) == 1
        assert clients_with_servers[0] == client_with_servers


class TestErrorMessages:
    """Test error message formatting functions."""

    def test_get_no_clients_message(self):
        """Should return clear message when no clients detected."""
        message = get_no_clients_message()

        assert "No MCP clients detected" in message
        assert message is not None
        assert len(message) > 0

    def test_get_supported_clients_list(self):
        """Should return list of supported client names from registry."""
        clients = client_registry.get_supported_client_names()

        # Verify all current clients are present
        assert "Claude Desktop" in clients
        assert "Claude Code" in clients
        assert "Codex" in clients
        assert "Cursor" in clients
        assert "Windsurf" in clients
        assert len(clients) >= 5  # Currently 5 clients, may grow

    def test_format_parse_error_message_single_error(self):
        """Should format single parse error clearly."""
        mock_client = MagicMock(spec=DetectedClient)
        mock_client.display_name.return_value = "Claude Desktop"
        mock_client.parse_errors = ["Failed to parse server 'foo'"]

        message = format_parse_error_message(mock_client)

        assert "Claude Desktop" in message
        assert "Failed to parse server 'foo'" in message

    def test_format_parse_error_message_multiple_errors(self):
        """Should format multiple parse errors clearly."""
        mock_client = MagicMock(spec=DetectedClient)
        mock_client.display_name.return_value = "Claude Code"
        mock_client.parse_errors = [
            "Failed to parse server 'foo'",
            "Failed to parse server 'bar'",
        ]

        message = format_parse_error_message(mock_client)

        assert "Claude Code" in message
        assert "2 errors" in message or "2" in message


class TestEditorOpener:
    """Test editor opening functionality with error handling."""

    @patch("platform.system")
    @patch("subprocess.run")
    def test_open_file_in_editor_macos(self, mock_run, mock_platform):
        """Should use 'open' on macOS (respects file extension associations)."""
        mock_platform.return_value = "Darwin"

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = Path(f.name)

        try:
            opener = EditorOpener()
            success, error = opener.open_file(file_path)

            assert success is True
            assert error is None
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "open"
            assert str(file_path) in args
            assert len(args) == 2  # Should be just ['open', '/path/to/file']
        finally:
            file_path.unlink(missing_ok=True)

    @patch("platform.system")
    @patch("subprocess.run")
    def test_open_file_in_editor_linux(self, mock_run, mock_platform):
        """Should use 'xdg-open' on Linux."""
        mock_platform.return_value = "Linux"

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = Path(f.name)

        try:
            opener = EditorOpener()
            success, error = opener.open_file(file_path)

            assert success is True
            assert error is None
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "xdg-open" in args
        finally:
            file_path.unlink(missing_ok=True)

    @patch("platform.system")
    @patch("os.startfile", create=True)
    def test_open_file_in_editor_windows(self, mock_startfile, mock_platform):
        """Should use os.startfile on Windows."""
        mock_platform.return_value = "Windows"

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = Path(f.name)

        try:
            opener = EditorOpener()
            success, error = opener.open_file(file_path)

            assert success is True
            assert error is None
            mock_startfile.assert_called_once_with(str(file_path))
        finally:
            file_path.unlink(missing_ok=True)

    @patch("platform.system")
    @patch("subprocess.run")
    def test_open_file_handles_editor_not_found(self, mock_run, mock_platform):
        """Should handle FileNotFoundError (editor command not found) gracefully."""
        mock_platform.return_value = "Darwin"
        mock_run.side_effect = FileNotFoundError("Editor not found")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = Path(f.name)

        try:
            opener = EditorOpener()
            success, error = opener.open_file(file_path)

            assert success is False
            assert error is not None
            assert "not found" in error.lower() or "editor" in error.lower()
        finally:
            file_path.unlink(missing_ok=True)

    def test_open_file_handles_file_not_found(self):
        """Should return clear error when file doesn't exist."""
        file_path = Path("/nonexistent/path/to/file.json")

        opener = EditorOpener()
        success, error = opener.open_file(file_path)

        assert success is False
        assert error is not None
        assert "not found" in error.lower()
        assert str(file_path) in error

    @patch("platform.system")
    @patch("subprocess.run")
    def test_open_file_handles_permission_error(self, mock_run, mock_platform):
        """Should handle PermissionError gracefully."""
        mock_platform.return_value = "Darwin"
        mock_run.side_effect = PermissionError("Permission denied")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = Path(f.name)

        try:
            opener = EditorOpener()
            success, error = opener.open_file(file_path)

            assert success is False
            assert error is not None
            assert "permission" in error.lower()
        finally:
            file_path.unlink(missing_ok=True)

    @patch("platform.system")
    @patch("subprocess.run")
    def test_open_file_handles_generic_exception(self, mock_run, mock_platform):
        """Should handle generic exceptions gracefully."""
        mock_platform.return_value = "Darwin"
        mock_run.side_effect = RuntimeError("Unexpected error")
        file_path = Path("/tmp/test.json")

        opener = EditorOpener()
        success, error = opener.open_file(file_path)

        assert success is False
        assert error is not None
        assert len(error) > 0

    @patch("platform.system")
    @patch("subprocess.run")
    def test_open_file_with_nonexistent_path(self, mock_run, mock_platform):
        """Should handle opening nonexistent file (subprocess will fail)."""
        mock_platform.return_value = "Darwin"
        # Simulate what would happen when trying to open nonexistent file
        mock_run.side_effect = FileNotFoundError("No such file or directory")
        nonexistent_path = Path("/tmp/definitely_does_not_exist_12345.json")

        opener = EditorOpener()
        success, error = opener.open_file(nonexistent_path)

        # Should fail gracefully
        assert success is False
        assert error is not None
        assert "not found" in error.lower() or "editor" in error.lower()
