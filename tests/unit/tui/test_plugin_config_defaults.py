"""Test plugin configuration default values.

This test ensures that _get_global_plugin_config and _get_server_plugin_config
return consistent defaults when a plugin doesn't exist in the config, preventing
the modal initialization bug where enabled state was incorrectly set to True.

Regression test for: Modal showing enabled=True for unconfigured global plugins.
"""

import pytest
from pathlib import Path
from gatekit.config import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.config.models import PluginsConfig, PluginConfig
from gatekit.tui.screens.config_editor import ConfigEditorScreen


class TestPluginConfigDefaults:
    """Test that config getter methods return correct defaults."""

    @pytest.fixture
    def config_editor_screen(self):
        """Create a ConfigEditorScreen instance for testing."""
        # Create minimal config
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test-server", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # Create screen
        screen = ConfigEditorScreen(Path("/tmp/test-config.yaml"), config)

        # Initialize available_handlers (empty for testing - we're only testing defaults)
        screen.available_handlers = {
            "security": {},
            "auditing": {},
            "middleware": {},
        }

        return screen

    def test_get_global_plugin_config_returns_disabled_default(self, config_editor_screen):
        """_get_global_plugin_config returns enabled=False for unconfigured plugins.

        When a plugin doesn't exist in global config, the method should return
        default framework values to match display data defaults.
        """
        # Test with a known plugin that's not in the config
        result = config_editor_screen._get_global_plugin_config(
            "basic_pii_filter", "security"
        )

        assert result == {"enabled": False, "priority": 50, "critical": True}, \
            "Unconfigured global plugin should default to disabled"

    def test_get_global_plugin_config_returns_actual_config(self, config_editor_screen):
        """_get_global_plugin_config returns actual config when plugin exists."""
        # Add a plugin to global config
        config_editor_screen.config.plugins = PluginsConfig()
        config_editor_screen.config.plugins.security = {
            "_global": [
                PluginConfig(
                    handler="basic_pii_filter",
                    config={"enabled": True, "priority": 25, "action": "redact"}
                )
            ]
        }

        result = config_editor_screen._get_global_plugin_config(
            "basic_pii_filter", "security"
        )

        assert result["enabled"]
        assert result["priority"] == 25
        assert result["action"] == "redact"

    def test_get_server_plugin_config_returns_disabled_default(self, config_editor_screen):
        """_get_server_plugin_config returns enabled=False for unconfigured plugins.

        When a plugin doesn't exist in server config, the method should return
        default framework values to match inheritance defaults.
        """
        config_editor_screen.selected_server = "test-server"

        result = config_editor_screen._get_server_plugin_config(
            "basic_pii_filter", "security"
        )

        assert result == {"enabled": False, "priority": 50, "critical": True}, \
            "Unconfigured server plugin should default to disabled"

    def test_get_server_plugin_config_returns_actual_config(self, config_editor_screen):
        """_get_server_plugin_config returns actual config when override exists."""
        config_editor_screen.selected_server = "test-server"

        # Add a server override
        config_editor_screen.config.plugins = PluginsConfig()
        config_editor_screen.config.plugins.security = {
            "test-server": [
                PluginConfig(
                    handler="basic_pii_filter",
                    config={"enabled": True, "priority": 10, "action": "block"}
                )
            ]
        }

        result = config_editor_screen._get_server_plugin_config(
            "basic_pii_filter", "security"
        )

        assert result["enabled"]
        assert result["priority"] == 10
        assert result["action"] == "block"

    def test_get_server_plugin_config_no_server_selected(self, config_editor_screen):
        """_get_server_plugin_config returns disabled default when no server selected."""
        config_editor_screen.selected_server = None

        result = config_editor_screen._get_server_plugin_config(
            "basic_pii_filter", "security"
        )

        assert result == {"enabled": False, "priority": 50, "critical": True}, \
            "No server selected should default to disabled"

    def test_default_values_are_consistent(self, config_editor_screen):
        """Defaults are consistent across global and server getters.

        Both _get_global_plugin_config and _get_server_plugin_config should
        return the same default values for consistency.
        """
        config_editor_screen.selected_server = "test-server"

        # Get defaults from both getters
        global_defaults = config_editor_screen._get_global_plugin_config(
            "any_plugin", "security"
        )
        server_defaults = config_editor_screen._get_server_plugin_config(
            "any_plugin", "security"
        )

        # They should be identical
        assert global_defaults == server_defaults
        assert global_defaults == {"enabled": False, "priority": 50, "critical": True}

    def test_default_values_match_inheritance_computation(self, config_editor_screen):
        """Defaults match _compute_plugin_inheritance behavior.

        Both _get_server_plugin_config and _compute_plugin_inheritance should
        use the same default values for consistency when plugins config exists
        but handler isn't configured.
        """
        config_editor_screen.selected_server = "test-server"

        # Initialize plugins config (empty but exists)
        config_editor_screen.config.plugins = PluginsConfig()
        config_editor_screen.config.plugins.security = {}

        # Get defaults from config getter
        config_defaults = config_editor_screen._get_server_plugin_config(
            "basic_pii_filter", "security"
        )

        # Compute inheritance (returns False, 50 for unconfigured when plugins config exists)
        status, enabled, priority = config_editor_screen._compute_plugin_inheritance(
            "basic_pii_filter", "security", "test-server"
        )

        # They should match (disabled when not configured)
        assert config_defaults["enabled"] == enabled is False
        assert config_defaults["priority"] == priority == 50

    def test_multiple_plugin_types_use_same_defaults(self, config_editor_screen):
        """All plugin types use the same default values."""
        # Test security plugins
        security_result = config_editor_screen._get_global_plugin_config(
            "basic_pii_filter", "security"
        )

        # Test auditing plugins
        auditing_result = config_editor_screen._get_global_plugin_config(
            "audit_jsonl", "auditing"
        )

        # Test middleware plugins (if any)
        middleware_result = config_editor_screen._get_global_plugin_config(
            "tool_manager", "middleware"
        )

        # Security and middleware plugins have enabled + priority + critical
        expected_with_priority = {"enabled": False, "priority": 50, "critical": True}
        assert security_result == expected_with_priority
        assert middleware_result == expected_with_priority

        # Auditing plugins have enabled + critical (no priority by design)
        expected_auditing = {"enabled": False, "critical": True}
        assert auditing_result == expected_auditing


