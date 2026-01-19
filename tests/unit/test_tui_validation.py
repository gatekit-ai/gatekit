"""Tests for TUI validation infrastructure."""

import pytest
from unittest.mock import Mock

from gatekit.tui.utils.json_pointer import (
    escape_json_pointer,
    unescape_json_pointer,
    path_to_widget_id,
    widget_id_to_path,
    extract_required_leaf_fields,
    get_field_schema,
)
from gatekit.tui.utils.field_registry import FieldRegistry
from gatekit.tui.utils.schema_cache import get_schema_validator, clear_validator_cache
from gatekit.tui.utils.error_parser import (
    parse_validation_errors,
    map_errors_to_widgets,
)


class TestJSONPointerUtilities:
    """Test JSON Pointer path conversions."""

    def test_basic_path_conversion(self):
        """Test basic path to widget ID conversion."""
        path = "/properties/enabled"
        widget_id = path_to_widget_id(path)
        assert widget_id == "wg__properties__enabled"
        assert widget_id_to_path(widget_id) == path

    def test_path_with_special_characters(self):
        """Test paths with special characters that need escaping."""
        path = "/properties/config~/timeout"
        escaped = escape_json_pointer(path)
        assert "__" in escaped  # / becomes __
        # Note: Our implementation doesn't use JSON Pointer ~0/~1 escaping
        assert unescape_json_pointer(escaped) == path

    def test_nested_path(self):
        """Test nested JSON Pointer paths."""
        path = "/properties/tools/items/0/action"
        widget_id = path_to_widget_id(path)
        assert widget_id == "wg__properties__tools__items__0__action"
        assert widget_id_to_path(widget_id) == path

    def test_invalid_widget_id(self):
        """Test that invalid widget IDs raise an error."""
        with pytest.raises(ValueError, match="Invalid widget ID format"):
            widget_id_to_path("invalid_id")

    def test_extract_required_leaf_fields(self):
        """Test extraction of required LEAF fields from schema."""
        schema = {
            "type": "object",
            "required": ["name", "config"],
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
                "config": {
                    "type": "object",
                    "required": ["timeout"],
                    "properties": {
                        "timeout": {"type": "integer"},
                        "retries": {"type": "integer"},
                    },
                },
            },
        }

        required = extract_required_leaf_fields(schema)

        # Only leaf fields should be marked as required
        assert "/properties/name" in required
        assert "/properties/config/properties/timeout" in required

        # Parent objects should NOT be in the required set
        assert "/properties/config" not in required

        # Non-required fields should not be included
        assert "/properties/enabled" not in required
        assert "/properties/config/properties/retries" not in required

    def test_extract_required_with_optional_parent(self):
        """Test that optional parent with required children doesn't mark children as required."""
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "optional_config": {
                    "type": "object",
                    "required": ["setting"],
                    "properties": {"setting": {"type": "string"}},
                },
            },
        }

        required = extract_required_leaf_fields(schema)

        # Only top-level required field
        assert "/properties/name" in required

        # Child of optional parent should not be required
        assert "/properties/optional_config/properties/setting" not in required

    def test_extract_required_from_array_items(self):
        """Test extraction of required fields from array item schemas."""
        schema = {
            "type": "object",
            "required": ["tools"],
            "properties": {
                "tools": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string"},
                            "action": {"type": "string"},
                        },
                    },
                }
            },
        }

        required = extract_required_leaf_fields(schema)

        # Array item required fields
        assert "/properties/tools/items/properties/name" in required
        assert "/properties/tools/items/properties/action" not in required

    def test_get_field_schema(self):
        """Test getting field schema by JSON Pointer path."""
        schema = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "timeout": {"type": "integer", "minimum": 1, "maximum": 3600}
                    },
                }
            },
        }

        # Get nested field schema
        field_schema = get_field_schema(schema, "/properties/config/properties/timeout")
        assert field_schema["type"] == "integer"
        assert field_schema["minimum"] == 1
        assert field_schema["maximum"] == 3600

        # Get root schema
        assert get_field_schema(schema, "/") == schema

        # Non-existent path returns empty dict
        assert get_field_schema(schema, "/properties/nonexistent") == {}


