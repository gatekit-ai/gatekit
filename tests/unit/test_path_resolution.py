"""Tests for path resolution utilities."""

import pytest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from gatekit.utils.paths import (
    resolve_config_path,
    ensure_absolute_path,
    expand_user_path,
)


def paths_equivalent(p1: Path, p2: Path) -> bool:
    """Compare paths in a cross-platform way.

    On Windows, '/foo/bar' resolves to 'C:/foo/bar', so we compare
    the path components after any drive letter.
    """
    # Normalize both to posix style for comparison
    s1 = p1.as_posix()
    s2 = p2.as_posix()

    # On Windows, strip drive letter prefix for comparison if comparing
    # Unix-style paths that got a drive letter prepended
    if sys.platform == "win32":
        # Remove drive letter (e.g., "C:") if present
        if len(s1) >= 2 and s1[1] == ":":
            s1 = s1[2:]
        if len(s2) >= 2 and s2[1] == ":":
            s2 = s2[2:]

    return s1 == s2


class TestExpandUserPath:
    """Test home directory expansion functionality."""

    def test_expand_tilde_to_home_directory(self):
        """Test that ~ expands to user home directory."""
        result = expand_user_path("~")
        expected = Path.home()
        assert result == expected

    def test_expand_tilde_with_path_components(self):
        """Test that ~/path expands correctly."""
        result = expand_user_path("~/Documents/config.yaml")
        expected = Path.home() / "Documents" / "config.yaml"
        assert result == expected

    def test_expand_tilde_user_with_mock(self):
        """Test that ~user expands correctly (using mock)."""
        with patch("os.path.expanduser") as mock_expand:
            mock_expand.return_value = "/Users/testuser"
            result = expand_user_path("~testuser")
            expected = Path("/Users/testuser")
            assert result == expected
            mock_expand.assert_called_once_with("~testuser")

    def test_no_expansion_for_regular_paths(self):
        """Test that regular paths without ~ are returned as-is."""
        result = expand_user_path("/absolute/path")
        expected = Path("/absolute/path")
        assert result == expected

        result = expand_user_path("relative/path")
        expected = Path("relative/path")
        assert result == expected

    def test_empty_path_handling(self):
        """Test handling of empty paths."""
        result = expand_user_path("")
        expected = Path("")
        assert result == expected


class TestEnsureAbsolutePath:
    """Test absolute path resolution functionality."""

    def test_absolute_path_unchanged(self):
        """Test that absolute paths are returned unchanged."""
        absolute_path = "/absolute/path/to/file.txt"
        base_dir = Path("/some/base/dir")

        result = ensure_absolute_path(absolute_path, base_dir)
        expected = Path(absolute_path)
        assert paths_equivalent(result, expected)

    def test_relative_path_resolved_to_base_dir(self):
        """Test that relative paths are resolved relative to base_dir."""
        relative_path = "logs/audit.log"
        base_dir = Path("/config/directory")

        result = ensure_absolute_path(relative_path, base_dir)
        expected = Path("/config/directory/logs/audit.log")
        assert paths_equivalent(result, expected)

    def test_current_directory_path(self):
        """Test handling of '.' path."""
        current_dir = "."
        base_dir = Path("/config/directory")

        result = ensure_absolute_path(current_dir, base_dir)
        expected = Path("/config/directory")
        assert paths_equivalent(result, expected)

    def test_parent_directory_path(self):
        """Test handling of '..' path."""
        parent_dir = ".."
        base_dir = Path("/config/directory")

        result = ensure_absolute_path(parent_dir, base_dir)
        expected = Path("/config")
        assert paths_equivalent(result, expected)

    def test_complex_relative_path(self):
        """Test handling of complex relative paths with .. and ."""
        complex_path = "../logs/./audit.log"
        base_dir = Path("/config/directory")

        result = ensure_absolute_path(complex_path, base_dir)
        expected = Path("/config/logs/audit.log")
        assert paths_equivalent(result, expected)

    def test_home_directory_expansion_within_relative_path(self):
        """Test that ~ expansion works within relative path resolution."""
        # Test with actual home directory expansion since mocking os.path.expanduser
        # is complex when Path.resolve() is involved
        tilde_path = "~/logs/audit.log"
        base_dir = Path("/config/directory")

        result = ensure_absolute_path(tilde_path, base_dir)
        expected = Path.home() / "logs" / "audit.log"
        assert result == expected


