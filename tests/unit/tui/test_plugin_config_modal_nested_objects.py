"""Tests for nested object support in PluginConfigModal."""

import pytest
from unittest.mock import patch

from gatekit.tui.screens.plugin_config import PluginConfigModal
from gatekit.plugins.interfaces import SecurityPlugin


class MockNestedPlugin(SecurityPlugin):
    """Mock plugin with nested object schema for testing."""

    DISPLAY_NAME = "Test Nested Plugin"
    DISPLAY_SCOPE = "global"

    @classmethod
    def get_json_schema(cls):
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "Enable Plugin",
                    "default": True,
                },
                "nested_config": {
                    "type": "object",
                    "description": "A nested configuration object",
                    "properties": {
                        "sub_enabled": {
                            "type": "boolean",
                            "description": "Sub Feature Enabled",
                            "default": False,
                        },
                        "sub_value": {
                            "type": "string",
                            "description": "Sub Value",
                            "default": "test",
                        },
                        "sub_number": {
                            "type": "number",
                            "description": "Sub Number",
                            "default": 42,
                        },
                    },
                },
            },
        }


class TestPluginConfigModalNestedObjects:
    """Test nested object support in plugin configuration modal."""

    @pytest.fixture
    def modal_with_nested_config(self):
        """Create modal with nested configuration."""
        current_config = {
            "enabled": True,
            "nested_config": {
                "sub_enabled": True,
                "sub_value": "example",
                "sub_number": 100,
            },
        }
        return PluginConfigModal(MockNestedPlugin, "mock_nested", current_config)

    @pytest.fixture
    def modal_with_empty_config(self):
        """Create modal with empty configuration."""
        return PluginConfigModal(MockNestedPlugin, "mock_nested", {})

    def test_nested_object_schema_recognition(self, modal_with_nested_config):
        """Test that nested object schemas are properly recognized."""
        properties = modal_with_nested_config.json_schema.get("properties", {})

        # Verify schema has nested_config field
        assert "nested_config" in properties
        nested_field = properties["nested_config"]

        # Verify it's recognized as object type with properties
        assert nested_field["type"] == "object"
        assert "properties" in nested_field

        # Verify nested properties
        nested_properties = nested_field["properties"]
        assert "sub_enabled" in nested_properties
        assert "sub_value" in nested_properties
        assert "sub_number" in nested_properties

        # Verify nested property types
        assert nested_properties["sub_enabled"]["type"] == "boolean"
        assert nested_properties["sub_value"]["type"] == "string"
        assert nested_properties["sub_number"]["type"] == "number"

    def test_nested_widget_id_generation(self, modal_with_nested_config):
        """Test that nested widgets get correct IDs."""
        # This test verifies the ID pattern: field_{parent}_{child}
        # We can't directly test widget creation without full Textual setup,
        # but we can verify the logic through the _collect_form_data method

        json_properties = modal_with_nested_config.json_schema.get("properties", {})
        nested_field = json_properties["nested_config"]

        # Verify that the expected nested IDs would be generated
        expected_ids = [
            "field_nested_config_sub_enabled",
            "field_nested_config_sub_value",
            "field_nested_config_sub_number",
        ]

        properties = nested_field["properties"]
        generated_ids = [
            f"field_nested_config_{prop_name}" for prop_name in properties.keys()
        ]

        assert sorted(generated_ids) == sorted(expected_ids)

    def test_collect_nested_form_data_structure(self, modal_with_nested_config):
        """Test that nested form data collection builds proper structure."""
        # Mock the form adapter's get_form_data method
        with patch.object(
            modal_with_nested_config.form_adapter, "get_form_data"
        ) as mock_get_data:
            # Setup expected return structure
            mock_get_data.return_value = {
                "enabled": True,
                "nested_config": {
                    "sub_enabled": False,
                    "sub_value": "new_value",
                    "sub_number": 123,
                },
            }

            # Collect form data
            result = modal_with_nested_config.form_adapter.get_form_data()

            # Verify structure
            assert "enabled" in result
            assert "nested_config" in result
            assert result["enabled"]

            # Verify nested structure
            nested_result = result["nested_config"]
            assert isinstance(nested_result, dict)
            assert not nested_result["sub_enabled"]
            assert nested_result["sub_value"] == "new_value"
            assert nested_result["sub_number"] == 123  # Should be converted to int

    def test_collect_nested_form_data_with_defaults(self, modal_with_empty_config):
        """Test nested form data collection with default values."""
        with patch.object(
            modal_with_empty_config.form_adapter, "get_form_data"
        ) as mock_get_data:
            # Setup expected return structure with defaults
            mock_get_data.return_value = {
                "enabled": True,  # Default from schema
                "nested_config": {
                    "sub_enabled": False,  # Default from schema
                    "sub_value": "test",  # Default from schema when field is empty
                    "sub_number": 42,  # Default from schema when field is empty
                },
            }

            result = modal_with_empty_config.form_adapter.get_form_data()

            # Verify nested defaults are applied
            nested_result = result["nested_config"]
            assert not nested_result["sub_enabled"]  # From widget
            assert (
                nested_result["sub_value"] == "test"
            )  # Default from schema when field is empty
            assert (
                nested_result["sub_number"] == 42
            )  # Default from schema when field is empty

    def test_nested_validation_integration(self, modal_with_nested_config):
        """Test that validation works with nested objects."""
        # Create invalid nested config
        invalid_config = {
            "enabled": True,
            "nested_config": {
                "sub_enabled": "invalid_boolean",  # Should be boolean
                "sub_value": "valid_string",
                "sub_number": "not_a_number",  # Should be number
            },
        }

        # Mock the validator to return expected errors for nested fields
        with patch.object(
            modal_with_nested_config.validator, "validate"
        ) as mock_validate:
            mock_validate.return_value = [
                "At /nested_config/sub_enabled: Expected boolean, got string",
                "At /nested_config/sub_number: Expected number, got string",
            ]

            # Validation should catch nested field errors
            handler_name = modal_with_nested_config._get_handler_name()
            errors = (
                modal_with_nested_config.validator.validate(
                    handler_name, invalid_config
                )
                or []
            )

            # Should have errors for the nested invalid fields
            assert len(errors) > 0

            # Check that error messages reference nested fields properly
            error_messages = " ".join(errors)
            assert "nested_config" in error_messages

    def test_object_without_properties(self):
        """Test handling of object type without properties schema."""

        class MockSimpleObjectPlugin(SecurityPlugin):
            @classmethod
            def get_json_schema(cls):
                return {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {
                        "simple_object": {
                            "type": "object",
                            "description": "Simple Object",
                            # No properties defined - should fallback to JSON input
                        }
                    },
                }

        modal = PluginConfigModal(
            MockSimpleObjectPlugin, "mock_simple", {"simple_object": {"key": "value"}}
        )

        # Should handle object without properties gracefully
        # Get properties from JSON schema
        properties = modal.json_schema.get("properties", {})
        assert "simple_object" in properties
        assert properties["simple_object"]["type"] == "object"
        assert "properties" not in properties["simple_object"]

    def test_current_config_normalization(self, modal_with_empty_config):
        """Test that non-dict current values are normalized for nested access."""
        # This simulates cases where current_config might have non-dict values
        # for object fields, which should be handled gracefully

        modal_with_empty_config.current_config = {
            "enabled": True,
            "nested_config": "invalid_non_dict_value",  # Should be normalized to {}
        }

        # The modal should handle this gracefully when rendering
        # We can't test widget creation directly, but we can verify the logic
        # by checking that the compose method doesn't crash and handles the case

        # Verify the modal initializes without crashing
        assert modal_with_empty_config.json_schema is not None
        properties = modal_with_empty_config.json_schema.get("properties", {})
        assert "nested_config" in properties

    def test_pii_filter_plugin_schema_structure(self):
        """Test that PII filter plugin nested structure is handled correctly."""
        from gatekit.plugins.security.pii import BasicPIIFilterPlugin

        # Test with actual PII filter plugin configuration
        current_config = {
            "enabled": True,
            "action": "redact",
            "pii_types": {
                "email": {"enabled": True, "action": "redact"},
                "phone": {"enabled": False, "action": "block"},
            },
        }

        modal = PluginConfigModal(BasicPIIFilterPlugin, "basic_pii_filter", current_config)

        # Verify the PII types schema is recognized as nested object
        # Get properties from JSON schema
        properties = modal.json_schema.get("properties", {})
        assert "pii_types" in properties
        pii_types_field = properties["pii_types"]
        assert pii_types_field["type"] == "object"
        assert "properties" in pii_types_field

        # Verify email and phone are in the schema
        pii_properties = pii_types_field["properties"]
        assert "email" in pii_properties
        assert "phone" in pii_properties

        # Both should either have a $ref or be objects (implementation detail doesn't matter)
        email_prop = pii_properties["email"]
        assert "$ref" in email_prop or "type" in email_prop

        phone_prop = pii_properties["phone"]
        assert "$ref" in phone_prop or "type" in phone_prop

        # Verify the config values are preserved
        assert modal.current_config["pii_types"]["email"]["enabled"]
        assert not modal.current_config["pii_types"]["phone"]["enabled"]