class TestFieldRegistry:
    """Test the central field registry."""

    def test_register_field(self):
        """Test registering a field in the registry."""
        registry = FieldRegistry()
        widget = Mock(id=None)
        schema = {"type": "string"}

        widget_id = registry.register("/properties/name", widget, schema, required=True)

        assert widget_id == "wg__properties__name"
        assert widget.id == widget_id

        # Check both lookups work
        info = registry.get_by_pointer("/properties/name")
        assert info is not None
        assert info.widget == widget
        assert info.required is True

        info2 = registry.get_by_widget_id(widget_id)
        assert info2 == info

    def test_get_widget(self):
        """Test getting widget by pointer."""
        registry = FieldRegistry()
        widget = Mock()

        registry.register("/properties/test", widget, {})

        assert registry.get_widget("/properties/test") == widget
        assert registry.get_widget("/properties/nonexistent") is None

    def test_map_error_path_instance_to_schema(self):
        """Test mapping instance paths to schema paths."""
        registry = FieldRegistry()
        widget = Mock()
        # Mock widget needs to not have an 'id' attribute initially
        # so the registry will set it
        del widget.id

        # Register a field in an array
        registry.register(
            "/properties/tools/items/properties/action", widget, {"type": "string"}
        )

        # Map instance path to widget ID
        widget_id = registry.map_error_path("/tools/0/action")
        assert widget_id == "wg__properties__tools__items__properties__action"

    def test_instance_to_schema_path_conversion(self):
        """Test conversion of instance paths to schema paths."""
        registry = FieldRegistry()

        # Simple property
        assert registry._instance_to_schema_path("/name") == "/properties/name"

        # Array item property
        assert (
            registry._instance_to_schema_path("/tools/0/action")
            == "/properties/tools/items/properties/action"
        )

        # Nested object
        assert (
            registry._instance_to_schema_path("/config/timeout")
            == "/properties/config/properties/timeout"
        )

        # Complex nested structure
        assert (
            registry._instance_to_schema_path("/tools/2/settings/enabled")
            == "/properties/tools/items/properties/settings/properties/enabled"
        )


class TestSchemaCache:
    """Test the validator caching singleton."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_validator_cache()

    def test_singleton_behavior(self):
        """Test that validator is truly cached as singleton."""
        validator1 = get_schema_validator()
        validator2 = get_schema_validator()

        # Should be the same instance
        assert validator1 is validator2

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_cache_clearing(self):
        """Test that cache can be cleared."""
        validator1 = get_schema_validator()
        clear_validator_cache()
        validator2 = get_schema_validator()

        # Should be different instances after clearing
        assert validator1 is not validator2


class TestErrorParser:
    """Test validation error parsing and mapping."""

    def test_parse_path_format(self):
        """Test parsing errors with 'At /path:' format."""
        errors = [
            "At /tools/0/action: Must be one of: allow, deny",
            "At /config/timeout: Must be an integer",
        ]

        parsed = parse_validation_errors(errors)

        assert len(parsed) == 2
        assert parsed[0] == ("/tools/0/action", "Must be one of: allow, deny")
        assert parsed[1] == ("/config/timeout", "Must be an integer")

    def test_parse_field_format(self):
        """Test parsing errors with 'field:' format."""
        errors = ["name: This field is required", "timeout: Must be >= 1"]

        parsed = parse_validation_errors(errors)

        assert len(parsed) == 2
        assert parsed[0] == ("/properties/name", "This field is required")
        assert parsed[1] == ("/properties/timeout", "Must be >= 1")

    def test_parse_general_errors(self):
        """Test parsing general errors without paths."""
        errors = ["Invalid configuration format", "Schema validation failed"]

        parsed = parse_validation_errors(errors)

        assert len(parsed) == 2
        assert parsed[0] == ("", "Invalid configuration format")
        assert parsed[1] == ("", "Schema validation failed")

    def test_map_errors_to_widgets(self):
        """Test mapping parsed errors to widget IDs."""
        registry = FieldRegistry()

        # Register some widgets
        widget1 = Mock()
        widget2 = Mock()
        # Mock widgets need to not have an 'id' attribute initially
        # so the registry will set it
        del widget1.id
        del widget2.id
        registry.register("/properties/name", widget1, {"type": "string"})
        registry.register(
            "/properties/tools/items/properties/action", widget2, {"type": "string"}
        )

        errors = [
            "At /name: This field is required",
            "At /tools/0/action: Must be one of: allow, deny",
            "General configuration error",
        ]

        widget_errors = map_errors_to_widgets(errors, registry)

        # Check mappings
        assert "wg__properties__name" in widget_errors
        assert widget_errors["wg__properties__name"] == ["This field is required"]

        assert "wg__properties__tools__items__properties__action" in widget_errors
        assert widget_errors["wg__properties__tools__items__properties__action"] == [
            "Must be one of: allow, deny"
        ]

        # General errors with no path
        assert "" in widget_errors
        assert "General configuration error" in widget_errors[""]

    def test_map_unmapped_path_errors(self):
        """Test that errors with unmapped paths are added to general errors."""
        registry = FieldRegistry()

        errors = [
            "At /unknown/field: Some error",
        ]

        widget_errors = map_errors_to_widgets(errors, registry)

        # Should be in general errors with path prefix
        assert "" in widget_errors
        assert "/unknown/field: Some error" in widget_errors[""]
