"""Security-focused tests for sandbox feature.

These tests verify that the sandbox correctly handles edge cases that
could lead to credential leakage or sandbox escapes.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gatekit.sandbox import resolve_and_wrap, _DENY_PATHS
from gatekit.sandbox.backends.base import SandboxProfile
from gatekit.sandbox.backends.seatbelt import SeatbeltBackend, _escape_seatbelt_string
from gatekit.sandbox.backends.bubblewrap import BubblewrapBackend


class TestSeatbeltPathEscaping:
    """Verify Seatbelt profile correctly escapes special characters in paths."""

    def test_escape_double_quotes(self):
        assert _escape_seatbelt_string('/tmp/my"dir') == '/tmp/my\\"dir'

    def test_escape_backslashes(self):
        assert _escape_seatbelt_string("/tmp/my\\dir") == "/tmp/my\\\\dir"

    def test_escape_both(self):
        result = _escape_seatbelt_string('/tmp/"test\\path"')
        assert result == '/tmp/\\"test\\\\path\\"'

    def test_normal_path_unchanged(self):
        assert _escape_seatbelt_string("/usr/local/bin") == "/usr/local/bin"

    def test_path_with_spaces_unchanged(self):
        assert _escape_seatbelt_string("/tmp/my dir/file") == "/tmp/my dir/file"

    def test_profile_with_quoted_rw_path(self):
        """Profile generation should escape quotes in rw paths."""
        backend = SeatbeltBackend()
        with tempfile.TemporaryDirectory() as td:
            # Create a dir with a quote in the name
            quoted_dir = Path(td) / 'has"quote'
            quoted_dir.mkdir()
            profile = SandboxProfile(read_write_paths=[quoted_dir])

            wrapped = backend.wrap_command(["echo"], profile)
            content = Path(wrapped[2]).read_text()

            # The quote must be escaped in the profile
            assert '\\"' in content
            # The raw (unescaped) quote should NOT appear — i.e., every `"` in
            # path position should be preceded by a backslash.  A simple check:
            # after removing all escaped quotes (\\"), the remaining structure
            # should still have balanced quotes (the Seatbelt delimiters).
            import re
            for line in content.splitlines():
                if "subpath" in line:
                    # Strip escaped quotes, then check balanced delimiters
                    stripped = line.replace('\\"', '')
                    assert stripped.count('"') % 2 == 0, (
                        f"Unbalanced quotes after removing escapes in: {line}"
                    )

            backend.cleanup()

    def test_profile_with_backslash_rw_path(self):
        """Profile generation should escape backslashes in rw paths."""
        backend = SeatbeltBackend()
        with tempfile.TemporaryDirectory() as td:
            slash_dir = Path(td) / "has\\backslash"
            slash_dir.mkdir()
            profile = SandboxProfile(read_write_paths=[slash_dir])

            wrapped = backend.wrap_command(["echo"], profile)
            content = Path(wrapped[2]).read_text()

            # Backslash should be escaped in the allow rules
            assert "\\\\" in content

            backend.cleanup()


class TestSeatbeltTempFileManagement:
    """Verify temp profile files are managed correctly."""

    def test_wrap_command_cleans_previous_profile(self):
        """Calling wrap_command twice should not leak the first temp file."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()

        wrapped1 = backend.wrap_command(["echo", "1"], profile)
        path1 = Path(wrapped1[2])
        assert path1.exists()

        wrapped2 = backend.wrap_command(["echo", "2"], profile)
        path2 = Path(wrapped2[2])

        # First profile should have been cleaned up
        assert not path1.exists(), "First temp profile should be cleaned up"
        assert path2.exists(), "Second temp profile should exist"

        backend.cleanup()
        assert not path2.exists()


