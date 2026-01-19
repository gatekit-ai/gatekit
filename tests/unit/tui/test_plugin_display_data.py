"""Unit tests for plugin display data building and rendering.

Tests the new _build_plugin_display_data() method that replaced the old
GlobalSecurityWidget.generate_plugin_display_data() pattern.
"""

from unittest.mock import Mock
from typing import Dict, Any, List

from gatekit.config.models import ProxyConfig, PluginsConfig, PluginConfig, UpstreamConfig, TimeoutConfig
from gatekit.tui.screens.config_editor.base import ConfigEditorScreen
from gatekit.tui.constants import GLOBAL_SCOPE


class MockPlugin:
    """Mock plugin class for testing."""
    DISPLAY_NAME = "Mock Plugin"
    DISPLAY_SCOPE = "global"

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        return "Mock status"


class ServerAwarePlugin:
    """Mock server-aware plugin."""
    DISPLAY_NAME = "Server Aware Plugin"
    DISPLAY_SCOPE = "server_aware"

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        return "Server aware status"


class FailingPlugin:
    """Plugin whose describe_status raises an exception."""
    DISPLAY_NAME = "Failing Plugin"
    DISPLAY_SCOPE = "global"

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        raise ValueError("Intentional test failure")


def create_mock_screen(
    available_handlers: Dict[str, Dict[str, type]] = None,
    plugin_configs: Dict[str, Dict[str, List[PluginConfig]]] = None
) -> ConfigEditorScreen:
    """Create a mock ConfigEditorScreen for testing.

    Args:
        available_handlers: Dict of plugin_type -> {handler_name: handler_class}
        plugin_configs: Dict of plugin_type -> {scope: [PluginConfig]}

    Returns:
        Mock ConfigEditorScreen instance
    """
    screen = Mock(spec=ConfigEditorScreen)

    # Set up available_handlers
    screen.available_handlers = available_handlers or {}

    # Set up config with plugins
    config = ProxyConfig(
        transport="stdio",
        upstreams=[
            UpstreamConfig(
                name="test_server",
                transport="stdio",
                command=["test"],
                is_draft=True  # Skip validation
            )
        ],
        timeouts=TimeoutConfig()
    )

    if plugin_configs:
        config.plugins = PluginsConfig()
        for plugin_type, scope_dict in plugin_configs.items():
            setattr(config.plugins, plugin_type, scope_dict)

    screen.config = config

    # Bind the real method to the mock
    screen._build_plugin_display_data = ConfigEditorScreen._build_plugin_display_data.__get__(
        screen, ConfigEditorScreen
    )

    return screen


