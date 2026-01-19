"""Tests for PluginManager path resolution improvements.

This test suite follows Test-Driven Development (TDD) methodology to verify
that PluginManager properly handles PathResolvablePlugin interface for plugins
that require path resolution.
"""

from typing import Optional
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PathResolvablePlugin,
)


class MockPathResolvableSecurityPlugin(SecurityPlugin, PathResolvablePlugin):
    """Mock security plugin that implements PathResolvablePlugin interface."""

    def __init__(self, config):
        super().__init__(config)
        self.config_directory = None
        self.validation_errors = []

    def set_config_directory(self, config_directory):
        """Set config directory for path resolution."""
        self.config_directory = Path(config_directory)

    def validate_paths(self):
        """Validate paths - return validation errors."""
        return self.validation_errors

    async def process_request(self, request, server_name: Optional[str] = None):
        from gatekit.plugins.interfaces import PluginResult

        return PluginResult(allowed=True, reason="Mock plugin allows all")

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        from gatekit.plugins.interfaces import PluginResult

        return PluginResult(allowed=True, reason="Mock plugin allows all")

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        from gatekit.plugins.interfaces import PluginResult

        return PluginResult(allowed=True, reason="Mock plugin allows all")


class MockPathResolvableAuditingPlugin(AuditingPlugin, PathResolvablePlugin):
    """Mock auditing plugin that implements PathResolvablePlugin interface."""

    def __init__(self, config):
        super().__init__(config)
        self.config_directory = None
        self.validation_errors = []

    def set_config_directory(self, config_directory):
        """Set config directory for path resolution."""
        self.config_directory = Path(config_directory)

    def validate_paths(self):
        """Validate paths - return validation errors."""
        return self.validation_errors

    async def log_request(self, request, decision, server_name: Optional[str] = None):
        """Mock log request."""
        pass

    async def log_response(
        self, request, response, decision, server_name: Optional[str] = None
    ):
        """Mock log response."""
        pass

    async def log_notification(
        self, notification, decision, server_name: Optional[str] = None
    ):
        """Mock log notification."""
        pass


class MockNonPathResolvablePlugin(SecurityPlugin):
    """Mock plugin that does NOT implement PathResolvablePlugin interface."""

    def __init__(self, config):
        super().__init__(config)

    async def process_request(self, request, server_name: Optional[str] = None):
        from gatekit.plugins.interfaces import PluginResult

        return PluginResult(allowed=True, reason="Non-path plugin allows all")

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        from gatekit.plugins.interfaces import PluginResult

        return PluginResult(allowed=True, reason="Non-path plugin allows all")

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        from gatekit.plugins.interfaces import PluginResult

        return PluginResult(allowed=True, reason="Non-path plugin allows all")


