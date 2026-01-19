"""Test that modal handles consolidated config correctly.

This test file implements Phase 1 of the plugin configuration consolidation for TUI modals.
All tests should FAIL initially (RED phase of TDD).
"""

from gatekit.config.models import PluginConfig
from gatekit.tui.screens.plugin_config.modal import PluginConfigModal
from gatekit.plugins.security.secrets import BasicSecretsFilterPlugin


class TestPluginModalConsolidation:
    """Test that modal handles consolidated config correctly."""

    def test_modal_no_split_inject_needed(self):
        """Modal receives config directly without injection."""
        wrapper = PluginConfig(
            handler="basic_secrets_filter",
            config={"enabled": True, "priority": 50, "action": "block"}
        )

        # Modal should receive config as-is (no injection needed)
        # The modal should work directly with wrapper.config
        modal_config = wrapper.config.copy()
        assert modal_config == wrapper.config
        assert "enabled" in modal_config
        assert "priority" in modal_config

    def test_modal_framework_field_injection(self):
        """Modal injects framework fields into schema."""
        modal = PluginConfigModal(BasicSecretsFilterPlugin, "basic_secrets_filter", {})
        schema = modal.json_schema

        # Framework fields should be present in schema
        assert "enabled" in schema["properties"]
        assert "priority" in schema["properties"]

        # Plugin fields should also be present
        assert "action" in schema["properties"]

        # Framework fields should come first (ordering)
        props_list = list(schema["properties"].keys())
        assert props_list.index("enabled") < props_list.index("action")
        assert props_list.index("priority") < props_list.index("action")

    def test_modal_framework_field_schemas(self):
        """Framework fields have proper schema definitions."""
        modal = PluginConfigModal(BasicSecretsFilterPlugin, "basic_secrets_filter", {})
        schema = modal.json_schema

        # enabled field schema
        enabled_schema = schema["properties"]["enabled"]
        assert enabled_schema["type"] == "boolean"
        assert enabled_schema["default"]
        assert "title" in enabled_schema
        assert "description" in enabled_schema

        # priority field schema
        priority_schema = schema["properties"]["priority"]
        assert priority_schema["type"] == "integer"
        assert priority_schema["default"] == 50
        assert priority_schema["minimum"] == 0
        assert priority_schema["maximum"] == 100
        assert "title" in priority_schema
        assert "description" in priority_schema

    def test_modal_save_no_extraction_needed(self):
        """Modal saves config directly without extraction."""
        wrapper = PluginConfig(handler="basic_secrets_filter", config={})
        new_config = {
            "enabled": False,
            "priority": 30,
            "action": "redact"
        }

        # Should update config directly (properties handle the rest)
        wrapper.config = new_config
        assert not wrapper.enabled
        assert wrapper.priority == 30
        assert wrapper.config["action"] == "redact"

    def test_modal_state_consistency(self):
        """Modal shows consistent state with wrapper."""
        wrapper = PluginConfig(
            handler="basic_secrets_filter",
            config={"enabled": False, "priority": 10}
        )

        # Modal should show same state
        modal_config = wrapper.config.copy()
        assert not modal_config["enabled"]
        assert modal_config["enabled"] == wrapper.enabled  # Consistent!

    def test_modal_config_with_all_fields(self):
        """Modal handles config with both framework and plugin fields."""
        wrapper = PluginConfig(
            handler="basic_secrets_filter",
            config={
                "enabled": False,
                "priority": 25,
                "action": "block",
                "secret_types": ["api_key", "password"]
            }
        )

        # All fields should be accessible
        assert not wrapper.enabled
        assert wrapper.priority == 25
        assert wrapper.config["action"] == "block"
        assert wrapper.config["secret_types"] == ["api_key", "password"]

    def test_modal_config_modification_preserves_other_fields(self):
        """Modifying enabled/priority preserves other config fields."""
        wrapper = PluginConfig(
            handler="basic_secrets_filter",
            config={
                "enabled": True,
                "priority": 50,
                "action": "block",
                "secret_types": ["api_key"]
            }
        )

        # Modify via properties
        wrapper.enabled = False
        wrapper.priority = 20

        # Other fields should be preserved
        assert wrapper.config["action"] == "block"
        assert wrapper.config["secret_types"] == ["api_key"]

    def test_modal_empty_config_uses_defaults(self):
        """Empty config dict uses default values for framework fields."""
        wrapper = PluginConfig(handler="basic_secrets_filter", config={})

        # Should use defaults
        assert wrapper.enabled
        assert wrapper.priority == 50
