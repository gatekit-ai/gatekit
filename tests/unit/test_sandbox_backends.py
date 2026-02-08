"""Unit tests for sandbox backend implementations."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from gatekit.sandbox.backends.base import SandboxBackend, SandboxProfile
from gatekit.sandbox.backends.seatbelt import SeatbeltBackend
from gatekit.sandbox.backends.bubblewrap import BubblewrapBackend


class TestSandboxProfile:
    """Test SandboxProfile dataclass defaults."""

    def test_defaults(self):
        profile = SandboxProfile()
        assert profile.read_write_paths == []
        assert profile.deny_paths == []
        assert profile.allow_network is True

    def test_custom_values(self):
        profile = SandboxProfile(
            read_write_paths=[Path("/data")],
            deny_paths=[Path.home() / ".ssh"],
            allow_network=False,
        )
        assert len(profile.read_write_paths) == 1
        assert len(profile.deny_paths) == 1
        assert profile.allow_network is False


class TestSeatbeltBackend:
    """Test macOS Seatbelt backend command wrapping and profile generation."""

    def test_name(self):
        backend = SeatbeltBackend()
        assert backend.name == "seatbelt"

    @patch("shutil.which", return_value="/usr/bin/sandbox-exec")
    def test_is_available_when_present(self, mock_which):
        backend = SeatbeltBackend()
        assert backend.is_available() is True

    @patch("shutil.which", return_value=None)
    def test_is_available_when_missing(self, mock_which):
        backend = SeatbeltBackend()
        assert backend.is_available() is False

    def test_wrap_command_structure(self):
        """Verify the wrapped command has the correct structure."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()
        cmd = ["node", "server.js"]

        wrapped = backend.wrap_command(cmd, profile)

        # Should start with sandbox-exec -f <path> --
        assert wrapped[0] == "sandbox-exec"
        assert wrapped[1] == "-f"
        assert wrapped[2].endswith(".sb")
        assert wrapped[3] == "--"
        assert wrapped[4:] == ["node", "server.js"]

        # Cleanup temp file
        backend.cleanup()

    def test_wrap_command_creates_temp_profile(self):
        """Profile file should exist after wrap_command."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()
        wrapped = backend.wrap_command(["echo", "test"], profile)

        profile_path = Path(wrapped[2])
        assert profile_path.exists()
        content = profile_path.read_text()
        assert "(version 1)" in content
        # Profile should deny writes globally
        assert "(deny file-write*)" in content

        backend.cleanup()
        assert not profile_path.exists()

    def test_profile_denies_home_directory_reads(self):
        """Profile should deny reads in the home directory by default."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        home = str(Path.home())
        assert f'(deny file-read* (subpath "{home}"' in content or \
               f"(deny file-read* (subpath \"{home}\"" in content

        backend.cleanup()

    def test_profile_includes_system_read_paths(self):
        """Profile should allow reading system paths."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        # Key system paths should be readable
        assert '(allow file-read* (subpath "/usr"))' in content
        assert '(allow file-read* (subpath "/bin"))' in content
        assert '(allow file-read* (subpath "/etc"))' in content

        backend.cleanup()

    def test_profile_denies_network_when_requested(self):
        backend = SeatbeltBackend()
        profile = SandboxProfile(allow_network=False)

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        assert "(deny network-outbound)" in content
        # Unix domain sockets should still be allowed
        assert "(allow network-outbound (local unix))" in content

        backend.cleanup()

    def test_profile_allows_network_by_default(self):
        backend = SeatbeltBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        assert "deny network-outbound" not in content

        backend.cleanup()

    def test_profile_denies_writes_by_default(self):
        """Profile should deny all file writes, then allow /tmp."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        lines = content.strip().splitlines()
        # (deny file-write*) should come after (allow default)
        allow_default_idx = next(i for i, l in enumerate(lines) if "(allow default)" in l)
        deny_write_idx = next(i for i, l in enumerate(lines) if l.strip() == "(deny file-write*)")
        assert deny_write_idx > allow_default_idx

        # /tmp should be explicitly allowed for writes
        assert '(allow file-write* (subpath "/tmp"))' in content

        backend.cleanup()

    def test_profile_includes_rw_paths(self):
        backend = SeatbeltBackend()
        rw_path = Path("/tmp/workspace")
        profile = SandboxProfile(read_write_paths=[rw_path])

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        # Path may resolve (e.g. /tmp -> /private/tmp on macOS)
        resolved = str(rw_path.expanduser().resolve())
        assert f'(allow file-write* (subpath "{resolved}")' in content

        backend.cleanup()

    def test_profile_allows_temp_dirs(self):
        """Profile should allow read+write for /tmp and macOS temp dirs."""
        backend = SeatbeltBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)
        content = Path(wrapped[2]).read_text()

        assert '(allow file-read* (subpath "/tmp"))' in content
        assert '(allow file-write* (subpath "/tmp"))' in content
        assert '(allow file-read* (subpath "/private/tmp"))' in content
        assert '(allow file-write* (subpath "/private/tmp"))' in content

        backend.cleanup()

    def test_cleanup_idempotent(self):
        """Multiple cleanup calls should not raise."""
        backend = SeatbeltBackend()
        backend.cleanup()
        backend.cleanup()

    def test_availability_diagnostic(self):
        backend = SeatbeltBackend()
        diag = backend.availability_diagnostic()
        assert "sandbox-exec" in diag