class TestNoWorkspaceInference:
    """Verify workspace paths are NOT inferred from command arguments."""

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_command_args_not_added_to_rw_paths(self, mock_get_backend, tmp_path):
        """Even if a command argument is a valid directory, it should not become writable."""
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        workspace = tmp_path / "my-project"
        workspace.mkdir()

        resolve_and_wrap(
            ["server", str(workspace)],
            enabled=True,
        )

        profile = mock_backend.wrap_command.call_args[0][1]
        rw_strs = [str(p) for p in profile.read_write_paths]

        # Workspace should NOT be in rw paths (no inference)
        assert not any("my-project" in p for p in rw_strs), (
            "Command arguments should not be inferred as writable paths"
        )

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_explicit_paths_config_used_instead(self, mock_get_backend, tmp_path):
        """Only explicitly configured paths should appear in rw_paths."""
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        workspace = tmp_path / "my-project"
        workspace.mkdir()

        resolve_and_wrap(
            ["server", str(tmp_path / "other")],
            enabled=True,
            paths=[str(workspace)],
        )

        profile = mock_backend.wrap_command.call_args[0][1]
        rw_strs = [str(p) for p in profile.read_write_paths]

        assert any("my-project" in p for p in rw_strs), (
            "Explicitly configured paths should be in rw_paths"
        )


class TestSeatbeltDenyPathWarning:
    """Verify Seatbelt warns when deny paths overlap with allowed paths."""

    def test_warns_when_home_allowed(self):
        """paths: ["~"] should trigger a warning about sensitive paths."""
        import logging

        backend = SeatbeltBackend()
        home = Path.home()
        profile = SandboxProfile(
            read_write_paths=[home],
            deny_paths=[home / ".ssh", home / ".aws"],
        )

        with patch.object(
            logging.getLogger("gatekit.sandbox.backends.seatbelt"),
            "warning",
        ) as mock_warn:
            backend.wrap_command(["echo"], profile)
            # Should have warned about at least one deny path inside home
            assert mock_warn.call_count >= 1
            warn_text = str(mock_warn.call_args_list[0])
            assert "allow-wins" in warn_text or "cannot protect" in warn_text

        backend.cleanup()

    def test_no_warning_when_specific_paths(self):
        """Specific paths that don't overlap deny paths should not warn."""
        import logging

        backend = SeatbeltBackend()
        profile = SandboxProfile(
            read_write_paths=[Path("/tmp/workspace")],
            deny_paths=[Path.home() / ".ssh"],
        )

        with patch.object(
            logging.getLogger("gatekit.sandbox.backends.seatbelt"),
            "warning",
        ) as mock_warn:
            backend.wrap_command(["echo"], profile)
            assert mock_warn.call_count == 0

        backend.cleanup()


class TestCacheDirHandling:
    """Verify cache directories are handled correctly in resolve_and_wrap."""

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_existing_cache_dirs_added(self, mock_get_backend, tmp_path):
        """Cache dirs that exist should be in rw_paths."""
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        # Patch _CACHE_RW_PATHS to use our tmp dirs
        cache_dir = tmp_path / ".cache"
        cache_dir.mkdir()
        with patch("gatekit.sandbox._CACHE_RW_PATHS", [cache_dir]):
            resolve_and_wrap(["echo"], enabled=True)

        profile = mock_backend.wrap_command.call_args[0][1]
        rw_strs = [str(p) for p in profile.read_write_paths]
        assert any(".cache" in p for p in rw_strs)

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_nonexistent_cache_dirs_skipped(self, mock_get_backend, tmp_path):
        """Cache dirs that don't exist should not be in rw_paths."""
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        nonexistent = tmp_path / ".nonexistent-cache"
        with patch("gatekit.sandbox._CACHE_RW_PATHS", [nonexistent]):
            resolve_and_wrap(["echo"], enabled=True)

        profile = mock_backend.wrap_command.call_args[0][1]
        rw_strs = [str(p) for p in profile.read_write_paths]
        assert not any("nonexistent-cache" in p for p in rw_strs)


