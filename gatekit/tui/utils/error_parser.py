"""Parse validation errors to extract paths and map to widgets."""

import re
from typing import TYPE_CHECKING, List, Tuple, Dict

if TYPE_CHECKING:
    from .field_registry import FieldRegistry


def parse_validation_errors(errors: List[str]) -> List[Tuple[str, str]]:
    """Parse validation errors to extract paths and messages.

    Args:
        errors: List of error strings from validator

    Returns:
        List of (json_pointer, error_message) tuples
    """
    parsed = []

    for error in errors:
        # Expected formats:
        # 1. "At /path/to/field: Error message" (from SchemaValidator)
        # 2. "field_name: Error message"
        # 3. "Error message"

        # Try "At /path" format first (from SchemaValidator)
        path_match = re.match(r"At ([^:]+):\s*(.+)", error)
        if path_match:
            path = path_match.group(1).strip()
            message = path_match.group(2).strip()
            parsed.append((path, message))
        else:
            # Try simple field:message format
            field_match = re.match(r"([^:]+):\s*(.+)", error)
            if field_match and "/" not in field_match.group(1):
                field = field_match.group(1).strip()
                message = field_match.group(2).strip()
                # Convert field name to path
                path = f"/properties/{field}"
                parsed.append((path, message))
            else:
                # No path found, general error
                parsed.append(("", error))

    return parsed


def map_errors_to_widgets(
    errors: List[str], registry: "FieldRegistry"
) -> Dict[str, List[str]]:
    """Map validation errors to widget IDs.

    Args:
        errors: List of error strings
        registry: Field registry for mapping

    Returns:
        Dict of widget_id -> [error_messages]
    """
    widget_errors = {}
    parsed = parse_validation_errors(errors)

    for path, message in parsed:
        if path:
            widget_id = registry.map_error_path(path)
            if widget_id:
                if widget_id not in widget_errors:
                    widget_errors[widget_id] = []
                widget_errors[widget_id].append(message)
            else:
                # No widget found, add to general errors
                if "" not in widget_errors:
                    widget_errors[""] = []
                widget_errors[""].append(f"{path}: {message}")
        else:
            # General error
            if "" not in widget_errors:
                widget_errors[""] = []
            widget_errors[""].append(message)

    return widget_errors
