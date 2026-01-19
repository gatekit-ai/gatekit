"""Tests for audit plugin priority removal.

This test module verifies that audit plugins:
1. Don't have priority attribute
2. Execute in definition order (not priority order)
3. Handle priority in config with warning
4. Work correctly without priority
"""

import pytest
from unittest.mock import MagicMock, patch
import logging
from gatekit.plugins.interfaces import AuditingPlugin, PluginResult
from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin
from gatekit.plugins.auditing.human_readable import LineAuditingPlugin
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest


class TestAuditPluginPriority:
    """Test that audit plugins don't use priority."""

    def test_audit_plugin_no_priority_attribute(self):
        """Verify audit plugins don't have priority attribute."""
        plugin = JsonAuditingPlugin({"enabled": True, "output_file": "test.json"})
        assert not hasattr(
            plugin, "priority"
        ), "Audit plugin should not have priority attribute"

    def test_audit_plugin_critical_configurable(self):
        """Verify audit plugins can be configured as critical or non-critical."""
        # Default should be True (fail-closed for all plugins)
        plugin = JsonAuditingPlugin({"enabled": True, "output_file": "test.json"})
        assert hasattr(plugin, "critical")
        assert (
            plugin.critical is True
        ), "All plugins should default to critical=True (fail-closed)"

        # Setting critical=True explicitly should also work
        plugin2 = JsonAuditingPlugin(
            {"enabled": True, "critical": True, "output_file": "test.json"}
        )
        assert (
            plugin2.critical is True
        ), "Audit plugins should respect critical=True in config"

        # Setting critical=False explicitly should work for development scenarios
        plugin3 = JsonAuditingPlugin(
            {"enabled": True, "critical": False, "output_file": "test.json"}
        )
        assert (
            plugin3.critical is False
        ), "Audit plugins should respect critical=False in config"

    def test_audit_plugin_priority_ignored_with_warning(self, caplog):
        """Verify priority in config is ignored with warning."""
        config = {
            "enabled": True,
            "priority": 99,  # Should be ignored
            "output_file": "test.json",
        }

        with caplog.at_level(logging.WARNING):
            plugin = JsonAuditingPlugin(config)

        # Plugin should work without priority attribute
        assert not hasattr(
            plugin, "priority"
        ), "Audit plugin should not have priority attribute"

        # Plugin should still be functional
        assert plugin.output_file.endswith("test.json")

    def test_audit_plugin_schema_no_priority(self):
        """Verify audit plugin schemas don't include priority field."""
        schema = JsonAuditingPlugin.get_json_schema()
        assert "priority" not in schema.get(
            "properties", {}
        ), "Audit plugin schema should not include priority field"

        # Check another audit plugin
        schema2 = LineAuditingPlugin.get_json_schema()
        assert "priority" not in schema2.get(
            "properties", {}
        ), "Human readable audit plugin schema should not include priority"

    @pytest.mark.asyncio
    async def test_audit_plugins_run_in_definition_order(self):
        """Verify audit plugins execute in configuration order, not priority order."""
        call_order = []

        class OrderTrackingPlugin(AuditingPlugin):
            def __init__(self, name, config=None):
                # Initialize with minimal config to avoid priority
                super().__init__(config or {})
                self.name = name
                self.handler = f"tracker_{name}"  # Each needs unique handler name

            async def log_request(self, request, decision, server_name):
                call_order.append(self.name)

            async def log_response(self, request, response, decision, server_name):
                pass

            async def log_notification(self, notification, decision, server_name):
                pass

        # Create plugins with different names (order should be preserved)
        plugin_c = OrderTrackingPlugin("C")
        plugin_a = OrderTrackingPlugin("A")
        plugin_b = OrderTrackingPlugin("B")

        # Create manager and set plugins in specific order
        manager = PluginManager({})
        manager._initialized = True
        manager.upstream_auditing_plugins["test"] = [plugin_c, plugin_a, plugin_b]

        # Create test request and decision
        request = MagicMock(spec=MCPRequest)
        decision = PluginResult(allowed=True, reason="test")

        # They should execute in the order they were added (C, A, B), not alphabetical
        await manager.log_request(request, decision, "test")
        assert call_order == [
            "C",
            "A",
            "B",
        ], f"Expected order [C, A, B], got {call_order}"

    @pytest.mark.asyncio
    async def test_manager_handles_audit_plugins_without_priority(self):
        """Verify plugin manager handles audit plugins without priority gracefully."""

        class SimpleAuditPlugin(AuditingPlugin):
            def __init__(self, config):
                # Call parent init properly
                super().__init__(config)

            async def log_request(self, request, decision, server_name):
                pass

            async def log_response(self, request, response, decision, server_name):
                pass

            async def log_notification(self, notification, decision, server_name):
                pass

        # Create plugins
        plugin1 = SimpleAuditPlugin({})
        plugin2 = SimpleAuditPlugin({})

        # Manager should handle them without errors
        manager = PluginManager({})
        manager._initialized = True
        manager.upstream_auditing_plugins["_global"] = [plugin1, plugin2]

        # Should work without priority
        plugins = manager.get_plugins_for_upstream("test")
        assert len(plugins["auditing"]) == 2

        # Should execute without errors
        request = MagicMock(spec=MCPRequest)
        decision = PluginResult(allowed=True, reason="test")
        await manager.log_request(request, decision, "test")

    @pytest.mark.asyncio
    async def test_plugin_manager_warns_on_audit_priority(self, caplog):
        """Verify plugin manager warns when audit plugins have priority in config."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "priority": 10,  # Should trigger warning
                            "output_file": "test.json"
                        },
                    }
                ]
            }
        }

        with caplog.at_level(logging.WARNING):
            manager = PluginManager(config)
            # Must actually load plugins to trigger the warning
            await manager.load_plugins()

        # Verify exact warning was logged
        assert "Priority field ignored for audit plugin" in caplog.text
        assert "audit_jsonl" in caplog.text
        assert "audit plugins execute in definition order" in caplog.text.lower()

    def test_security_plugins_still_have_priority(self):
        """Verify security plugins still use priority (unchanged)."""
        from gatekit.plugins.security.pii import BasicPIIFilterPlugin

        plugin = BasicPIIFilterPlugin({"enabled": True, "priority": 25})
        assert hasattr(
            plugin, "priority"
        ), "Security plugins should still have priority"
        assert (
            plugin.priority == 25
        ), "Security plugin priority should be set from config"


class TestAuditPluginNoSorting:
    """Test that audit plugins are not sorted by priority."""

    @patch("gatekit.plugins.manager.PluginManager._discover_handlers")
    def test_load_auditing_plugins_no_sorting(self, mock_discover):
        """Verify audit plugins are loaded in definition order without sorting."""

        class MockAuditPlugin(AuditingPlugin):
            def __init__(self, config):
                self.enabled = True
                self.critical = False
                self.handler = config.get("handler", "mock")
                self.order_mark = config.get("order_mark", 0)

            async def log_request(self, request, decision, server_name):
                pass

            async def log_response(self, request, response, decision, server_name):
                pass

            async def log_notification(self, notification, decision, server_name):
                pass

        # Mock discovery to return our test plugin
        mock_discover.return_value = {
            "mock_audit_1": MockAuditPlugin,
            "mock_audit_2": MockAuditPlugin,
            "mock_audit_3": MockAuditPlugin,
        }

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "mock_audit_2",
                        "enabled": True,
                        "config": {"order_mark": 2},
                    },
                    {
                        "handler": "mock_audit_1",
                        "enabled": True,
                        "config": {"order_mark": 1},
                    },
                    {
                        "handler": "mock_audit_3",
                        "enabled": True,
                        "config": {"order_mark": 3},
                    },
                ]
            }
        }

        manager = PluginManager(config)
        manager._initialized = False

        # This should NOT sort plugins by priority
        import asyncio

        asyncio.run(manager.load_plugins())

        # Check that plugins are in definition order (2, 1, 3), not sorted
        plugins = manager.upstream_auditing_plugins.get("_global", [])
        assert len(plugins) == 3
        assert plugins[0].order_mark == 2
        assert plugins[1].order_mark == 1
        assert plugins[2].order_mark == 3


class TestDynamicAuditPluginRegistration:
    """Test dynamic registration of audit plugins without priority."""

    def test_dynamic_registration_without_priority(self):
        """Test that dynamically registered audit plugins work without priority attribute."""
        from gatekit.plugins.manager import PluginManager
        from gatekit.plugins.interfaces import AuditingPlugin

        class CustomAuditPlugin(AuditingPlugin):
            """Custom audit plugin without priority attribute."""

            def __init__(self):
                # Bypass parent init to simulate a plugin without priority
                self.critical = False
                self.handler = "custom_audit"

            async def log_request(self, request, decision, server_name):
                pass

            async def log_response(self, request, response, decision, server_name):
                pass

            async def log_notification(self, notification, decision, server_name):
                pass

        # Create plugin without priority attribute
        plugin = CustomAuditPlugin()
        assert not hasattr(plugin, "priority")

        # Register it dynamically
        manager = PluginManager({})
        manager.register_auditing_plugin(plugin)

        # Should work without errors
        assert len(manager.auditing_plugins) == 1
        assert plugin in manager.auditing_plugins

        # Plugin should not have priority
        assert not hasattr(plugin, "priority")

    def test_dynamic_registration_with_priority_ignored(self):
        """Test that dynamically registered audit plugins with priority attribute are accepted."""
        from gatekit.plugins.manager import PluginManager
        from gatekit.plugins.interfaces import AuditingPlugin

        class CustomAuditPluginWithPriority(AuditingPlugin):
            """Custom audit plugin that incorrectly has priority."""

            def __init__(self):
                # Bypass parent init to set priority directly
                self.critical = False
                self.handler = "custom_audit_priority"
                self.priority = 50  # Incorrectly set priority

            async def log_request(self, request, decision, server_name):
                pass

            async def log_response(self, request, response, decision, server_name):
                pass

            async def log_notification(self, notification, decision, server_name):
                pass

        # Create plugin with priority
        plugin = CustomAuditPluginWithPriority()
        assert hasattr(plugin, "priority")
        assert plugin.priority == 50

        # Register it dynamically
        manager = PluginManager({})
        manager.register_auditing_plugin(plugin)

        # Priority attribute remains but is ignored for audit plugins
        assert plugin.priority == 50

        # Should be registered successfully
        assert len(manager.auditing_plugins) == 1
        assert plugin in manager.auditing_plugins


class TestMixedPluginPriorityDetection:
    """Test detection and handling of mixed plugin priority scenarios."""

    @pytest.mark.asyncio
    async def test_warns_on_mixed_priority_in_global_audit_plugins(self, caplog):
        """Test warning when some audit plugins have priority and others don't."""
        from gatekit.plugins.manager import PluginManager
        import logging

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {
                            "enabled": True,
                            "priority": 10,  # Has priority
                            "output_file": "test1.json"
                        },
                    },
                    {
                        "handler": "audit_human_readable",
                        "config": {
                            "enabled": True,  # No priority
                            "output_file": "test2.log"
                        },
                    },
                    {
                        "handler": "audit_csv",
                        "config": {
                            "enabled": True,
                            "priority": 30,  # Has priority
                            "output_file": "test3.csv"
                        },
                    },
                ]
            }
        }

        with caplog.at_level(logging.WARNING):
            manager = PluginManager(config)
            await manager.load_plugins()

        # Should warn about priority being ignored for audit plugins
        warning_text = caplog.text

        # Check for specific warning messages
        assert "Priority field ignored for audit plugin" in warning_text
        # At least one of the plugins with priority should generate a warning
        assert "audit_jsonl" in warning_text or "audit_csv" in warning_text

        # Verify audit plugins don't have priority attribute
        global_plugins = manager.upstream_auditing_plugins.get("_global", [])
        for plugin in global_plugins:
            assert not hasattr(
                plugin, "priority"
            ), f"Audit plugin {plugin.handler_name} should not have priority attribute"

    @pytest.mark.asyncio
    async def test_no_warning_when_no_audit_plugins_have_priority(self, caplog):
        """Test no warnings when audit plugins correctly have no priority."""
        from gatekit.plugins.manager import PluginManager
        import logging

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "enabled": True,
                        "config": {"output_file": "test1.json"},
                    },
                    {
                        "handler": "audit_human_readable",
                        "enabled": True,
                        "config": {"output_file": "test2.log"},
                    },
                ]
            }
        }

        with caplog.at_level(logging.WARNING):
            manager = PluginManager(config)
            await manager.load_plugins()

        # Should not warn about priority (might have other warnings)
        warning_text = caplog.text.lower()
        assert "priority field ignored" not in warning_text
        assert "removing priority" not in warning_text