class TestBwrapMountOrdering:
    """Verify bubblewrap mount ordering for deny-within-allowed scenarios."""

    def test_deny_subdirectory_of_allowed_parent(self, tmp_path):
        """When a deny path is a child of an allowed path, deny --tmpfs must come after --bind."""
        backend = BubblewrapBackend()
        parent = tmp_path / "home"
        parent.mkdir()
        sensitive = parent / ".ssh"
        sensitive.mkdir()

        profile = SandboxProfile(
            read_write_paths=[parent],
            deny_paths=[sensitive],
        )

        wrapped = backend.wrap_command(["echo"], profile)

        # Find positions
        bind_idx = None
        tmpfs_idx = None
        for i, arg in enumerate(wrapped):
            if arg == "--bind" and i + 1 < len(wrapped) and str(parent.resolve()) in wrapped[i + 1]:
                bind_idx = i
            if arg == "--tmpfs" and i + 1 < len(wrapped) and str(sensitive.resolve()) in wrapped[i + 1]:
                tmpfs_idx = i

        assert bind_idx is not None, "Should have --bind for parent"
        assert tmpfs_idx is not None, "Should have --tmpfs for sensitive child"
        assert tmpfs_idx > bind_idx, (
            "Deny --tmpfs must come after parent --bind to actually overlay it"
        )


class TestDefaultDenyPathsCoverage:
    """Verify the default deny paths list is comprehensive."""

    def test_ssh_keys_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any(".ssh" in p for p in deny_strs)

    def test_gpg_keys_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any(".gnupg" in p for p in deny_strs)

    def test_aws_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any(".aws" in p for p in deny_strs)

    def test_azure_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any(".azure" in p for p in deny_strs)

    def test_gcloud_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any("gcloud" in p for p in deny_strs)

    def test_kube_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any(".kube" in p for p in deny_strs)

    def test_docker_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any(".docker" in p for p in deny_strs)

    def test_git_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any("git-credentials" in p for p in deny_strs)

    def test_vault_token_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any("vault-token" in p for p in deny_strs)

    def test_terraform_credentials_denied(self):
        deny_strs = [str(p) for p in _DENY_PATHS]
        assert any("terraform" in p for p in deny_strs)

    @patch("gatekit.sandbox.get_sandbox_backend_or_raise")
    def test_all_deny_paths_included_in_profile(self, mock_get_backend):
        """All default deny paths should appear in the generated profile."""
        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo"]
        mock_get_backend.return_value = mock_backend

        resolve_and_wrap(["echo"], enabled=True)

        profile = mock_backend.wrap_command.call_args[0][1]
        assert len(profile.deny_paths) >= len(_DENY_PATHS)


class TestSandboxConfigEquality:
    """Verify SandboxConfig equality for reconnect detection."""

    def test_none_vs_disabled_config(self):
        """None and SandboxConfig(enabled=False) should compare as different objects."""
        from gatekit.config.models import SandboxConfig

        config = SandboxConfig(enabled=False)
        # None != SandboxConfig is always true — reconnect will trigger
        assert config is not None

    def test_same_config_is_equal(self):
        from gatekit.config.models import SandboxConfig

        a = SandboxConfig(enabled=True, paths=["/data"])
        b = SandboxConfig(enabled=True, paths=["/data"])
        assert a == b

    def test_different_paths_not_equal(self):
        from gatekit.config.models import SandboxConfig

        a = SandboxConfig(enabled=True, paths=["/data"])
        b = SandboxConfig(enabled=True, paths=["/other"])
        assert a != b

    def test_different_network_not_equal(self):
        from gatekit.config.models import SandboxConfig

        a = SandboxConfig(enabled=True, network=True)
        b = SandboxConfig(enabled=True, network=False)
        assert a != b

    def test_empty_vs_populated_paths_not_equal(self):
        from gatekit.config.models import SandboxConfig

        a = SandboxConfig(enabled=True, paths=[])
        b = SandboxConfig(enabled=True, paths=["/data"])
        assert a != b
