"""Tests for security plugin critical handling functionality."""

from typing import Optional
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult


class TestSecurityPluginCriticalHandling:
    """Test SecurityPlugin critical handling functionality."""

    def test_security_plugin_defaults_to_critical(self):
        """Test that security plugins default to critical behavior."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        # Test default critical behavior
        plugin = TestSecurityPlugin({})
        assert plugin.is_critical() is True

    def test_security_plugin_can_be_configured_non_critical(self):
        """Test that security plugins can be configured as non-critical."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        # Test explicit non-critical configuration
        plugin = TestSecurityPlugin({"critical": False})
        assert plugin.is_critical() is False

    def test_security_plugin_can_be_configured_critical(self):
        """Test that security plugins can be explicitly configured as critical."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        # Test explicit critical configuration
        plugin = TestSecurityPlugin({"critical": True})
        assert plugin.is_critical() is True

    def test_is_critical_returns_config_value(self):
        """Test that is_critical() returns the configured value."""

        class TestSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        # Test various config values
        critical_plugin = TestSecurityPlugin({"critical": True})
        assert critical_plugin.is_critical() is True

        non_critical_plugin = TestSecurityPlugin({"critical": False})
        assert non_critical_plugin.is_critical() is False

        default_plugin = TestSecurityPlugin({})
        assert default_plugin.is_critical() is True