class TestResolveConfigPath:
    """Test main path resolution function."""

    def test_absolute_path_unchanged(self):
        """Test that absolute paths are returned unchanged."""
        absolute_path = "/absolute/path/to/file.txt"
        config_dir = Path("/config/directory")

        result = resolve_config_path(absolute_path, config_dir)
        expected = Path(absolute_path)
        assert paths_equivalent(result, expected)

    def test_relative_path_resolved_to_config_dir(self):
        """Test that relative paths are resolved relative to config directory."""
        relative_path = "logs/audit.log"
        config_dir = Path("/config/directory")

        result = resolve_config_path(relative_path, config_dir)
        expected = Path("/config/directory/logs/audit.log")
        assert paths_equivalent(result, expected)

    def test_home_directory_expansion(self):
        """Test that ~ expansion works in config path resolution."""
        tilde_path = "~/Documents/gatekit/logs/audit.log"
        config_dir = Path("/config/directory")

        result = resolve_config_path(tilde_path, config_dir)
        expected = Path.home() / "Documents" / "gatekit" / "logs" / "audit.log"
        assert result == expected

    def test_empty_path_handling(self):
        """Test handling of empty paths."""
        config_dir = Path("/config/directory")

        with pytest.raises(ValueError, match="Path cannot be empty"):
            resolve_config_path("", config_dir)

    def test_whitespace_only_path_handling(self):
        """Test handling of whitespace-only paths."""
        config_dir = Path("/config/directory")

        with pytest.raises(ValueError, match="Path cannot be empty"):
            resolve_config_path("   ", config_dir)

    def test_none_path_handling(self):
        """Test handling of None paths."""
        config_dir = Path("/config/directory")

        with pytest.raises(TypeError, match="Path must be a string"):
            resolve_config_path(None, config_dir)

    def test_non_string_path_handling(self):
        """Test handling of non-string paths."""
        config_dir = Path("/config/directory")

        with pytest.raises(TypeError, match="Path must be a string"):
            resolve_config_path(123, config_dir)

    def test_config_dir_as_string(self):
        """Test that config_dir can be passed as a string."""
        relative_path = "logs/audit.log"
        config_dir_str = "/config/directory"

        result = resolve_config_path(relative_path, config_dir_str)
        expected = Path("/config/directory/logs/audit.log")
        assert paths_equivalent(result, expected)

    def test_complex_path_resolution(self):
        """Test complex path resolution with multiple components."""
        complex_path = "../logs/./subdirectory/../audit.log"
        config_dir = Path("/config/directory")

        result = resolve_config_path(complex_path, config_dir)
        expected = Path("/config/logs/audit.log")
        assert paths_equivalent(result, expected)


class TestPathResolutionIntegration:
    """Integration tests for path resolution with real filesystem."""

    def test_resolve_path_with_real_filesystem(self):
        """Test path resolution with real filesystem operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create a config directory
            config_dir = temp_path / "config"
            config_dir.mkdir()

            # Create a logs directory
            logs_dir = temp_path / "logs"
            logs_dir.mkdir()

            # Test relative path resolution
            relative_path = "../logs/audit.log"
            result = resolve_config_path(relative_path, config_dir)
            expected = logs_dir / "audit.log"

            # Resolve both paths to compare them properly
            assert result.resolve() == expected.resolve()

    def test_symlink_handling(self):
        """Test path resolution with symbolic links."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create directories
            config_dir = temp_path / "config"
            config_dir.mkdir()
            actual_logs = temp_path / "actual_logs"
            actual_logs.mkdir()

            # Create a symbolic link
            link_logs = temp_path / "logs"
            try:
                link_logs.symlink_to(actual_logs)

                # Test relative path through symlink
                relative_path = "../logs/audit.log"
                result = resolve_config_path(relative_path, config_dir)

                # Should resolve to the actual location through the symlink
                expected = actual_logs / "audit.log"
                assert result.resolve() == expected.resolve()

            except OSError:
                # Skip test if symlinks aren't available (Windows requires Developer Mode or admin)
                pytest.skip("Symbolic links not available (on Windows, enable Developer Mode or run as admin)")

    def test_unicode_path_support(self):
        """Test path resolution with Unicode characters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create config directory with Unicode name
            config_dir = temp_path / "配置"
            config_dir.mkdir()

            # Test Unicode path resolution
            unicode_path = "日志/audit.log"
            result = resolve_config_path(unicode_path, config_dir)
            expected = config_dir / "日志" / "audit.log"

            # Compare resolved paths to handle symlink differences
            assert result.resolve() == expected.resolve()
            # Use as_posix() for cross-platform path string comparison
            assert result.as_posix().endswith("日志/audit.log")


class TestErrorHandling:
    """Test error handling in path resolution."""

    def test_invalid_path_characters(self):
        """Test handling of invalid path characters."""
        config_dir = Path("/config/directory")

        # Test path with null character (invalid on most filesystems)
        invalid_path = "logs/audit\x00.log"

        # Should raise an error when resolve() is called due to null byte/character
        # Error message differs between platforms: "embedded null byte" (Unix) vs
        # "embedded null character" (Windows)
        with pytest.raises(ValueError, match="embedded null"):
            resolve_config_path(invalid_path, config_dir)

    def test_very_long_path(self):
        """Test handling of very long paths."""
        config_dir = Path("/config/directory")

        # Create a very long path (exceeding typical filesystem limits)
        long_component = "a" * 1000
        long_path = f"logs/{long_component}/audit.log"

        # Should resolve without error (filesystem limits enforced elsewhere)
        result = resolve_config_path(long_path, config_dir)
        assert isinstance(result, Path)
        assert long_component in str(result)
