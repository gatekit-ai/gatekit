"""Tests for updating existing security plugins with critical handling."""

import pytest
from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
from gatekit.plugins.security.secrets import BasicSecretsFilterPlugin
from gatekit.plugins.security.pii import BasicPIIFilterPlugin
from gatekit.plugins.security.prompt_injection import (
    BasicPromptInjectionDefensePlugin,
)
from gatekit.protocol.messages import MCPRequest


class TestExistingSecurityPluginsCriticalHandling:
    """Test that existing security plugins support critical handling."""

    def test_tool_manager_plugin_supports_critical_handling(self):
        """Test that ToolManagerPlugin (middleware) supports critical configuration."""

        # Test default critical behavior - all plugins default to critical=True (fail closed)
        plugin = ToolManagerPlugin({"tools": [{"tool": "test_tool"}]})
        assert plugin.is_critical() is True

        # Test explicit critical configuration
        plugin_critical = ToolManagerPlugin(
            {"tools": [{"tool": "test_tool"}], "critical": True}
        )
        assert plugin_critical.is_critical() is True

        # Test non-critical configuration
        plugin_non_critical = ToolManagerPlugin(
            {"tools": [{"tool": "test_tool"}], "critical": False}
        )
        assert plugin_non_critical.is_critical() is False

    def test_secrets_filter_plugin_supports_critical_handling(self):
        """Test that BasicSecretsFilterPlugin supports critical configuration."""

        # Test default critical behavior
        plugin = BasicSecretsFilterPlugin({"action": "block"})
        assert plugin.is_critical() is True

        # Test explicit critical configuration
        plugin_critical = BasicSecretsFilterPlugin(
            {"action": "block", "critical": True}
        )
        assert plugin_critical.is_critical() is True

        # Test non-critical configuration
        plugin_non_critical = BasicSecretsFilterPlugin(
            {"action": "audit_only", "critical": False}
        )
        assert plugin_non_critical.is_critical() is False

    def test_pii_filter_plugin_supports_critical_handling(self):
        """Test that BasicPIIFilterPlugin supports critical configuration."""

        # Test default critical behavior
        plugin = BasicPIIFilterPlugin({"action": "block"})
        assert plugin.is_critical() is True

        # Test explicit critical configuration
        plugin_critical = BasicPIIFilterPlugin({"action": "block", "critical": True})
        assert plugin_critical.is_critical() is True

        # Test non-critical configuration
        plugin_non_critical = BasicPIIFilterPlugin(
            {"action": "audit_only", "critical": False}
        )
        assert plugin_non_critical.is_critical() is False

    @pytest.mark.asyncio
    async def test_critical_configuration_affects_plugin_behavior(self):
        """Test that critical configuration doesn't change plugin behavior - only failure handling."""

        # Create two identical plugins with different critical settings
        plugin_critical = ToolManagerPlugin(
            {"tools": [{"tool": "read_file"}], "critical": True}
        )

        plugin_non_critical = ToolManagerPlugin(
            {"tools": [{"tool": "read_file"}], "critical": False}
        )

        # Both should behave identically for normal operations
        request_allowed = MCPRequest(
            jsonrpc="2.0", method="tools/call", id="1", params={"name": "read_file"}
        )
        request_blocked = MCPRequest(
            jsonrpc="2.0", method="tools/call", id="2", params={"name": "write_file"}
        )

        # Test allowed request
        decision_critical = await plugin_critical.process_request(
            request_allowed, server_name="test_server"
        )
        decision_non_critical = await plugin_non_critical.process_request(
            request_allowed, server_name="test_server"
        )

        # Middleware doesn't set allowed - it returns completed_response for blocked tools
        assert (
            decision_critical.completed_response
            == decision_non_critical.completed_response
        )
        assert (
            decision_critical.completed_response is None
        )  # Allowed requests pass through

        # Test blocked request
        decision_critical = await plugin_critical.process_request(
            request_blocked, server_name="test_server"
        )
        decision_non_critical = await plugin_non_critical.process_request(
            request_blocked, server_name="test_server"
        )

        # Both should return completed_response with error for blocked tools
        assert decision_critical.completed_response is not None
        assert decision_non_critical.completed_response is not None
        assert decision_critical.completed_response.error is not None
        assert decision_non_critical.completed_response.error is not None

    def test_prompt_injection_defense_plugin_supports_critical_handling(self):
        """Test that BasicPromptInjectionDefensePlugin supports critical configuration."""

        # Test default critical behavior
        plugin = BasicPromptInjectionDefensePlugin({"action": "block"})
        assert plugin.is_critical() is True

        # Test explicit critical configuration
        plugin_critical = BasicPromptInjectionDefensePlugin(
            {"action": "block", "critical": True}
        )
        assert plugin_critical.is_critical() is True

        # Test non-critical configuration
        plugin_non_critical = BasicPromptInjectionDefensePlugin(
            {"action": "audit_only", "critical": False}
        )
        assert plugin_non_critical.is_critical() is False

    def test_all_security_plugins_support_critical_handling(self):
        """Integration test to verify ALL security plugins support critical handling."""

        # List of all security plugin classes and their minimum required config
        # Note: ToolManagerPlugin is now middleware, not security
        security_plugins = [
            (BasicSecretsFilterPlugin, {"action": "audit_only"}),
            (BasicPIIFilterPlugin, {"action": "audit_only"}),
            (BasicPromptInjectionDefensePlugin, {"action": "audit_only"}),
        ]

        for plugin_class, min_config in security_plugins:
            # Test default behavior (should be critical)
            plugin_default = plugin_class(min_config)
            assert hasattr(
                plugin_default, "is_critical"
            ), f"{plugin_class.__name__} missing is_critical method"
            assert (
                plugin_default.is_critical() is True
            ), f"{plugin_class.__name__} should default to critical"

            # Test explicit critical configuration
            critical_config = {**min_config, "critical": True}
            plugin_critical = plugin_class(critical_config)
            assert (
                plugin_critical.is_critical() is True
            ), f"{plugin_class.__name__} critical config failed"

            # Test non-critical configuration
            non_critical_config = {**min_config, "critical": False}
            plugin_non_critical = plugin_class(non_critical_config)
            assert (
                plugin_non_critical.is_critical() is False
            ), f"{plugin_class.__name__} non-critical config failed"

        # Test middleware plugin - also defaults to critical=True (fail closed)
        middleware_plugin = ToolManagerPlugin({"tools": [{"tool": "test_tool"}]})
        assert hasattr(
            middleware_plugin, "is_critical"
        ), "ToolManagerPlugin missing is_critical method"
        assert (
            middleware_plugin.is_critical() is True
        ), "ToolManagerPlugin should default to critical (fail closed)"

        # Test explicit critical configuration for middleware
        middleware_critical = ToolManagerPlugin(
            {"tools": [{"tool": "test_tool"}], "critical": True}
        )
        assert (
            middleware_critical.is_critical() is True
        ), "ToolManagerPlugin critical config failed"

        middleware_non_critical = ToolManagerPlugin(
            {"tools": [{"tool": "test_tool"}], "critical": False}
        )
        assert (
            middleware_non_critical.is_critical() is False
        ), "ToolManagerPlugin non-critical config failed"
