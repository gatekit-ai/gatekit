"""Unit tests for cross-platform path resolution."""

from pathlib import Path
from unittest.mock import patch

import pytest

from gatekit.tui.platform_paths import get_user_state_dir, get_user_config_dir


class TestGetUserStateDir:
    """Test get_user_state_dir() for all platforms."""

    @patch('sys.platform', 'darwin')
    def test_macos_state_dir(self, tmp_path, monkeypatch):
        """Test macOS returns ~/Library/Application Support/appname."""
        # Mock home directory
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = get_user_state_dir('gatekit')

        expected = tmp_path / 'Library' / 'Application Support' / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'linux')
    def test_linux_state_dir_with_xdg_env(self, tmp_path, monkeypatch):
        """Test Linux with XDG_STATE_HOME set."""
        xdg_state = tmp_path / 'xdg_state'
        monkeypatch.setenv('XDG_STATE_HOME', str(xdg_state))

        result = get_user_state_dir('gatekit')

        expected = xdg_state / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'linux')
    def test_linux_state_dir_without_xdg_env(self, tmp_path, monkeypatch):
        """Test Linux without XDG_STATE_HOME falls back to ~/.local/state."""
        monkeypatch.delenv('XDG_STATE_HOME', raising=False)
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = get_user_state_dir('gatekit')

        expected = tmp_path / '.local' / 'state' / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'win32')
    def test_windows_state_dir_with_localappdata(self, tmp_path, monkeypatch):
        """Test Windows with LOCALAPPDATA env var."""
        localappdata = tmp_path / 'AppData' / 'Local'
        monkeypatch.setenv('LOCALAPPDATA', str(localappdata))

        result = get_user_state_dir('gatekit')

        expected = localappdata / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'win32')
    def test_windows_state_dir_without_localappdata(self, tmp_path, monkeypatch):
        """Test Windows without LOCALAPPDATA falls back to ~\\AppData\\Local."""
        monkeypatch.delenv('LOCALAPPDATA', raising=False)
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        # Mock expanduser to return our temp path
        def mock_expanduser(path):
            if path.startswith('~'):
                return str(tmp_path / path[2:].replace('\\', '/'))
            return path

        monkeypatch.setattr('os.path.expanduser', mock_expanduser)

        result = get_user_state_dir('gatekit')

        # The function should use expanduser fallback
        expected = tmp_path / 'AppData' / 'Local' / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'linux')
    def test_creates_directory_if_not_exists(self, tmp_path, monkeypatch):
        """Test directory is created if it doesn't exist."""
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        monkeypatch.delenv('XDG_STATE_HOME', raising=False)

        result = get_user_state_dir('gatekit')

        assert result.exists()
        assert result.is_dir()

    @pytest.mark.posix_only
    @patch('sys.platform', 'linux')
    def test_secure_permissions_on_unix(self, tmp_path, monkeypatch):
        """Test directory has 0700 permissions on Unix platforms."""
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        monkeypatch.delenv('XDG_STATE_HOME', raising=False)

        result = get_user_state_dir('gatekit')

        # Check permissions are 0700 (owner rwx only)
        stat_info = result.stat()
        mode = stat_info.st_mode & 0o777
        assert mode == 0o700, f"Expected 0700, got {oct(mode)}"

    @pytest.mark.posix_only
    @patch('sys.platform', 'linux')
    def test_enforces_permissions_on_existing_directory(self, tmp_path, monkeypatch):
        """Test permissions are enforced even if directory already exists."""
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        monkeypatch.delenv('XDG_STATE_HOME', raising=False)

        # Create directory with wrong permissions first
        expected_dir = tmp_path / '.local' / 'state' / 'gatekit'
        expected_dir.mkdir(parents=True, mode=0o755)  # Too permissive

        result = get_user_state_dir('gatekit')

        # Check permissions were corrected to 0700
        stat_info = result.stat()
        mode = stat_info.st_mode & 0o777
        assert mode == 0o700, f"Expected 0700, got {oct(mode)}"


class TestGetUserConfigDir:
    """Test get_user_config_dir() for all platforms."""

    @patch('sys.platform', 'darwin')
    def test_macos_config_dir(self, tmp_path, monkeypatch):
        """Test macOS returns ~/Library/Application Support/appname."""
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = get_user_config_dir('gatekit')

        expected = tmp_path / 'Library' / 'Application Support' / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'linux')
    def test_linux_config_dir_with_xdg_env(self, tmp_path, monkeypatch):
        """Test Linux with XDG_CONFIG_HOME set."""
        xdg_config = tmp_path / 'xdg_config'
        monkeypatch.setenv('XDG_CONFIG_HOME', str(xdg_config))

        result = get_user_config_dir('gatekit')

        expected = xdg_config / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'linux')
    def test_linux_config_dir_without_xdg_env(self, tmp_path, monkeypatch):
        """Test Linux without XDG_CONFIG_HOME falls back to ~/.config."""
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)

        result = get_user_config_dir('gatekit')

        expected = tmp_path / '.config' / 'gatekit'
        assert result == expected
        assert result.exists()

    @patch('sys.platform', 'win32')
    def test_windows_config_dir_with_localappdata(self, tmp_path, monkeypatch):
        """Test Windows with LOCALAPPDATA env var."""
        localappdata = tmp_path / 'AppData' / 'Local'
        monkeypatch.setenv('LOCALAPPDATA', str(localappdata))

        result = get_user_config_dir('gatekit')

        expected = localappdata / 'gatekit'
        assert result == expected
        assert result.exists()

    @pytest.mark.posix_only
    @patch('sys.platform', 'linux')
    def test_secure_permissions_on_unix(self, tmp_path, monkeypatch):
        """Test directory has 0700 permissions on Unix platforms."""
        monkeypatch.setattr(Path, 'home', lambda: tmp_path)
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)

        result = get_user_config_dir('gatekit')

        # Check permissions are 0700 (owner rwx only)
        stat_info = result.stat()
        mode = stat_info.st_mode & 0o777
        assert mode == 0o700, f"Expected 0700, got {oct(mode)}"
