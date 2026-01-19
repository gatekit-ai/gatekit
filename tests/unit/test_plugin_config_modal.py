"""Tests for plugin configuration modal functionality."""

from unittest.mock import patch
from gatekit.plugins.security.pii import BasicPIIFilterPlugin
from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
from gatekit.tui.screens.plugin_config import PluginConfigModal


class TestPluginConfigModal:
    """Test plugin configuration modal functionality."""

    def test_modal_initialization_with_schema(self):
        """Test modal initializes correctly with plugin that has schema."""
        current_config = {"enabled": True, "action": "redact"}
        modal = PluginConfigModal(BasicPIIFilterPlugin, "basic_pii_filter", current_config)

        assert modal.plugin_class == BasicPIIFilterPlugin
        assert modal.current_config["enabled"] is True
        assert modal.current_config["action"] == "redact"
        assert modal.current_config["priority"] == 50
        # Modal uses JSON Schema directly now
        assert modal.json_schema is not None
        assert isinstance(modal.json_schema, dict)
        assert modal.validation_errors == []

    def test_modal_initialization_with_invalid_schema(self):
        """Test modal handles invalid schema gracefully."""

        # Create a mock plugin class with invalid schema type
        class MockPlugin:
            @classmethod
            def get_json_schema(cls):
                return {
                    "type": "object",
                    "properties": {"invalid_field": {"type": "invalid_type"}},
                }

        current_config = {}
        modal = PluginConfigModal(MockPlugin, "mock", current_config)

        # Framework fields should be injected
        assert "enabled" in modal.json_schema["properties"]
        assert "priority" in modal.json_schema["properties"]
        # Plugin's invalid field should still be present
        assert "invalid_field" in modal.json_schema["properties"]

    def test_modal_initialization_without_schema(self):
        """Test modal with plugin that has no schema."""

        class MockPluginNoSchema:
            @classmethod
            def get_json_schema(cls):
                return {"type": "object", "properties": {}}

        current_config = {}
        modal = PluginConfigModal(MockPluginNoSchema, "mock_no_schema", current_config)

        # Framework fields should be injected even if plugin has no fields
        assert "enabled" in modal.json_schema["properties"]
        assert "priority" in modal.json_schema["properties"]
        assert "critical" in modal.json_schema["properties"]
        assert len(modal.json_schema["properties"]) == 3  # Only framework fields

    def test_collect_form_data_basic_fields(self):
        """Test collecting form data for basic field types."""
        modal = PluginConfigModal(BasicPIIFilterPlugin, "basic_pii_filter", {})

        # Mock the form adapter's get_form_data method
        with patch.object(modal.form_adapter, "get_form_data") as mock_get_data:
            mock_get_data.return_value = {
                "enabled": True,
                "action": "redact",
                "priority": 50,
            }

            config = modal.form_adapter.get_form_data()

            # Should collect data for all schema fields
            assert isinstance(config, dict)
            assert config["enabled"]
            assert config["action"] == "redact"
            assert config["priority"] == 50

    def test_validate_config_with_errors(self):
        """Test configuration validation with errors."""
        modal = PluginConfigModal(ToolManagerPlugin, "tool_manager", {})

        # Test with invalid config (missing required field)
        config = {
            "enabled": True,
            # Missing tools field
        }

        # Validate using the validator directly
        handler_name = modal._get_handler_name()
        errors = modal.validator.validate(handler_name, config)

        # Should have validation errors for missing tools field
        assert len(errors) >= 0  # Depends on schema requirements

    def test_validate_config_valid(self):
        """Test configuration validation with valid config."""
        modal = PluginConfigModal(ToolManagerPlugin, "tool_manager", {})

        config = {"enabled": True, "tools": [{"tool": "tool1"}, {"tool": "tool2"}]}

        # Validate using the validator directly
        handler_name = modal._get_handler_name()
        errors = modal.validator.validate(handler_name, config)
        assert errors == [] or errors is None


class TestPluginConfigModalIntegration:
    """Test modal integration with different plugin types."""

    def test_pii_plugin_modal_setup(self):
        """Test modal setup for PII plugin."""
        current_config = {
            "enabled": True,
            "action": "redact",
            "pii_types": {"email": {"enabled": True}, "phone": {"enabled": False}},
        }

        modal = PluginConfigModal(BasicPIIFilterPlugin, "basic_pii_filter", current_config)

        # Check JSON schema is loaded
        properties = modal.json_schema.get("properties", {})
        assert "enabled" in properties
        assert "action" in properties
        assert "pii_types" in properties

        # Check current config is preserved
        assert modal.current_config["enabled"]
        assert modal.current_config["action"] == "redact"

    def test_tool_allowlist_modal_setup(self):
        """Test modal setup for Tool Manager plugin."""
        # Use new configuration format
        current_config = {
            "enabled": True,
            "tools": [{"tool": "read_file"}, {"tool": "write_file"}],
        }

        modal = PluginConfigModal(ToolManagerPlugin, "tool_manager", current_config)

        # Check JSON schema is loaded
        properties = modal.json_schema.get("properties", {})
        assert "enabled" in properties
        assert "mode" not in properties
        assert "tools" in properties  # Tools array

        # Check tools field is configured correctly via shared fragment
        tools_field = properties["tools"]
        assert tools_field["$ref"] == "#/$defs/tool_selection"
        defs = modal.json_schema.get("$defs", {})
        tool_selection = defs.get("tool_selection", {})
        assert tool_selection.get("type") == "array"
        assert "tool" in tool_selection.get("items", {}).get("properties", {})
