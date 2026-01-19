"""Tests for Windows-specific command resolution in StdioTransport.

These tests verify that the transport layer correctly handles Windows batch
files (.cmd/.bat) by resolving commands via shutil.which() before spawning.
"""

import pytest
from unittest.mock import patch

from gatekit.transport.stdio import StdioTransport


class TestResolveCommandForPlatform:
    """Tests for _resolve_command_for_platform method."""

    def test_resolves_command_on_windows(self):
        """On Windows, command should be resolved via shutil.which()."""
        transport = StdioTransport(command=["npx", "-y", "@modelcontextprotocol/server-everything"])

        with patch("gatekit.transport.stdio.sys.platform", "win32"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                mock_which.return_value = "C:\\Program Files\\nodejs\\npx.CMD"

                result = transport._resolve_command_for_platform(["npx", "-y", "some-package"])

                mock_which.assert_called_once_with("npx")
                assert result == ["C:\\Program Files\\nodejs\\npx.CMD", "-y", "some-package"]

    def test_preserves_arguments_after_resolution(self):
        """Arguments after the command should be preserved unchanged."""
        transport = StdioTransport(command=["test"])

        with patch("gatekit.transport.stdio.sys.platform", "win32"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                mock_which.return_value = "/resolved/path/test.cmd"

                result = transport._resolve_command_for_platform(
                    ["test", "--arg1", "value1", "--arg2", "value with spaces"]
                )

                assert result == [
                    "/resolved/path/test.cmd",
                    "--arg1",
                    "value1",
                    "--arg2",
                    "value with spaces",
                ]

    def test_skips_resolution_on_non_windows(self):
        """On non-Windows platforms, command should be returned unchanged."""
        transport = StdioTransport(command=["npx"])

        with patch("gatekit.transport.stdio.sys.platform", "darwin"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                result = transport._resolve_command_for_platform(["npx", "-y", "package"])

                mock_which.assert_not_called()
                assert result == ["npx", "-y", "package"]

    def test_skips_resolution_on_linux(self):
        """On Linux, command should be returned unchanged."""
        transport = StdioTransport(command=["npx"])

        with patch("gatekit.transport.stdio.sys.platform", "linux"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                result = transport._resolve_command_for_platform(["npx", "-y", "package"])

                mock_which.assert_not_called()
                assert result == ["npx", "-y", "package"]

    def test_fallback_when_which_returns_none(self):
        """If shutil.which() returns None, original command should be used."""
        transport = StdioTransport(command=["unknown-command"])

        with patch("gatekit.transport.stdio.sys.platform", "win32"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                mock_which.return_value = None

                result = transport._resolve_command_for_platform(["unknown-command", "arg"])

                mock_which.assert_called_once_with("unknown-command")
                assert result == ["unknown-command", "arg"]

    def test_empty_command_list(self):
        """Empty command list should be returned unchanged."""
        transport = StdioTransport(command=[])

        with patch("gatekit.transport.stdio.sys.platform", "win32"):
            result = transport._resolve_command_for_platform([])
            assert result == []

    def test_real_executable_still_works(self):
        """Commands that are already real executables should still work."""
        transport = StdioTransport(command=["python"])

        with patch("gatekit.transport.stdio.sys.platform", "win32"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                # shutil.which returns the .exe path for real executables
                mock_which.return_value = "C:\\Python310\\python.exe"

                result = transport._resolve_command_for_platform(["python", "-m", "module"])

                assert result == ["C:\\Python310\\python.exe", "-m", "module"]

    def test_uvx_resolution(self):
        """uvx (which is a real .exe) should also be resolved correctly."""
        transport = StdioTransport(command=["uvx"])

        with patch("gatekit.transport.stdio.sys.platform", "win32"):
            with patch("gatekit.transport.stdio.shutil.which") as mock_which:
                mock_which.return_value = "C:\\Users\\user\\.local\\bin\\uvx.exe"

                result = transport._resolve_command_for_platform(["uvx", "mcp-server-sqlite"])

                assert result == ["C:\\Users\\user\\.local\\bin\\uvx.exe", "mcp-server-sqlite"]


class TestResolveCommandIntegration:
    """Integration-style tests that verify the resolution works with real shutil.which."""

    @pytest.mark.windows_only
    def test_npx_resolves_to_cmd_on_windows(self):
        """On actual Windows, npx should resolve to npx.cmd or npx.CMD."""
        import shutil

        transport = StdioTransport(command=["npx"])

        # Only run if npx is actually installed
        if shutil.which("npx") is None:
            pytest.skip("npx not installed")

        result = transport._resolve_command_for_platform(["npx", "-y", "package"])

        # Should resolve to full path with .cmd extension
        assert result[0].lower().endswith(".cmd")
        assert "npx" in result[0].lower()
        assert result[1:] == ["-y", "package"]