class TestAuditPluginSchemasNoPriority:
    """Test that all audit plugin schemas exclude priority field."""

    def test_all_audit_plugin_schemas_exclude_priority(self):
        """Verify ALL discovered audit plugin schemas don't include priority field."""
        from gatekit.plugins.manager import PluginManager

        # Discover ALL auditing plugins
        manager = PluginManager({})
        policies = manager._discover_handlers("auditing")

        assert len(policies) > 0, "No auditing policies discovered"

        # Check each discovered policy
        for policy_name, plugin_cls in policies.items():
            # Get schema and verify no priority field
            schema = plugin_cls.get_json_schema()
            assert "priority" not in schema.get("properties", {}), (
                f"Audit plugin '{policy_name}' ({plugin_cls.__name__}) "
                f"schema should not include priority field"
            )


class TestUpstreamOverrideSemantics:
    """Test upstream-specific audit plugin override behavior."""

    @pytest.mark.asyncio
    async def test_upstream_specific_overrides_global(self):
        """Verify upstream-specific audit plugin overrides global with same policy."""
        from gatekit.plugins.manager import PluginManager

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "enabled": True,
                        "config": {"output_file": "global.json"},
                    }
                ],
                "specific_upstream": [
                    {
                        "handler": "audit_jsonl",  # Same handler name
                        "enabled": True,
                        "config": {"output_file": "specific.json"},
                    }
                ],
            }
        }

        manager = PluginManager(config)
        await manager.load_plugins()

        # Get plugins for specific upstream
        plugins = manager.get_plugins_for_upstream("specific_upstream")
        audit_plugins = plugins["auditing"]

        # Should have only one json_auditing plugin (upstream-specific)
        assert len(audit_plugins) == 1
        assert audit_plugins[0].__class__.__name__ == "JsonAuditingPlugin"

        # Verify it's the upstream-specific one by checking config
        # (This assumes the plugin stores output_file from config)
        assert "specific.json" in str(audit_plugins[0].output_file)

        # Verify global is not included when upstream-specific exists
        assert "global.json" not in str(audit_plugins[0].output_file)


