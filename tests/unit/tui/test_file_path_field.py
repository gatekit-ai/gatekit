"""Tests for FilePathField widget start directory resolution."""

import os
from pathlib import Path

import pytest

from gatekit.tui.widgets.file_path_field import resolve_start_directory


class TestResolveStartDirectory:
    """Tests for the resolve_start_directory helper function."""

    def test_explicit_start_directory_takes_priority(self, tmp_path: Path):
        """Explicit start_directory should be used when it exists."""
        override_dir = tmp_path / "override"
        override_dir.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        result = resolve_start_directory(
            value="some/path.json",
            start_directory=override_dir,
            config_dir=config_dir,
        )

        assert result == override_dir

    def test_nonexistent_start_directory_ignored(self, tmp_path: Path):
        """Non-existent start_directory should fall through to value-based logic."""
        nonexistent = tmp_path / "does_not_exist"
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        result = resolve_start_directory(
            value="",
            start_directory=nonexistent,
            config_dir=config_dir,
        )

        # Should fall back to config_dir since start_directory doesn't exist
        assert result == config_dir

    def test_absolute_path_uses_parent(self, tmp_path: Path):
        """Absolute paths should resolve to their parent directory."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        file_path = logs_dir / "audit.json"

        result = resolve_start_directory(
            value=str(file_path),
            start_directory=None,
            config_dir=None,
        )

        assert result == logs_dir

    def test_absolute_path_nonexistent_parent_falls_back(self, tmp_path: Path):
        """Absolute path with non-existent parent should fall back to config_dir."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        nonexistent_file = tmp_path / "nonexistent_dir" / "audit.json"

        result = resolve_start_directory(
            value=str(nonexistent_file),
            start_directory=None,
            config_dir=config_dir,
        )

        assert result == config_dir

    def test_tilde_path_expands_and_uses_parent(self):
        """Paths with ~ should expand and use the expanded parent."""
        # Use home directory which always exists
        result = resolve_start_directory(
            value="~/some_file.json",
            start_directory=None,
            config_dir=None,
        )

        # Should be the home directory (parent of ~/some_file.json)
        assert result == Path.home()

    @pytest.mark.windows_only
    def test_windows_env_var_expands(self, tmp_path: Path):
        """Windows environment variables should expand correctly."""
        # LOCALAPPDATA always exists on Windows
        if "LOCALAPPDATA" not in os.environ:
            pytest.skip("LOCALAPPDATA not set")

        result = resolve_start_directory(
            value="%LOCALAPPDATA%\\some_file.json",
            start_directory=None,
            config_dir=None,
        )

        expected_parent = Path(os.environ["LOCALAPPDATA"])
        assert result == expected_parent

    def test_relative_path_with_config_dir_resolves_correctly(self, tmp_path: Path):
        """Relative paths should resolve against config_dir."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        logs_dir = config_dir / "logs"
        logs_dir.mkdir()

        result = resolve_start_directory(
            value="logs/audit.json",
            start_directory=None,
            config_dir=config_dir,
        )

        assert result == logs_dir

    def test_relative_path_nonexistent_falls_back_to_config_dir(self, tmp_path: Path):
        """Relative path with non-existent parent falls back to config_dir."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        result = resolve_start_directory(
            value="nonexistent/subdir/audit.json",
            start_directory=None,
            config_dir=config_dir,
        )

        assert result == config_dir

    def test_relative_path_without_config_dir_tries_cwd(self, tmp_path: Path, monkeypatch):
        """Relative path without config_dir should try cwd."""
        # Create a subdirectory in tmp_path and set it as cwd
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()
        logs_dir = work_dir / "logs"
        logs_dir.mkdir()
        monkeypatch.chdir(work_dir)

        result = resolve_start_directory(
            value="logs/audit.json",
            start_directory=None,
            config_dir=None,
        )

        assert result == logs_dir

    def test_relative_path_without_config_dir_nonexistent_falls_back_to_cwd(
        self, tmp_path: Path, monkeypatch
    ):
        """Relative path without config_dir and non-existent parent falls back to cwd."""
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)

        result = resolve_start_directory(
            value="nonexistent/audit.json",
            start_directory=None,
            config_dir=None,
        )

        assert result == work_dir

    def test_empty_value_uses_config_dir(self, tmp_path: Path):
        """Empty value should use config_dir."""
        config_dir = tmp_path / "configs"
        config_dir.mkdir()

        result = resolve_start_directory(
            value="",
            start_directory=None,
            config_dir=config_dir,
        )

        assert result == config_dir

    def test_empty_value_without_config_dir_uses_cwd(self, tmp_path: Path, monkeypatch):
        """Empty value without config_dir should use cwd."""
        work_dir = tmp_path / "workdir"
        work_dir.mkdir()
        monkeypatch.chdir(work_dir)

        result = resolve_start_directory(
            value="",
            start_directory=None,
            config_dir=None,
        )

        assert result == work_dir
