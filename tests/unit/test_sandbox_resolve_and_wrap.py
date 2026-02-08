"""Tests for the resolve_and_wrap public API."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gatekit.sandbox import resolve_and_wrap
from gatekit.sandbox.errors import SandboxUnavailableError


class TestResolveAndWrap:
    """Test the main integration function."""

    def test_disabled_returns_original_command(self):
        cmd = ["echo", "test"]
        result_cmd, backend = resolve_and_wrap(cmd, enabled=False)
        assert result_cmd == cmd
        assert backend is None

    def test_disabled_by_default(self):
        cmd = ["echo", "test"]
        result_cmd, backend = resolve_and_wrap(cmd)
        assert result_cmd == cmd
        assert backend is None

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_enabled_wraps_command(self, mock_get_backend):
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "--", "echo", "test"]
        mock_get_backend.return_value = mock_backend

        result_cmd, backend = resolve_and_wrap(
            ["echo", "test"],
            enabled=True,
        )

        assert result_cmd == ["wrapper", "--", "echo", "test"]
        assert backend is mock_backend
        mock_backend.wrap_command.assert_called_once()

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_passes_network_setting(self, mock_get_backend):
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        resolve_and_wrap(["echo"], enabled=True, network=False)

        # Check the SandboxProfile passed to wrap_command
        call_args = mock_backend.wrap_command.call_args
        profile = call_args[0][1]
        assert profile.allow_network is False

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_includes_deny_paths(self, mock_get_backend):
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        resolve_and_wrap(["echo"], enabled=True)

        profile = mock_backend.wrap_command.call_args[0][1]
        deny_path_strs = [str(p) for p in profile.deny_paths]
        # Should include default sensitive paths
        assert any(".ssh" in p for p in deny_path_strs)
        assert any(".gnupg" in p for p in deny_path_strs)
        assert any(".aws" in p for p in deny_path_strs)

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_paths_added_to_rw(self, mock_get_backend):
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        resolve_and_wrap(
            ["echo"],
            enabled=True,
            paths=["/data/workspace"],
        )

        profile = mock_backend.wrap_command.call_args[0][1]
        rw_strs = [str(p) for p in profile.read_write_paths]
        assert any("workspace" in p for p in rw_strs)

    def test_raises_when_no_backend(self):
        with patch("gatekit.sandbox.get_sandbox_backend_or_raise",
                    side_effect=SandboxUnavailableError("not available")):
            with pytest.raises(SandboxUnavailableError):
                resolve_and_wrap(["echo"], enabled=True)

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_no_workspace_inference(self, mock_get_backend):
        """Workspace paths are NOT inferred from command arguments."""
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        resolve_and_wrap(
            ["server", "/tmp/some-dir"],
            enabled=True,
        )

        profile = mock_backend.wrap_command.call_args[0][1]
        rw_strs = [str(p) for p in profile.read_write_paths]
        # /tmp/some-dir should NOT be in rw paths (no inference)
        assert not any("some-dir" in p for p in rw_strs)
