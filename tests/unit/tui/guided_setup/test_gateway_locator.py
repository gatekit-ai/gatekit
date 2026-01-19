"""Unit tests for gatekit-gateway locator with fallback strategies."""

import pytest
from unittest.mock import patch

from gatekit.tui.guided_setup.gateway import locate_gatekit_gateway, validate_gateway_path


class TestGatewayLocator:
    """Test suite for gatekit-gateway location logic."""

    def test_locate_as_sibling_posix(self, tmp_path):
        """Locate gatekit-gateway when it's a sibling of sys.executable (POSIX)."""
        # Create fake bin directory structure (like venv)
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_gateway = fake_bin / "gatekit-gateway"
        fake_gateway.touch()
        fake_gateway.chmod(0o755)  # Make executable

        # Mock sys.executable to point to our fake bin
        with patch("sys.executable", str(fake_bin / "python")):
            with patch("shutil.which", return_value=None):  # PATH search fails
                gateway_path = locate_gatekit_gateway()

        assert gateway_path == fake_gateway.resolve()
        assert gateway_path.exists()

    def test_locate_as_sibling_windows(self, tmp_path):
        """Locate gatekit-gateway.exe when it's a sibling of sys.executable (Windows)."""
        # Create fake Scripts directory structure (like Windows venv)
        fake_scripts = tmp_path / "Scripts"
        fake_scripts.mkdir()
        fake_gateway = fake_scripts / "gatekit-gateway.exe"
        fake_gateway.touch()

        # Mock sys.executable to point to our fake Scripts
        with patch("sys.executable", str(fake_scripts / "python.exe")):
            with patch("shutil.which", return_value=None):  # PATH search fails
                gateway_path = locate_gatekit_gateway()

        assert gateway_path == fake_gateway.resolve()
        assert gateway_path.exists()

    def test_locate_via_path(self, tmp_path):
        """Locate gatekit-gateway via PATH when not a sibling (like --user install)."""
        # Create fake structure where gateway is NOT a sibling
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_local_bin = tmp_path / ".local" / "bin"
        fake_local_bin.mkdir(parents=True)
        fake_gateway = fake_local_bin / "gatekit-gateway"
        fake_gateway.touch()
        fake_gateway.chmod(0o755)

        # sys.executable is in different directory than gatekit-gateway
        with patch("sys.executable", str(fake_bin / "python")):
            with patch("shutil.which", return_value=str(fake_gateway)):
                gateway_path = locate_gatekit_gateway()

        assert gateway_path == fake_gateway.resolve()
        assert gateway_path.exists()

    def test_prefer_sibling_over_path(self, tmp_path):
        """Prefer sibling location over PATH when both exist."""
        # Create two possible locations
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        sibling_gateway = fake_bin / "gatekit-gateway"
        sibling_gateway.touch()
        sibling_gateway.chmod(0o755)

        other_gateway = tmp_path / "other" / "gatekit-gateway"
        other_gateway.parent.mkdir(parents=True)
        other_gateway.touch()
        other_gateway.chmod(0o755)

        # Both exist, but prefer sibling
        with patch("sys.executable", str(fake_bin / "python")):
            with patch("shutil.which", return_value=str(other_gateway)):
                gateway_path = locate_gatekit_gateway()

        # Should prefer the sibling
        assert gateway_path == sibling_gateway.resolve()

    def test_missing_shows_error(self, tmp_path):
        """If gatekit-gateway not found by any strategy, show clear error."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        # Don't create gatekit-gateway anywhere

        with patch("sys.executable", str(fake_bin / "python")):
            with patch("shutil.which", return_value=None):  # PATH search fails too
                with pytest.raises(FileNotFoundError) as exc_info:
                    locate_gatekit_gateway()

        error_msg = str(exc_info.value).lower()
        assert "gatekit-gateway not found" in error_msg
        assert "sibling" in error_msg
        assert "path" in error_msg

    def test_returns_absolute_path(self, tmp_path):
        """Ensure returned path is always absolute."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_gateway = fake_bin / "gatekit-gateway"
        fake_gateway.touch()
        fake_gateway.chmod(0o755)

        with patch("sys.executable", str(fake_bin / "python")):
            with patch("shutil.which", return_value=None):
                gateway_path = locate_gatekit_gateway()

        # Must be absolute
        assert gateway_path.is_absolute()


class TestGatewayValidation:
    """Test suite for gateway path validation."""

    @pytest.mark.posix_only
    def test_validate_existing_executable_posix(self, tmp_path):
        """Validate an existing executable on POSIX."""
        gateway = tmp_path / "gatekit-gateway"
        gateway.touch()
        gateway.chmod(0o755)

        assert validate_gateway_path(gateway) is True

    @pytest.mark.platform_specific(["Windows"])
    def test_validate_existing_file_windows(self, tmp_path):
        """Validate an existing .exe on Windows."""
        gateway = tmp_path / "gatekit-gateway.exe"
        gateway.touch()

        assert validate_gateway_path(gateway) is True

    def test_validate_nonexistent(self, tmp_path):
        """Validate returns False for nonexistent path."""
        gateway = tmp_path / "nonexistent" / "gatekit-gateway"
        assert validate_gateway_path(gateway) is False

    def test_validate_none(self):
        """Validate returns False for None."""
        assert validate_gateway_path(None) is False

    @pytest.mark.posix_only
    def test_validate_non_executable_posix(self, tmp_path):
        """Validate returns False for non-executable file on POSIX."""
        gateway = tmp_path / "gatekit-gateway"
        gateway.touch()
        gateway.chmod(0o644)  # Not executable

        assert validate_gateway_path(gateway) is False
