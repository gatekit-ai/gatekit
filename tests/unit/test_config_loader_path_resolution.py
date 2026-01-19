"""Tests for ConfigLoader path resolution functionality."""

import pytest
import tempfile
import yaml
from pathlib import Path

from gatekit.config.loader import ConfigLoader
from gatekit.config.models import ProxyConfig


class TestConfigLoaderPathResolution:
    """Test path resolution integration in ConfigLoader."""

    def test_config_loader_stores_config_directory(self):
        """Test that ConfigLoader stores the config file's directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "gatekit.yaml"

            # Create minimal valid config
            config_data = {
                "proxy": {
                    "transport": "stdio",
                    "upstreams": [{"name": "test_server", "command": ["echo", "test"]}],
                }
            }

            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            loader = ConfigLoader()
            config = loader.load_from_file(config_file)

            # Verify that config directory is stored
            assert hasattr(loader, "config_directory")
            assert loader.config_directory.resolve() == temp_path.resolve()
            assert isinstance(config, ProxyConfig)

    def test_config_loader_resolves_relative_config_file_path(self):
        """Test that ConfigLoader resolves relative config file paths to absolute."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "gatekit.yaml"

            # Create minimal valid config
            config_data = {
                "proxy": {
                    "transport": "stdio",
                    "upstreams": [{"name": "test_server", "command": ["echo", "test"]}],
                }
            }

            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            # Load using relative path
            loader = ConfigLoader()
            relative_path = Path("./gatekit.yaml")

            # Change working directory to temp_dir to test relative path resolution
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                loader.load_from_file(relative_path)

                # Config directory should be absolute even if input was relative
                assert loader.config_directory.resolve() == temp_path.resolve()
                assert loader.config_directory.is_absolute()

            finally:
                os.chdir(original_cwd)

    def test_config_loader_passes_config_directory_to_logging_config(self):
        """Test that ConfigLoader passes config directory to LoggingConfig."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "gatekit.yaml"

            # Create logs directory to satisfy path validation
            (temp_path / "logs").mkdir()

            # Create config with relative logging path
            config_data = {
                "proxy": {
                    "transport": "stdio",
                    "upstreams": [{"name": "test_server", "command": ["echo", "test"]}],
                },
                "logging": {
                    "level": "INFO",
                    "handlers": ["file"],
                    "file_path": "logs/gatekit.log",  # Relative path
                },
            }

            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            loader = ConfigLoader()
            config = loader.load_from_file(config_file)

            # Verify logging config has resolved path
            assert config.logging is not None
            assert config.logging.file_path is not None
            assert config.logging.file_path.is_absolute()
            expected_path = temp_path / "logs" / "gatekit.log"
            assert config.logging.file_path.resolve() == expected_path.resolve()

    def test_config_loader_passes_config_directory_to_plugin_configs(self):
        """Test that ConfigLoader passes config directory to plugin configs."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "gatekit.yaml"

            # No need to create directory - using absolute path in temp_path

            # Create config with plugin that has relative path
            config_data = {
                "proxy": {
                    "transport": "stdio",
                    "upstreams": [{"name": "test_server", "command": ["echo", "test"]}],
                },
                "plugins": {
                    "auditing": {
                        "_global": [
                            {
                                "handler": "audit_jsonl",
                                "config": {"enabled": True,
                                    "output_file": str(
                                        temp_path / "test_audit_activity.log"
                                    ),  # Use absolute path
                                },
                            }
                        ]
                    }
                },
            }

            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            loader = ConfigLoader()
            config = loader.load_from_file(config_file)

            # Verify config directory is available for plugin resolution
            assert hasattr(loader, "config_directory")
            assert loader.config_directory.resolve() == temp_path.resolve()

            # Verify plugin config is loaded with absolute path
            assert config.plugins is not None
            plugin_config = config.plugins.auditing["_global"][0]
            expected_path = str(temp_path / "test_audit_activity.log")
            assert plugin_config.config["output_file"] == expected_path

    def test_config_loader_handles_home_directory_paths(self):
        """Test that ConfigLoader handles home directory paths in logging config."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "gatekit.yaml"

            # Create gatekit/logs directory in home to satisfy path validation
            home_gatekit_logs_dir = Path.home() / "gatekit" / "logs"
            home_gatekit_logs_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Create config with home directory path
                config_data = {
                    "proxy": {
                        "transport": "stdio",
                        "upstreams": [
                            {"name": "test_server", "command": ["echo", "test"]}
                        ],
                    },
                    "logging": {
                        "level": "INFO",
                        "handlers": ["file"],
                        "file_path": "~/gatekit/logs/gatekit.log",  # Home directory path
                    },
                }

                with open(config_file, "w") as f:
                    yaml.dump(config_data, f)

                loader = ConfigLoader()
                config = loader.load_from_file(config_file)

                # Verify logging config has resolved home directory path
                assert config.logging is not None
                assert config.logging.file_path is not None
                assert config.logging.file_path.is_absolute()

                # Should be under user home directory
                expected = Path.home() / "gatekit" / "logs" / "gatekit.log"
                assert config.logging.file_path == expected
            finally:
                # Clean up the logs directory we created
                try:
                    home_gatekit_logs_dir.rmdir()
                    (Path.home() / "gatekit").rmdir()
                except OSError:
                    pass  # Directory might not be empty or might not exist

    def test_config_loader_preserves_absolute_paths(self):
        """Test that ConfigLoader preserves absolute paths unchanged."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "gatekit.yaml"

            # Create a logs directory within temp dir for testing absolute paths
            abs_log_dir = temp_path / "absolute_logs"
            abs_log_dir.mkdir()
            absolute_log_path = str(abs_log_dir / "gatekit.log")

            # Create config with absolute logging path
            config_data = {
                "proxy": {
                    "transport": "stdio",
                    "upstreams": [{"name": "test_server", "command": ["echo", "test"]}],
                },
                "logging": {
                    "level": "INFO",
                    "handlers": ["file"],
                    "file_path": absolute_log_path,  # Absolute path
                },
            }

            with open(config_file, "w") as f:
                yaml.dump(config_data, f)

            loader = ConfigLoader()
            config = loader.load_from_file(config_file)

            # Verify absolute path is preserved
            assert config.logging is not None
            assert config.logging.file_path is not None
            assert str(config.logging.file_path) == absolute_log_path


