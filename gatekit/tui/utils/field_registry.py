"""Central field registry for widget-to-path mapping."""

from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class FieldInfo:
    """Information about a form field."""

    json_pointer: str  # Canonical schema path
    widget_id: str  # Generated widget ID
    widget: Any  # Widget instance
    schema: Dict[str, Any]  # Field schema
    required: bool  # Whether field is required
    parent_path: Optional[str] = None  # Parent object path if nested


class FieldRegistry:
    """Central registry mapping JSON Pointers to widgets."""

    def __init__(self):
        self.by_pointer: Dict[str, FieldInfo] = {}
        self.by_widget_id: Dict[str, FieldInfo] = {}

    def register(
        self, pointer: str, widget: Any, schema: Dict[str, Any], required: bool = False
    ) -> str:
        """Register a field and return its widget ID.

        Args:
            pointer: Canonical JSON Pointer path
            widget: Widget instance
            schema: Field schema
            required: Whether field is required

        Returns:
            Generated widget ID
        """
        from gatekit.tui.utils.json_pointer import path_to_widget_id

        widget_id = path_to_widget_id(pointer)
        # Only set ID if widget doesn't already have one (e.g., ArrayEditor sets its own)
        # Check if widget.id exists and is not None (widgets may have id=None initially)
        if hasattr(widget, "id") and widget.id is not None:
            # Widget already has an ID, use it
            widget_id = widget.id
        else:
            # Set the widget ID
            widget.id = widget_id

        info = FieldInfo(
            json_pointer=pointer,
            widget_id=widget_id,
            widget=widget,
            schema=schema,
            required=required,
        )

        self.by_pointer[pointer] = info
        self.by_widget_id[widget_id] = info

        return widget_id

    def get_by_pointer(self, pointer: str) -> Optional[FieldInfo]:
        """Get field info by JSON Pointer."""
        return self.by_pointer.get(pointer)

    def get_by_widget_id(self, widget_id: str) -> Optional[FieldInfo]:
        """Get field info by widget ID."""
        return self.by_widget_id.get(widget_id)

    def get_widget(self, pointer: str) -> Optional[Any]:
        """Get widget by JSON Pointer."""
        info = self.get_by_pointer(pointer)
        return info.widget if info else None

    def map_error_path(self, error_path: str) -> Optional[str]:
        """Map a validator error path to widget ID.

        Args:
            error_path: Path from validator (e.g., "/tools/0/action")

        Returns:
            Widget ID if found
        """
        # Convert instance path to schema path
        schema_path = self._instance_to_schema_path(error_path)
        info = self.get_by_pointer(schema_path)
        return info.widget_id if info else None

    def _instance_to_schema_path(self, instance_path: str) -> str:
        """Convert instance path to schema path.

        Example:
            /tools/0/action -> /properties/tools/items/properties/action
        """
        if not instance_path or instance_path == "/":
            return "/"

        parts = instance_path.strip("/").split("/")
        schema_parts = []
        in_array = False

        for _i, part in enumerate(parts):
            if part.isdigit():
                # This is an array index
                # The previous part was the array property name
                # Replace the array property with items
                if not in_array:
                    # First array index - add /items
                    schema_parts.append("items")
                    in_array = True
            else:
                # This is a property name
                if in_array:
                    # Property within array item
                    in_array = False
                    schema_parts.append("properties")
                    schema_parts.append(part)
                else:
                    # Regular property
                    schema_parts.append("properties")
                    schema_parts.append(part)

        return "/" + "/".join(schema_parts)
