"""Tests for TUI array editor components."""


from gatekit.tui.utils.array_editor import ArrayEditor
from gatekit.tui.utils.object_item_modal import ObjectItemModal


def test_array_type_detection():
    """Test detection of array types."""
    # Enum array
    enum_schema = {
        "type": "array",
        "items": {"type": "string", "enum": ["red", "green", "blue"]},
    }
    editor = ArrayEditor("colors", enum_schema)
    assert editor._is_enum_array()
    assert not editor._is_simple_array()

    # Simple array
    simple_schema = {"type": "array", "items": {"type": "string"}}
    editor = ArrayEditor("tags", simple_schema)
    assert not editor._is_enum_array()
    assert editor._is_simple_array()

    # Object array
    object_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "value": {"type": "integer"}},
        },
    }
    editor = ArrayEditor("items", object_schema)
    assert not editor._is_enum_array()
    assert not editor._is_simple_array()


def test_object_item_modal_validation():
    """Test object item validation in modal."""
    schema = {
        "type": "object",
        "required": ["tool"],
        "properties": {
            "tool": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$"},
            "display_name": {"type": "string", "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$"},
            "display_description": {"type": "string"},
        },
    }

    modal = ObjectItemModal(schema)

    # Test invalid data - invalid pattern
    errors = modal._validate_item({"tool": "123-invalid"})
    assert any("pattern" in e for e in errors)

    # Test missing required field
    errors = modal._validate_item({"tool": "valid-tool"})
    assert len(errors) == 0

    # Test optional display fields
    errors = modal._validate_item(
        {
            "tool": "validTool",
            "display_name": "DisplayName",
            "display_description": "Some description",
        }
    )
    assert len(errors) == 0


def test_array_crud_operations():
    """Test array add/edit/remove operations."""
    initial_items = [{"name": "item1", "value": 10}, {"name": "item2", "value": 20}]

    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "value": {"type": "integer"}},
        },
    }

    editor = ArrayEditor("items", schema, initial_items)

    # Test initial state
    assert len(editor.get_value()) == 2

    # Simulate adding item
    editor.items.append({"name": "item3", "value": 30})
    assert len(editor.get_value()) == 3

    # Simulate editing item
    editor.items[0] = {"name": "edited", "value": 15}
    assert editor.get_value()[0]["name"] == "edited"

    # Simulate removing item
    editor.items.pop(1)
    assert len(editor.get_value()) == 2


def test_tool_manager_array_schema():
    """Test array editor with Tool Manager schema."""
    # This is the actual schema used by Tool Manager plugin
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["tool"],
            "properties": {
                "tool": {
                    "type": "string",
                    "description": "Tool name to expose",
                    "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$",
                },
                "display_name": {
                    "type": "string",
                    "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$",
                },
                "display_description": {"type": "string"},
            },
        },
        "description": "List of tools available to clients",
    }

    initial_items = [{"tool": "bash"}, {"tool": "read", "display_name": "read_files"}]

    editor = ArrayEditor("tools", schema, initial_items)

    # Should be recognized as object array
    assert not editor._is_enum_array()
    assert not editor._is_simple_array()

    # Should have initial items
    assert len(editor.get_value()) == 2
    assert editor.get_value()[0]["tool"] == "bash"


def test_simple_string_array():
    """Test simple string array handling."""
    schema = {
        "type": "array",
        "items": {"type": "string", "pattern": "^[a-z]+$"},
        "description": "List of tags",
    }

    initial_items = ["alpha", "beta", "gamma"]

    editor = ArrayEditor("tags", schema, initial_items)

    # Should be recognized as simple array
    assert not editor._is_enum_array()
    assert editor._is_simple_array()

    # Should have initial items
    assert len(editor.get_value()) == 3
    assert "alpha" in editor.get_value()


def test_enum_array_multi_select():
    """Test enum array with multi-select."""
    schema = {
        "type": "array",
        "items": {"type": "string", "enum": ["read", "write", "execute", "delete"]},
        "description": "Select permissions",
    }

    initial_items = ["read", "write"]

    editor = ArrayEditor("permissions", schema, initial_items)

    # Should be recognized as enum array
    assert editor._is_enum_array()
    assert not editor._is_simple_array()

    # Should have initial items
    assert len(editor.get_value()) == 2
    assert "read" in editor.get_value()


def test_integer_array():
    """Test integer array handling."""
    schema = {
        "type": "array",
        "items": {"type": "integer", "minimum": 1, "maximum": 100},
        "description": "List of priority values",
    }

    initial_items = [10, 20, 30]

    editor = ArrayEditor("priorities", schema, initial_items)

    # Should be recognized as simple array
    assert not editor._is_enum_array()
    assert editor._is_simple_array()

    # Should have initial items
    assert len(editor.get_value()) == 3
    assert 10 in editor.get_value()