class TestPluginManagerPathResolution:
    """Test PluginManager handling of PathResolvablePlugin interface."""

    def test_calls_set_config_directory_on_path_resolvable_security_plugins(self):
        """Test that PluginManager calls set_config_directory on PathResolvablePlugin security plugins."""
        config_directory = Path("/test/config")
        plugins_config = {
            "security": {
                "_global": [
                    {"handler": "mock_path_resolvable", "config": {"enabled": True}}
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            # Mock discovery to return our test plugin
            mock_discover.return_value = {
                "mock_path_resolvable": MockPathResolvableSecurityPlugin
            }

            manager = PluginManager(plugins_config, config_directory)
            # Use the full load_plugins() method to test path resolution in context
            asyncio.run(manager.load_plugins())

            # Should have loaded one plugin into upstream scope
            assert len(manager.upstream_security_plugins["_global"]) == 1
            plugin = manager.upstream_security_plugins["_global"][0]

            # Should have called set_config_directory with correct path
            assert plugin.config_directory == config_directory

    def test_calls_set_config_directory_on_path_resolvable_auditing_plugins(self):
        """Test that PluginManager calls set_config_directory on PathResolvablePlugin auditing plugins."""
        config_directory = Path("/test/config")
        plugins_config = {
            "auditing": {
                "_global": [
                    {"handler": "mock_path_resolvable", "config": {"enabled": True}}
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            # Mock discovery to return our test plugin
            mock_discover.return_value = {
                "mock_path_resolvable": MockPathResolvableAuditingPlugin
            }

            manager = PluginManager(plugins_config, config_directory)
            manager._load_upstream_scoped_auditing_plugins(plugins_config["auditing"])

            # Should have loaded one plugin into upstream scope
            assert len(manager.upstream_auditing_plugins["_global"]) == 1
            plugin = manager.upstream_auditing_plugins["_global"][0]

            # Should have called set_config_directory with correct path
            assert plugin.config_directory == config_directory

    def test_skips_set_config_directory_on_non_path_resolvable_plugins(self):
        """Test that PluginManager skips set_config_directory on plugins that don't implement PathResolvablePlugin."""
        config_directory = Path("/test/config")
        plugins_config = {
            "security": {
                "_global": [{"handler": "mock_non_path", "config": {"enabled": True}}]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            # Mock discovery to return our test plugin
            mock_discover.return_value = {"mock_non_path": MockNonPathResolvablePlugin}

            manager = PluginManager(plugins_config, config_directory)
            # Use the full load_plugins() method to test path resolution in context
            asyncio.run(manager.load_plugins())

            # Should have loaded one plugin into upstream scope
            assert len(manager.upstream_security_plugins["_global"]) == 1
            plugin = manager.upstream_security_plugins["_global"][0]

            # Should not have config_directory attribute (wasn't set)
            assert not hasattr(plugin, "config_directory")

    def test_handles_none_config_directory_gracefully(self):
        """Test that PluginManager handles None config_directory without errors."""
        plugins_config = {
            "security": {
                "_global": [
                    {"handler": "mock_path_resolvable", "config": {"enabled": True}}
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            # Mock discovery to return our test plugin
            mock_discover.return_value = {
                "mock_path_resolvable": MockPathResolvableSecurityPlugin
            }

            manager = PluginManager(plugins_config, config_directory=None)
            manager._load_upstream_scoped_security_plugins(plugins_config["security"])

            # Should have loaded one plugin into upstream scope
            assert len(manager.upstream_security_plugins["_global"]) == 1
            plugin = manager.upstream_security_plugins["_global"][0]

            # Should not have called set_config_directory (config_directory should remain None)
            assert plugin.config_directory is None

    def test_removes_config_directory_from_plugin_config_dict(self):
        """Test that PluginManager no longer passes config_directory through plugin config dict."""
        config_directory = Path("/test/config")
        plugins_config = {
            "security": {
                "_global": [
                    {
                        "handler": "mock_path_resolvable",
                        "enabled": True,
                        "config": {"some_setting": "value"},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            # Create a mock plugin class that captures the config dict passed to __init__
            class ConfigCapturingPlugin(MockPathResolvableSecurityPlugin):
                def __init__(self, config):
                    self.captured_config = config.copy()
                    super().__init__(config)

            mock_discover.return_value = {"mock_path_resolvable": ConfigCapturingPlugin}

            manager = PluginManager(plugins_config, config_directory)
            manager._load_upstream_scoped_security_plugins(plugins_config["security"])

            # Should have loaded one plugin into upstream scope
            assert len(manager.upstream_security_plugins["_global"]) == 1
            plugin = manager.upstream_security_plugins["_global"][0]

            # Config dict should not contain config_directory
            assert "config_directory" not in plugin.captured_config
            # But should contain the original setting
            assert plugin.captured_config["some_setting"] == "value"
            # And should have called set_config_directory separately
            assert plugin.config_directory == config_directory


class TestPluginManagerPathValidation:
    """Test PluginManager validation of path-resolvable plugins."""

    def test_validates_path_resolvable_plugins_during_loading(self):
        """Test that PluginManager validates paths for PathResolvablePlugins during loading.

        With critical=True (default), path validation errors raise an exception
        and prevent the plugin from loading.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            config_directory = Path(temp_dir)
            # Default critical=True means validation errors raise exceptions
            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "mock_path_resolvable",
                            "enabled": True,
                            "config": {},
                        }
                    ]
                }
            }

            with patch.object(PluginManager, "_discover_handlers") as mock_discover:
                # Create plugin that returns validation errors
                class FailingValidationPlugin(MockPathResolvableSecurityPlugin):
                    def validate_paths(self):
                        return ["Path /invalid/path does not exist"]

                mock_discover.return_value = {
                    "mock_path_resolvable": FailingValidationPlugin
                }

                manager = PluginManager(plugins_config, config_directory)

                # With critical=True (default), path validation failures raise exceptions
                with pytest.raises(ValueError) as exc_info:
                    manager._load_upstream_scoped_security_plugins(
                        plugins_config["security"]
                    )

                # Verify the error message includes path validation info
                assert "path validation failed" in str(exc_info.value).lower()
                assert "mock_path_resolvable" in str(exc_info.value)

    def test_allows_plugins_with_valid_paths(self):
        """Test that PluginManager allows plugins with valid path validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_directory = Path(temp_dir)
            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "mock_path_resolvable",
                            "enabled": True,
                            "config": {},
                        }
                    ]
                }
            }

            with patch.object(PluginManager, "_discover_handlers") as mock_discover:
                # Plugin with no validation errors
                mock_discover.return_value = {
                    "mock_path_resolvable": MockPathResolvableSecurityPlugin
                }

                manager = PluginManager(plugins_config, config_directory)
                manager._load_upstream_scoped_security_plugins(
                    plugins_config["security"]
                )

                # Should have loaded plugin successfully into upstream scope
                assert len(manager.upstream_security_plugins["_global"]) == 1
                plugin = manager.upstream_security_plugins["_global"][0]
                assert plugin.config_directory == config_directory
