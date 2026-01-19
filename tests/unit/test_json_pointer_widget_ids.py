"""Test JSON Pointer to widget ID conversion for Textual compatibility."""

import re
import pytest
from gatekit.tui.utils.json_pointer import (
    escape_json_pointer,
    unescape_json_pointer,
    path_to_widget_id,
    widget_id_to_path,
)

# Textual's identifier regex pattern
TEXTUAL_ID_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


class TestWidgetIDGeneration:
    """Test that widget IDs are valid for Textual."""

    def test_simple_property_path(self):
        """Test simple property path conversion."""
        path = "/properties/enabled"
        widget_id = path_to_widget_id(path)

        # Check format
        assert widget_id == "wg__properties__enabled"

        # Verify it's a valid Textual ID
        assert TEXTUAL_ID_PATTERN.match(widget_id), f"Invalid ID: {widget_id}"

        # Verify round-trip
        recovered_path = widget_id_to_path(widget_id)
        assert recovered_path == path

    def test_nested_object_path(self):
        """Test nested object path conversion."""
        path = "/properties/config/properties/timeout"
        widget_id = path_to_widget_id(path)

        # Check format
        assert widget_id == "wg__properties__config__properties__timeout"

        # Verify it's a valid Textual ID
        assert TEXTUAL_ID_PATTERN.match(widget_id), f"Invalid ID: {widget_id}"

        # Verify round-trip
        recovered_path = widget_id_to_path(widget_id)
        assert recovered_path == path

    def test_array_item_path(self):
        """Test array item property path conversion."""
        path = "/properties/tools/items/properties/action"
        widget_id = path_to_widget_id(path)

        # Check format
        assert widget_id == "wg__properties__tools__items__properties__action"

        # Verify it's a valid Textual ID
        assert TEXTUAL_ID_PATTERN.match(widget_id), f"Invalid ID: {widget_id}"

        # Verify round-trip
        recovered_path = widget_id_to_path(widget_id)
        assert recovered_path == path

    def test_no_tilde_characters(self):
        """Test that generated IDs don't contain tildes."""
        # Test various paths
        paths = [
            "/properties/enabled",
            "/properties/tools/items/properties/tool",
            "/properties/pii_types/properties/email",
            "/properties/config/properties/nested/properties/deep",
        ]

        for path in paths:
            widget_id = path_to_widget_id(path)

            # Ensure no tildes
            assert "~" not in widget_id, f"ID contains tilde: {widget_id}"

            # Ensure valid Textual ID
            assert TEXTUAL_ID_PATTERN.match(widget_id), f"Invalid ID: {widget_id}"

    def test_property_with_underscore(self):
        """Test property names with underscores."""
        path = "/properties/scan_base64"
        widget_id = path_to_widget_id(path)

        # Check format
        assert widget_id == "wg__properties__scan_base64"

        # Verify it's a valid Textual ID
        assert TEXTUAL_ID_PATTERN.match(widget_id), f"Invalid ID: {widget_id}"

        # Verify round-trip
        recovered_path = widget_id_to_path(widget_id)
        assert recovered_path == path

    def test_property_with_hyphen(self):
        """Test property names with hyphens (if they exist)."""
        path = "/properties/tool-name"
        widget_id = path_to_widget_id(path)

        # Check format
        assert widget_id == "wg__properties__tool-name"

        # Verify it's a valid Textual ID
        assert TEXTUAL_ID_PATTERN.match(widget_id), f"Invalid ID: {widget_id}"

        # Verify round-trip
        recovered_path = widget_id_to_path(widget_id)
        assert recovered_path == path

    def test_escape_unescape_consistency(self):
        """Test that escape and unescape are consistent."""
        test_paths = [
            "properties/enabled",
            "properties/tools/items/properties/action",
            "properties/config/properties/timeout",
        ]

        for path in test_paths:
            escaped = escape_json_pointer("/" + path)
            unescaped = unescape_json_pointer(escaped)
            assert unescaped == "/" + path

    def test_invalid_widget_id_format(self):
        """Test that invalid widget IDs raise errors."""
        with pytest.raises(ValueError, match="Invalid widget ID format"):
            widget_id_to_path("invalid_id")

        with pytest.raises(ValueError, match="Invalid widget ID format"):
            widget_id_to_path("properties__enabled")  # Missing wg__ prefix