class TestGetDefaultPluginConfigWithSchemaDefaults:
    """Tests for _get_default_plugin_config including schema defaults.

    Regression tests for: TUI crash when enabling auditing plugins.
    When a plugin class is provided, schema defaults must be included
    in the returned config dict.
    """

    def test_get_default_plugin_config_includes_schema_defaults_with_plugin_class(self):
        """_get_default_plugin_config should include schema defaults when plugin class provided."""
        from gatekit.tui.screens.config_editor.plugin_actions import _get_default_plugin_config
        from gatekit.plugins.auditing.csv import CsvAuditingPlugin

        config = _get_default_plugin_config("auditing", CsvAuditingPlugin)

        # Should include framework defaults
        assert "enabled" in config
        assert "critical" in config

        # Should include schema defaults
        assert "output_file" in config, \
            "output_file should be included from schema default"
        assert config["output_file"] == "logs/gatekit_audit.csv", \
            "output_file should match schema default value"

    def test_get_default_plugin_config_without_plugin_class_returns_framework_only(self):
        """_get_default_plugin_config without plugin class returns only framework defaults."""
        from gatekit.tui.screens.config_editor.plugin_actions import _get_default_plugin_config

        config = _get_default_plugin_config("auditing", None)

        # Should include framework defaults
        assert config == {"enabled": False, "critical": True}

        # Should NOT include schema defaults (no plugin class to get them from)
        assert "output_file" not in config

    def test_get_default_plugin_config_all_auditing_plugins_include_output_file(self):
        """All auditing plugins should have output_file in their defaults."""
        from gatekit.tui.screens.config_editor.plugin_actions import _get_default_plugin_config
        from gatekit.plugins.auditing.csv import CsvAuditingPlugin
        from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin
        from gatekit.plugins.auditing.human_readable import LineAuditingPlugin

        for plugin_class in [CsvAuditingPlugin, JsonAuditingPlugin, LineAuditingPlugin]:
            config = _get_default_plugin_config("auditing", plugin_class)

            assert "output_file" in config, \
                f"{plugin_class.__name__}: should include output_file"
            assert config["output_file"], \
                f"{plugin_class.__name__}: output_file should have a value"

    def test_get_default_plugin_config_can_instantiate_auditing_plugin(self):
        """Config from _get_default_plugin_config should allow plugin instantiation.

        This is the key regression test - the original bug was that enabling
        an auditing plugin in the TUI crashed because config lacked output_file.
        """
        from gatekit.tui.screens.config_editor.plugin_actions import _get_default_plugin_config
        from gatekit.plugins.auditing.csv import CsvAuditingPlugin

        config = _get_default_plugin_config("auditing", CsvAuditingPlugin)
        config["enabled"] = True  # Simulate user enabling the plugin

        # This should NOT raise - the config should be complete enough
        plugin = CsvAuditingPlugin(config)
        assert plugin.raw_output_file == "logs/gatekit_audit.csv"

    def test_config_editor_with_available_handlers_includes_schema_defaults(self):
        """ConfigEditorScreen methods should include schema defaults when handlers available."""
        from gatekit.plugins.auditing.csv import CsvAuditingPlugin

        # Create minimal config
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test-server", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("/tmp/test-config.yaml"), config)

        # Set up available_handlers WITH the plugin class (simulates normal operation)
        screen.available_handlers = {
            "security": {},
            "auditing": {"audit_csv": CsvAuditingPlugin},
            "middleware": {},
        }

        # Get config for unconfigured plugin
        result = screen._get_global_plugin_config("audit_csv", "auditing")

        # Should include schema defaults because handler class is available
        assert "output_file" in result, \
            "With available_handlers populated, schema defaults should be included"
        assert result["output_file"] == "logs/gatekit_audit.csv"
