"""JSON Pointer utilities for widget ID generation and error mapping."""

from typing import Dict, Any, Set


def escape_json_pointer(path: str) -> str:
    """Escape a JSON Pointer path for use in widget IDs.

    Textual widget IDs can only contain letters, numbers, underscores, or hyphens.
    We use a simple escaping that works for our structured paths.

    Args:
        path: JSON Pointer path (e.g., "/properties/tools/items/0")

    Returns:
        Escaped string safe for widget IDs
    """
    # Remove leading slash and replace remaining slashes with double underscores
    # This works because property names in our schemas are already valid identifiers
    path = path.lstrip("/")
    # Replace / with __ (double underscore)
    path = path.replace("/", "__")
    # Replace any remaining special characters
    # Since we control the schema, we know property names are already safe
    return path


def unescape_json_pointer(escaped: str) -> str:
    """Unescape a widget ID back to JSON Pointer path.

    Args:
        escaped: Escaped widget ID component

    Returns:
        Original JSON Pointer path
    """
    # Replace double underscores back to slashes and add leading slash
    return "/" + escaped.replace("__", "/")


def path_to_widget_id(json_pointer: str) -> str:
    """Convert JSON Pointer path to widget ID.

    Args:
        json_pointer: JSON Pointer path (e.g., "/properties/enabled")

    Returns:
        Widget ID (e.g., "wg__properties__enabled")
    """
    return f"wg__{escape_json_pointer(json_pointer)}"


def widget_id_to_path(widget_id: str) -> str:
    """Convert widget ID back to JSON Pointer path.

    Args:
        widget_id: Widget ID (e.g., "wg__properties__enabled")

    Returns:
        JSON Pointer path (e.g., "/properties/enabled")
    """
    if not widget_id.startswith("wg__"):
        raise ValueError(f"Invalid widget ID format: {widget_id}")

    escaped = widget_id[4:]  # Remove "wg__" prefix
    return unescape_json_pointer(escaped)


def extract_required_leaf_fields(
    schema: Dict[str, Any], path_prefix: str = "", parent_required: bool = True
) -> Set[str]:
    """Extract paths to required LEAF fields only.

    Args:
        schema: JSON Schema object
        path_prefix: Current path prefix for recursion
        parent_required: Whether parent object is required

    Returns:
        Set of JSON Pointer paths to required leaf fields
    """
    required_paths = set()

    if schema.get("type") != "object":
        # Leaf field - add if parent is required
        if parent_required:
            required_paths.add(path_prefix)
        return required_paths

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    for prop_name, prop_schema in properties.items():
        field_path = f"{path_prefix}/properties/{prop_name}"
        is_required = prop_name in required

        if prop_schema.get("type") == "object":
            # Recurse into nested object
            nested_required = extract_required_leaf_fields(
                prop_schema,
                field_path,
                parent_required
                and is_required,  # Only if both parent and field required
            )
            required_paths.update(nested_required)
        elif prop_schema.get("type") == "array":
            # Arrays themselves aren't required leaves, but items might be
            items_schema = prop_schema.get("items", {})
            if items_schema.get("type") == "object":
                # Extract required fields from array item schema
                item_required = extract_required_leaf_fields(
                    items_schema, f"{field_path}/items", parent_required and is_required
                )
                required_paths.update(item_required)
        else:
            # Leaf field - add if required and parent chain is required
            if is_required and parent_required:
                required_paths.add(field_path)

    return required_paths


def get_field_schema(schema: Dict[str, Any], json_pointer: str) -> Dict[str, Any]:
    """Get schema for a field by JSON Pointer path.

    Args:
        schema: Root JSON Schema
        json_pointer: JSON Pointer path (e.g., "/properties/config/properties/timeout")

    Returns:
        Field schema or empty dict if not found
    """
    if not json_pointer or json_pointer == "/":
        return schema

    # Split path and traverse
    parts = json_pointer.strip("/").split("/")
    current = schema

    for part in parts:
        # Unescape JSON Pointer escapes
        part = part.replace("~1", "/").replace("~0", "~")

        if isinstance(current, dict):
            current = current.get(part, {})
        else:
            return {}

    return current