class TestPluginDisplayDataSorting:
    """Test sorting behavior: enabled first, priority ascending, then name."""

    def test_sorting_enabled_before_disabled(self):
        """Enabled plugins should appear before disabled ones."""
        # Create plugins with same priority but different enabled states
        handlers = {
            "security": {
                "plugin_a": type("PluginA", (), {
                    "DISPLAY_NAME": "Plugin A",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Status A")
                }),
                "plugin_b": type("PluginB", (), {
                    "DISPLAY_NAME": "Plugin B",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Status B")
                }),
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="plugin_a", config={"enabled": False, "priority": 50}),
                    PluginConfig(handler="plugin_b", config={"enabled": True, "priority": 50}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 2
        assert result[0]["handler"] == "plugin_b"  # Enabled first
        assert result[0]["enabled"] is True
        assert result[1]["handler"] == "plugin_a"  # Disabled second
        assert result[1]["enabled"] is False

    def test_sorting_by_priority_within_enabled(self):
        """Within enabled plugins, lower priority number comes first."""
        handlers = {
            "security": {
                "high_priority": type("HighPrio", (), {
                    "DISPLAY_NAME": "High Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "High")
                }),
                "low_priority": type("LowPrio", (), {
                    "DISPLAY_NAME": "Low Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Low")
                }),
                "medium_priority": type("MediumPrio", (), {
                    "DISPLAY_NAME": "Medium Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Medium")
                }),
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="high_priority", config={"enabled": True, "priority": 10}),
                    PluginConfig(handler="low_priority", config={"enabled": True, "priority": 90}),
                    PluginConfig(handler="medium_priority", config={"enabled": True, "priority": 50}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 3
        assert result[0]["handler"] == "high_priority"  # Priority 10
        assert result[0]["priority"] == 10
        assert result[1]["handler"] == "medium_priority"  # Priority 50
        assert result[1]["priority"] == 50
        assert result[2]["handler"] == "low_priority"  # Priority 90
        assert result[2]["priority"] == 90

    def test_sorting_alphabetically_within_same_priority(self):
        """Plugins with same priority sort alphabetically by display name."""
        handlers = {
            "security": {
                "zebra": type("Zebra", (), {
                    "DISPLAY_NAME": "Zebra Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Z")
                }),
                "alpha": type("Alpha", (), {
                    "DISPLAY_NAME": "Alpha Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "A")
                }),
                "beta": type("Beta", (), {
                    "DISPLAY_NAME": "Beta Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "B")
                }),
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="zebra", config={"enabled": True, "priority": 50}),
                    PluginConfig(handler="alpha", config={"enabled": True, "priority": 50}),
                    PluginConfig(handler="beta", config={"enabled": True, "priority": 50}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 3
        assert result[0]["display_name"] == "Alpha Plugin"
        assert result[1]["display_name"] == "Beta Plugin"
        assert result[2]["display_name"] == "Zebra Plugin"

    def test_complex_sorting_scenario(self):
        """Test full sorting hierarchy: enabled > priority > name."""
        handlers = {
            "security": {
                "enabled_low": type("EnabledLow", (), {
                    "DISPLAY_NAME": "Enabled Low Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "EL")
                }),
                "enabled_high": type("EnabledHigh", (), {
                    "DISPLAY_NAME": "Enabled High Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "EH")
                }),
                "disabled_high": type("DisabledHigh", (), {
                    "DISPLAY_NAME": "Disabled High Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "DH")
                }),
                "enabled_mid_b": type("EnabledMidB", (), {
                    "DISPLAY_NAME": "Enabled Mid B",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "EMB")
                }),
                "enabled_mid_a": type("EnabledMidA", (), {
                    "DISPLAY_NAME": "Enabled Mid A",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "EMA")
                }),
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="enabled_low", config={"enabled": True, "priority": 90}),
                    PluginConfig(handler="enabled_high", config={"enabled": True, "priority": 10}),
                    PluginConfig(handler="disabled_high", config={"enabled": False, "priority": 5}),
                    PluginConfig(handler="enabled_mid_b", config={"enabled": True, "priority": 50}),
                    PluginConfig(handler="enabled_mid_a", config={"enabled": True, "priority": 50}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        # Expected order:
        # 1. enabled_high (enabled, priority 10)
        # 2. enabled_mid_a (enabled, priority 50, alphabetically first)
        # 3. enabled_mid_b (enabled, priority 50, alphabetically second)
        # 4. enabled_low (enabled, priority 90)
        # 5. disabled_high (disabled, priority 5)

        assert len(result) == 5
        assert result[0]["handler"] == "enabled_high"
        assert result[1]["handler"] == "enabled_mid_a"
        assert result[2]["handler"] == "enabled_mid_b"
        assert result[3]["handler"] == "enabled_low"
        assert result[4]["handler"] == "disabled_high"


class TestDisplayScopeFiltering:
    """Test DISPLAY_SCOPE filtering for global security plugins."""

    def test_global_security_filters_by_display_scope(self):
        """Global security panel should only show plugins with DISPLAY_SCOPE='global'."""
        handlers = {
            "security": {
                "global_plugin": type("GlobalPlugin", (), {
                    "DISPLAY_NAME": "Global Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Global")
                }),
                "server_aware_plugin": type("ServerAwarePlugin", (), {
                    "DISPLAY_NAME": "Server Aware Plugin",
                    "DISPLAY_SCOPE": "server_aware",
                    "describe_status": classmethod(lambda cls, cfg: "Server")
                }),
                "server_specific_plugin": type("ServerSpecificPlugin", (), {
                    "DISPLAY_NAME": "Server Specific Plugin",
                    "DISPLAY_SCOPE": "server_specific",
                    "describe_status": classmethod(lambda cls, cfg: "Specific")
                }),
            }
        }

        screen = create_mock_screen(handlers)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        # Only global_plugin should appear
        assert len(result) == 1
        assert result[0]["handler"] == "global_plugin"

    def test_global_security_includes_plugins_without_display_scope(self):
        """Plugins without DISPLAY_SCOPE attribute default to 'global'."""
        handlers = {
            "security": {
                "no_scope_attr": type("NoScopeAttr", (), {
                    "DISPLAY_NAME": "No Scope Attribute",
                    # No DISPLAY_SCOPE attribute
                    "describe_status": classmethod(lambda cls, cfg: "No scope")
                }),
            }
        }

        screen = create_mock_screen(handlers)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        # Plugin without DISPLAY_SCOPE should be included (defaults to 'global')
        assert len(result) == 1
        assert result[0]["handler"] == "no_scope_attr"

    def test_auditing_plugins_not_filtered_by_display_scope(self):
        """Auditing plugins should NOT be filtered by DISPLAY_SCOPE."""
        handlers = {
            "auditing": {
                "audit_global": type("AuditGlobal", (), {
                    "DISPLAY_NAME": "Audit Global",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Audit G")
                }),
                "audit_server": type("AuditServer", (), {
                    "DISPLAY_NAME": "Audit Server",
                    "DISPLAY_SCOPE": "server_aware",
                    "describe_status": classmethod(lambda cls, cfg: "Audit S")
                }),
            }
        }

        screen = create_mock_screen(handlers)
        result = screen._build_plugin_display_data("auditing", GLOBAL_SCOPE)

        # Both should appear (auditing doesn't filter)
        assert len(result) == 2
        handler_names = {p["handler"] for p in result}
        assert handler_names == {"audit_global", "audit_server"}

    def test_server_scope_security_not_filtered_by_display_scope(self):
        """Server-scoped security plugins should show all plugins."""
        handlers = {
            "security": {
                "global_plugin": type("GlobalPlugin", (), {
                    "DISPLAY_NAME": "Global Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Global")
                }),
                "server_aware_plugin": type("ServerAwarePlugin", (), {
                    "DISPLAY_NAME": "Server Aware Plugin",
                    "DISPLAY_SCOPE": "server_aware",
                    "describe_status": classmethod(lambda cls, cfg: "Server")
                }),
            }
        }

        screen = create_mock_screen(handlers)
        result = screen._build_plugin_display_data("security", "my_server")

        # Both should appear (server scope doesn't filter)
        assert len(result) == 2
        handler_names = {p["handler"] for p in result}
        assert handler_names == {"global_plugin", "server_aware_plugin"}


class TestMissingHandlerWarnings:
    """Test that configured plugins without available handlers show warnings."""

    def test_missing_handler_creates_warning_entry(self):
        """Config entry without available handler should show '⚠ not found' warning."""
        handlers = {
            "security": {
                "existing_plugin": type("ExistingPlugin", (), {
                    "DISPLAY_NAME": "Existing Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Exists")
                }),
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="existing_plugin", config={"enabled": True, "priority": 50}),
                    PluginConfig(handler="missing_plugin", config={"enabled": True, "priority": 50}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 2

        # Find the missing plugin entry
        missing = next((p for p in result if p["handler"] == "missing_plugin"), None)
        assert missing is not None
        assert missing["is_missing"] is True
        assert missing["status"] == "Plugin not found"
        assert missing["display_name"] == "missing_plugin"

    def test_missing_handler_preserves_config_values(self):
        """Missing handler entry should preserve enabled/priority from config."""
        handlers = {"security": {}}

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="missing", config={"enabled": False, "priority": 25}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 1
        assert result[0]["handler"] == "missing"
        assert result[0]["enabled"] is False
        assert result[0]["priority"] == 25
        assert result[0]["is_missing"] is True

    def test_multiple_missing_handlers(self):
        """Multiple missing handlers should all show warnings."""
        handlers = {"security": {}}

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="missing_1", config={"enabled": True, "priority": 10}),
                    PluginConfig(handler="missing_2", config={"enabled": True, "priority": 20}),
                    PluginConfig(handler="missing_3", config={"enabled": False, "priority": 30}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 3
        for plugin in result:
            assert plugin["is_missing"] is True
            assert plugin["status"] == "Plugin not found"


class TestDescribeStatusErrorHandling:
    """Test error handling when plugin describe_status() raises exceptions."""

    def test_describe_status_exception_creates_fallback_entry(self):
        """Exception in describe_status() should create fallback entry."""
        handlers = {
            "security": {
                "failing": FailingPlugin,
            }
        }

        screen = create_mock_screen(handlers)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 1
        assert result[0]["handler"] == "failing"
        assert result[0]["status"] == "Error loading plugin status"
        assert result[0]["enabled"] is False  # Fallback to disabled
        assert result[0]["is_missing"] is False
        assert "error" in result[0]

    def test_multiple_plugins_with_mixed_failures(self):
        """Mix of working and failing plugins should all appear."""
        handlers = {
            "security": {
                "working": type("WorkingPlugin", (), {
                    "DISPLAY_NAME": "Working Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Working")
                }),
                "failing": FailingPlugin,
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="working", config={"enabled": True, "priority": 10}),
                    PluginConfig(handler="failing", config={"enabled": True, "priority": 20}),
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 2

        working = next(p for p in result if p["handler"] == "working")
        assert working["status"] == "Working"
        assert working["enabled"] is True

        failing = next(p for p in result if p["handler"] == "failing")
        assert failing["status"] == "Error loading plugin status"
        assert "error" in failing


class TestPluginDisplayDataDefaults:
    """Test default values when config is missing or incomplete."""

    def test_plugin_without_config_gets_defaults(self):
        """Available plugin without config should get default enabled=False, priority=50."""
        handlers = {
            "security": {
                "unconfigured": type("Unconfigured", (), {
                    "DISPLAY_NAME": "Unconfigured Plugin",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "Unconfigured")
                }),
            }
        }

        # No configs provided
        screen = create_mock_screen(handlers)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 1
        assert result[0]["handler"] == "unconfigured"
        assert result[0]["enabled"] is False
        assert result[0]["priority"] == 50

    def test_plugin_config_without_priority_gets_default(self):
        """Config without priority should default to 50."""
        handlers = {
            "security": {
                "no_priority": type("NoPriority", (), {
                    "DISPLAY_NAME": "No Priority",
                    "DISPLAY_SCOPE": "global",
                    "describe_status": classmethod(lambda cls, cfg: "No pri")
                }),
            }
        }

        configs = {
            "security": {
                GLOBAL_SCOPE: [
                    PluginConfig(handler="no_priority", config={"enabled": True}),
                    # priority will default to 50 in PluginConfig
                ]
            }
        }

        screen = create_mock_screen(handlers, configs)
        result = screen._build_plugin_display_data("security", GLOBAL_SCOPE)

        assert len(result) == 1
        assert result[0]["priority"] == 50


class TestPluginTableWidgetRendering:
    """Test PluginTableWidget properly renders plugins in sorted order."""

    def test_widget_renders_plugins_in_sorted_order(self):
        """PluginTableWidget should render plugins in the order provided by display data."""
        from gatekit.tui.widgets.plugin_table import PluginTableWidget

        # Create unsorted plugin data
        unsorted_data = [
            {
                "handler": "plugin_c",
                "display_name": "Plugin C",
                "status": "Status C",
                "action": "Configure",
                "enabled": False,
                "priority": 50,
                "is_missing": False,
            },
            {
                "handler": "plugin_a",
                "display_name": "Plugin A",
                "status": "Status A",
                "action": "Configure",
                "enabled": True,
                "priority": 10,
                "is_missing": False,
            },
            {
                "handler": "plugin_b",
                "display_name": "Plugin B",
                "status": "Status B",
                "action": "Configure",
                "enabled": True,
                "priority": 50,
                "is_missing": False,
            },
        ]

        # Sort as _build_plugin_display_data does
        sorted_data = sorted(
            unsorted_data,
            key=lambda p: (not p["enabled"], p.get("priority", 50), p["display_name"])
        )

        # Create widget with sorted data
        widget = PluginTableWidget(
            plugin_type="security",
            server_name=GLOBAL_SCOPE,
            plugins_data=sorted_data,
            show_priority=False,
            show_header=False,
        )

        # Widget should use the data in the order provided
        assert widget.plugins_data == sorted_data
        assert len(widget.plugins_data) == 3
        assert widget.plugins_data[0]["handler"] == "plugin_a"
        assert widget.plugins_data[1]["handler"] == "plugin_b"
        assert widget.plugins_data[2]["handler"] == "plugin_c"

    def test_widget_stores_initial_data_in_order(self):
        """Widget construction should store plugins_data in the order provided."""
        from gatekit.tui.widgets.plugin_table import PluginTableWidget

        # Provide sorted data to constructor
        sorted_data = [
            {
                "handler": "first",
                "display_name": "First Plugin",
                "status": "First",
                "action": "Configure",
                "enabled": True,
                "priority": 10,
                "is_missing": False,
            },
            {
                "handler": "second",
                "display_name": "Second Plugin",
                "status": "Second",
                "action": "Configure",
                "enabled": True,
                "priority": 20,
                "is_missing": False,
            },
        ]

        widget = PluginTableWidget(
            plugin_type="security",
            server_name=GLOBAL_SCOPE,
            plugins_data=sorted_data,
            show_priority=False,
            show_header=False,
        )

        # Verify order is preserved in stored data
        assert len(widget.plugins_data) == 2
        assert widget.plugins_data[0]["handler"] == "first"
        assert widget.plugins_data[1]["handler"] == "second"

    def test_global_mode_widget_configuration(self):
        """Global mode widgets should have correct configuration."""
        from gatekit.tui.widgets.plugin_table import PluginTableWidget

        widget = PluginTableWidget(
            plugin_type="security",
            server_name=GLOBAL_SCOPE,
            plugins_data=[],
            show_priority=False,
            show_header=False,
        )

        assert widget.plugin_type == "security"
        assert widget.server_name == GLOBAL_SCOPE
        assert widget.show_priority is False
        assert widget.show_header is False

    def test_server_mode_widget_configuration(self):
        """Server mode widgets should have different configuration."""
        from gatekit.tui.widgets.plugin_table import PluginTableWidget

        widget = PluginTableWidget(
            plugin_type="security",
            server_name="my_server",
            plugins_data=[],
            show_priority=True,
            show_header=True,
        )

        assert widget.plugin_type == "security"
        assert widget.server_name == "my_server"
        assert widget.show_priority is True
        assert widget.show_header is True