class TestBubblewrapBackend:
    """Test Linux bubblewrap backend command wrapping."""

    def test_name(self):
        backend = BubblewrapBackend()
        assert backend.name == "bubblewrap"

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    @patch("subprocess.run")
    def test_is_available_when_functional(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        backend = BubblewrapBackend()
        assert backend.is_available() is True

    @patch("shutil.which", return_value=None)
    def test_is_available_when_not_installed(self, mock_which):
        backend = BubblewrapBackend()
        assert backend.is_available() is False

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    @patch("subprocess.run")
    def test_is_available_when_apparmor_blocks(self, mock_run, mock_which):
        """Ubuntu AppArmor may block user namespaces."""
        mock_run.return_value = MagicMock(returncode=1)
        backend = BubblewrapBackend()
        assert backend.is_available() is False

    def test_wrap_command_basic_structure(self):
        backend = BubblewrapBackend()
        profile = SandboxProfile()
        cmd = ["node", "server.js"]

        wrapped = backend.wrap_command(cmd, profile)

        assert wrapped[0] == "bwrap"
        assert "--ro-bind" in wrapped
        assert "--die-with-parent" in wrapped
        assert "--" in wrapped
        # Original command should be at the end
        idx = wrapped.index("--")
        assert wrapped[idx + 1:] == ["node", "server.js"]

    def test_wrap_command_selective_system_mounts(self):
        """Backend should selectively mount system paths instead of --ro-bind / /."""
        backend = BubblewrapBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)

        # Should NOT have --ro-bind / / (the old approach)
        for i, arg in enumerate(wrapped):
            if arg == "--ro-bind" and i + 1 < len(wrapped) and wrapped[i + 1] == "/":
                if i + 2 < len(wrapped) and wrapped[i + 2] == "/":
                    pytest.fail("Should not have --ro-bind / / (deny-all model)")

        # Should have selective system path mounts
        ro_bind_targets = []
        for i, arg in enumerate(wrapped):
            if arg == "--ro-bind" and i + 2 < len(wrapped):
                ro_bind_targets.append(wrapped[i + 1])
        # At least /usr and /bin should be mounted
        assert any("/usr" in t for t in ro_bind_targets)

    def test_wrap_command_deny_paths_as_tmpfs(self, tmp_path):
        """Existing sensitive paths should be overlaid with empty tmpfs."""
        backend = BubblewrapBackend()
        # Use real temp dirs so they pass the is_dir() check
        deny1 = tmp_path / "secret1"
        deny2 = tmp_path / "secret2"
        deny1.mkdir()
        deny2.mkdir()
        profile = SandboxProfile(deny_paths=[deny1, deny2])

        wrapped = backend.wrap_command(["echo"], profile)

        # Find --tmpfs arguments (beyond the /tmp one)
        tmpfs_paths = []
        for i, arg in enumerate(wrapped):
            if arg == "--tmpfs" and i + 1 < len(wrapped):
                tmpfs_paths.append(wrapped[i + 1])

        assert str(deny1.resolve()) in tmpfs_paths
        assert str(deny2.resolve()) in tmpfs_paths

    def test_wrap_command_deny_paths_after_bind_mounts(self, tmp_path):
        """Deny --tmpfs mounts must come after --bind mounts to prevent re-exposure."""
        backend = BubblewrapBackend()
        deny_dir = tmp_path / "sensitive"
        deny_dir.mkdir()
        rw_dir = tmp_path / "workspace"
        rw_dir.mkdir()

        profile = SandboxProfile(
            read_write_paths=[rw_dir],
            deny_paths=[deny_dir],
        )

        wrapped = backend.wrap_command(["echo"], profile)

        # Find positions of --bind and deny --tmpfs
        bind_idx = None
        deny_tmpfs_idx = None
        for i, arg in enumerate(wrapped):
            if arg == "--bind" and i + 1 < len(wrapped) and wrapped[i + 1] == str(rw_dir.resolve()):
                bind_idx = i
            if arg == "--tmpfs" and i + 1 < len(wrapped) and wrapped[i + 1] == str(deny_dir.resolve()):
                deny_tmpfs_idx = i

        assert bind_idx is not None, "Should have a --bind for rw path"
        assert deny_tmpfs_idx is not None, "Should have a --tmpfs for deny path"
        assert deny_tmpfs_idx > bind_idx, "Deny --tmpfs must come after --bind"

    def test_wrap_command_creates_dir_for_nonexistent_deny_paths(self):
        """Non-existent deny paths should use --dir + --tmpfs to prevent creation."""
        backend = BubblewrapBackend()
        profile = SandboxProfile(
            deny_paths=[Path("/nonexistent/path/that/does/not/exist")]
        )

        wrapped = backend.wrap_command(["echo"], profile)

        # Should have --dir followed by --tmpfs for the non-existent path
        target = "/nonexistent/path/that/does/not/exist"
        found_dir = False
        for i, arg in enumerate(wrapped):
            if arg == "--dir" and i + 1 < len(wrapped) and wrapped[i + 1] == target:
                # Next pair should be --tmpfs for the same path
                assert i + 2 < len(wrapped) and wrapped[i + 2] == "--tmpfs"
                assert i + 3 < len(wrapped) and wrapped[i + 3] == target
                found_dir = True
                break

        assert found_dir, "Should use --dir + --tmpfs for non-existent deny path"

    def test_wrap_command_deny_file_paths_with_dev_null(self, tmp_path):
        """Existing file deny paths should be replaced with /dev/null."""
        backend = BubblewrapBackend()
        cred_file = tmp_path / "git-credentials"
        cred_file.write_text("secret-token")

        profile = SandboxProfile(deny_paths=[cred_file])

        wrapped = backend.wrap_command(["echo"], profile)

        # Should have --ro-bind /dev/null <file> to hide the file contents
        resolved_str = str(cred_file.resolve())
        found = False
        for i, arg in enumerate(wrapped):
            if arg == "--ro-bind" and i + 2 < len(wrapped):
                if wrapped[i + 1] == "/dev/null" and wrapped[i + 2] == resolved_str:
                    found = True
                    break
        assert found, "File deny paths should be replaced with /dev/null"

    def test_wrap_command_rw_bind_mounts(self, tmp_path):
        backend = BubblewrapBackend()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        profile = SandboxProfile(read_write_paths=[workspace])

        wrapped = backend.wrap_command(["echo"], profile)

        # Should have --bind for read-write paths
        bind_indices = [i for i, a in enumerate(wrapped) if a == "--bind"]
        assert len(bind_indices) > 0

    def test_wrap_command_network_isolation(self):
        backend = BubblewrapBackend()
        profile = SandboxProfile(allow_network=False)

        wrapped = backend.wrap_command(["echo"], profile)

        assert "--unshare-net" in wrapped

    def test_wrap_command_network_allowed_by_default(self):
        backend = BubblewrapBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)

        assert "--unshare-net" not in wrapped

    def test_wrap_command_has_dev_mount(self):
        """bwrap should mount /dev for /dev/null, /dev/urandom etc."""
        backend = BubblewrapBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)

        idx = wrapped.index("--dev")
        assert wrapped[idx + 1] == "/dev"

    def test_wrap_command_has_proc_mount(self):
        """bwrap should mount /proc."""
        backend = BubblewrapBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)

        idx = wrapped.index("--proc")
        assert wrapped[idx + 1] == "/proc"

    def test_wrap_command_has_tmp_tmpfs(self):
        """bwrap should mount a fresh tmpfs for /tmp."""
        backend = BubblewrapBackend()
        profile = SandboxProfile()

        wrapped = backend.wrap_command(["echo"], profile)

        # Find --tmpfs /tmp
        found = False
        for i, arg in enumerate(wrapped):
            if arg == "--tmpfs" and i + 1 < len(wrapped) and wrapped[i + 1] == "/tmp":
                found = True
                break
        assert found, "Should have --tmpfs /tmp"

    @patch("shutil.which", return_value=None)
    def test_availability_diagnostic_not_installed(self, mock_which):
        backend = BubblewrapBackend()
        diag = backend.availability_diagnostic()
        assert "apt install" in diag or "not installed" in diag

    @patch("shutil.which", return_value="/usr/bin/bwrap")
    @patch("subprocess.run")
    def test_availability_diagnostic_apparmor(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=1)
        backend = BubblewrapBackend()
        diag = backend.availability_diagnostic()
        assert "AppArmor" in diag or "user namespaces" in diag