class TestConfigLoaderPathResolutionEdgeCases:
    """Test edge cases in ConfigLoader path resolution."""

    def test_config_directory_with_symlinks(self):
        """Test config directory handling with symbolic links."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create actual config directory
            actual_config_dir = temp_path / "actual_config"
            actual_config_dir.mkdir()

            # Create symbolic link to config directory
            link_config_dir = temp_path / "config_link"
            try:
                link_config_dir.symlink_to(actual_config_dir)

                config_file = link_config_dir / "gatekit.yaml"

                # Create minimal config
                config_data = {
                    "proxy": {
                        "transport": "stdio",
                        "upstreams": [
                            {"name": "test_server", "command": ["echo", "test"]}
                        ],
                    }
                }

                with open(config_file, "w") as f:
                    yaml.dump(config_data, f)

                loader = ConfigLoader()
                loader.load_from_file(config_file)

                # Config directory should be the symlink path, not resolved
                # This preserves user's intended directory structure
                assert loader.config_directory.resolve() == link_config_dir.resolve()

            except OSError:
                # Skip test if symlinks aren't available (Windows requires Developer Mode or admin)
                pytest.skip("Symbolic links not available (on Windows, enable Developer Mode or run as admin)")

    def test_config_directory_with_unicode_paths(self):
        """Test config directory handling with Unicode characters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create config directory with Unicode name
            unicode_config_dir = temp_path / "配置目录"
            unicode_config_dir.mkdir()

            config_file = unicode_config_dir / "gatekit.yaml"

            # Create Unicode log directory to satisfy path validation
            unicode_log_dir = unicode_config_dir / "日志"
            unicode_log_dir.mkdir()

            # Create config with Unicode log path
            config_data = {
                "proxy": {
                    "transport": "stdio",
                    "upstreams": [{"name": "test_server", "command": ["echo", "test"]}],
                },
                "logging": {
                    "level": "INFO",
                    "handlers": ["file"],
                    "file_path": "日志/活动.log",  # Unicode relative path
                },
            }

            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, allow_unicode=True)

            loader = ConfigLoader()
            config = loader.load_from_file(config_file)

            # Verify Unicode paths are handled correctly
            assert loader.config_directory.resolve() == unicode_config_dir.resolve()
            assert config.logging is not None
            assert config.logging.file_path is not None

            expected = unicode_config_dir / "日志" / "活动.log"
            assert config.logging.file_path.resolve() == expected.resolve()