class TestAuditPluginExecutionOrder:
    """Test that audit plugins execute in definition order without priority sorting."""

    @pytest.mark.asyncio
    async def test_audit_plugins_maintain_definition_order(self):
        """Verify audit plugins execute in the exact order they're defined."""
        from gatekit.plugins.manager import PluginManager
        from gatekit.plugins.interfaces import AuditingPlugin, PluginResult
        from gatekit.protocol.messages import MCPRequest
        from unittest.mock import MagicMock

        execution_order = []

        class OrderTrackingAuditPlugin(AuditingPlugin):
            def __init__(self, name, config):
                super().__init__(config)
                self.name = name
                self.handler = f"order_plugin_{name}"

            async def log_request(self, request, decision, server_name):
                execution_order.append(f"request_{self.name}")

            async def log_response(self, request, response, decision, server_name):
                execution_order.append(f"response_{self.name}")

            async def log_notification(self, notification, decision, server_name):
                execution_order.append(f"notification_{self.name}")

        # Create plugins in specific order
        plugin_a = OrderTrackingAuditPlugin("A", {"enabled": True})
        plugin_b = OrderTrackingAuditPlugin("B", {"enabled": True})
        plugin_c = OrderTrackingAuditPlugin("C", {"enabled": True})

        # Create manager and register plugins in order A, B, C
        manager = PluginManager({})
        manager._initialized = True
        manager.upstream_auditing_plugins["test"] = [plugin_a, plugin_b, plugin_c]

        # Test request logging
        request = MagicMock(spec=MCPRequest)
        decision = PluginResult(allowed=True, reason="test")

        await manager.log_request(request, decision, "test")
        assert execution_order == ["request_A", "request_B", "request_C"]

        # Clear and test response logging
        execution_order.clear()
        response = MagicMock()
        await manager.log_response(request, response, decision, "test")
        assert execution_order == ["response_A", "response_B", "response_C"]

        # Clear and test notification logging
        execution_order.clear()
        notification = MagicMock()
        await manager.log_notification(notification, decision, "test")
        assert execution_order == ["notification_A", "notification_B", "notification_C"]
