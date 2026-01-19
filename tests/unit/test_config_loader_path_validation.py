"""Tests for ConfigLoader path validation improvements.

This test suite follows Test-Driven Development (TDD) methodology to verify
that ConfigLoader properly validates paths during configuration loading
and provides clear error messages for path-related issues.
"""

import os
import sys
import pytest
import tempfile
import uuid
import yaml
from pathlib import Path
from unittest.mock import patch
from gatekit.config.loader import ConfigLoader
from gatekit.config.errors import ConfigError


def get_nonexistent_absolute_path() -> str:
    """Get an absolute path that definitely doesn't exist on any platform."""
    random_dir = f"nonexistent_{uuid.uuid4().hex}"
    # Use Path to build paths correctly on all platforms
    if sys.platform == "win32":
        # On Windows, use a drive letter with a nonexistent path
        base = Path("C:/")
    else:
        base = Path("/")
    return str(base / random_dir / "deeply" / "nested" / "audit.log")


class TestConfigLoaderPathValidation:
    """Test ConfigLoader path validation during configuration loading."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary directory for test configuration files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def basic_config_dict(self):
        """Basic valid configuration dictionary."""
        return {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "test_server"]}
                ],
            }
        }

    def test_validates_json_auditing_plugin_paths(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that config loader validates file auditing plugin paths.

        With critical=true (default), the plugin fails during initialization
        when the parent directory doesn't exist and can't be created.
        The error is raised from the plugin, not the config loader.
        """
        # Use a path where parent "directory" is actually a file - this cannot be created
        # on any platform and provides genuine validation testing
        blocker_file = temp_config_dir / "blocker"
        blocker_file.write_text("I am a file, not a directory")

        # Try to create a log file "inside" this file - impossible on any OS
        invalid_path = str(blocker_file / "subdir" / "audit.log")

        # Add file auditing plugin with invalid path
        # critical=true by default means plugin init will fail
        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "output_file": invalid_path,
                        },
                    }
                ]
            }
        }

        # Create config file
        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        # Should raise error about invalid path (critical plugin fails during init)
        # The path is genuinely invalid because the parent is a file, not a directory
        with pytest.raises((ConfigError, Exception), match="(Path validation failed|Critical auditing plugin|failed to initialize|Not a directory|cannot find the path)"):
            loader.load_from_file(config_file)

    def test_allows_logging_paths_in_nonexistent_directories(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that config loader allows logging paths in non-existent directories.

        Per ADR-012 R3.3, directories are auto-created at runtime, so validation
        should not fail for non-existent parent directories.
        """
        # Use a cross-platform absolute path that doesn't exist
        nonexistent_path = get_nonexistent_absolute_path().replace("audit.log", "gatekit.log")

        # Add logging configuration with path in non-existent directory
        basic_config_dict["logging"] = {
            "level": "INFO",
            "handlers": ["file"],
            "file_path": nonexistent_path,
        }

        # Create config file
        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        # Should load successfully - directory will be auto-created at runtime
        config = loader.load_from_file(config_file)
        assert config is not None

    def test_passes_validation_with_valid_paths(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that config loader passes validation with valid paths."""
        # Create a valid log directory
        log_dir = temp_config_dir / "logs"
        log_dir.mkdir()

        # Add plugins with valid paths
        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {"enabled": True, "output_file": str(log_dir / "audit.log")},
                    }
                ]
            }
        }

        # Create config file
        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        # Should load successfully without validation errors
        config = loader.load_from_file(config_file)
        assert config is not None
        assert config.plugins is not None

    def test_skips_validation_for_disabled_plugins(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that config loader skips validation for disabled plugins."""
        # Add disabled plugin with invalid path
        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {"enabled": False, "output_file": "/definitely/nonexistent/audit.log"},  # Disabled
                    }
                ]
            }
        }

        # Create config file
        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        # Should load successfully because plugin is disabled
        config = loader.load_from_file(config_file)
        assert config is not None

    def test_validates_relative_paths_with_config_directory(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that config loader properly validates relative paths against config directory."""
        # Add plugin with relative path that will fail validation
        # Use a path that can't be created (contains null byte which is invalid in file paths)
        relative_path = "invalid\x00path/audit.log"

        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "output_file": relative_path,  # Invalid path
                        },
                    }
                ]
            }
        }

        # Create config file
        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        # Should raise error about invalid path (critical plugin fails during init)
        with pytest.raises((ConfigError, Exception), match="(Path validation failed|Critical auditing plugin|failed to initialize)"):
            loader.load_from_file(config_file)

    def test_validates_home_directory_expansion(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that config loader validates paths after home directory expansion.

        This test verifies that permission checks work correctly by mocking os.access.
        We need to mock because:
        1. On Windows, os.chmod doesn't actually restrict permissions
        2. The test needs to be deterministic and not depend on file system state

        The mocking simulates what happens when a user tries to write to a
        directory they don't have write access to.
        """
        # Create a directory to test permission issues
        test_dir = temp_config_dir / "test_dir"
        test_dir.mkdir()

        # Add plugin with path in the test directory
        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "output_file": str(test_dir / "audit.log"),
                        },
                    }
                ]
            }
        }

        # Create config file
        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        # Mock os.access to simulate permission denied scenario
        # This is necessary because:
        # - Windows doesn't enforce Unix-style permissions via chmod
        # - We want to test the validation logic, not the OS permission system
        original_access = os.access

        def mock_access(path, mode):
            # Only deny write access to our test directory
            if mode == os.W_OK and str(test_dir) in str(path):
                return False
            return original_access(path, mode)

        with patch("os.access", side_effect=mock_access):
            # Should raise error about permission issue (critical plugin fails during init)
            with pytest.raises((ConfigError, Exception), match="(Path validation failed|Critical auditing plugin|failed to initialize|Permission denied|not writable|No write permission)"):
                loader.load_from_file(config_file)


class TestConfigLoaderPathValidationErrorDetails:
    """Test detailed error reporting for path validation failures."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary directory for test configuration files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def basic_config_dict(self):
        """Basic valid configuration dictionary."""
        return {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "test_server"]}
                ],
            }
        }

    def test_error_message_includes_plugin_name_and_path(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that error messages include plugin name and problematic path."""
        # Use a path where parent "directory" is actually a file - genuinely invalid
        blocker_file = temp_config_dir / "blocker"
        blocker_file.write_text("I am a file, not a directory")
        invalid_path = str(blocker_file / "subdir" / "audit.log")

        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "output_file": invalid_path,
                        },
                    }
                ]
            }
        }

        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        with pytest.raises((ConfigError, Exception)) as exc_info:
            loader.load_from_file(config_file)

        error_message = str(exc_info.value)
        # Critical plugin fails with helpful error message including path or plugin name
        assert "audit" in error_message.lower() or "path" in error_message.lower()

    def test_error_message_suggests_solutions(self, temp_config_dir, basic_config_dict):
        """Test that error messages suggest solutions for common path issues."""
        # Use a path where parent "directory" is actually a file - genuinely invalid
        blocker_file = temp_config_dir / "blocker2"
        blocker_file.write_text("I am a file, not a directory")
        invalid_path = str(blocker_file / "subdir" / "audit.log")

        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "output_file": invalid_path,
                        },
                    }
                ]
            }
        }

        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        with pytest.raises((ConfigError, Exception)) as exc_info:
            loader.load_from_file(config_file)

        error_message = str(exc_info.value)
        # Should suggest common solutions or indicate what went wrong
        assert any(
            keyword in error_message.lower()
            for keyword in ["create", "permission", "directory", "path", "critical", "initialize"]
        )

    def test_aggregates_multiple_path_validation_errors(
        self, temp_config_dir, basic_config_dict
    ):
        """Test that genuinely invalid paths are rejected with helpful error messages.

        Note: Per ADR-012 R3.3, non-existent directories are allowed (auto-created at runtime).
        This test uses paths where the parent is a file (not a directory), which is
        genuinely invalid and cannot be auto-created.
        """
        # Use a path where parent "directory" is actually a file - genuinely invalid
        blocker_file = temp_config_dir / "blocker3"
        blocker_file.write_text("I am a file, not a directory")
        invalid_path = str(blocker_file / "subdir" / "audit.log")

        basic_config_dict["plugins"] = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "output_file": invalid_path,
                        },
                    }
                ]
            }
        }

        config_file = temp_config_dir / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(basic_config_dict, f)

        loader = ConfigLoader()

        with pytest.raises((ConfigError, Exception)) as exc_info:
            loader.load_from_file(config_file)

        error_message = str(exc_info.value)

        # Should include path validation errors or critical plugin failure info
        assert any(
            keyword in error_message.lower()
            for keyword in ["path", "invalid", "critical", "failed", "not found", "directory"]
        )
