"""Modal for editing objects within arrays."""

from typing import Dict, Any, Optional, List
from textual.screen import ModalScreen
from textual.widgets import Button, Label
from textual.containers import Vertical, Horizontal
from textual.app import ComposeResult


class ObjectItemModal(ModalScreen):
    """Modal for editing an object within an array."""

    CSS = """
    .object-item-modal {
        padding: 2;
        max-width: 60;
        max-height: 80%;
    }
    
    .modal-title {
        font-size: 1.2em;
        font-weight: bold;
        margin-bottom: 1;
    }
    
    .modal-buttons {
        margin-top: 2;
        align-horizontal: right;
    }
    """

    def __init__(
        self,
        item_schema: Dict[str, Any],
        item_data: Dict[str, Any] = None,
        item_index: Optional[int] = None,
    ):
        """Initialize object item editor modal.

        Args:
            item_schema: JSON Schema for the object
            item_data: Existing object data (for editing)
            item_index: Index of item being edited (None for new)
        """
        super().__init__()
        self.item_schema = item_schema
        self.item_data = item_data or {}
        self.item_index = item_index
        self.form_adapter = None

    def compose(self) -> ComposeResult:
        """Compose the modal UI."""
        # Import here to avoid circular dependency
        from gatekit.tui.utils.json_form_adapter import JSONFormAdapter

        # Create a temporary schema wrapping the item
        wrapper_schema = {
            "type": "object",
            "properties": self.item_schema.get("properties", {}),
            "required": self.item_schema.get("required", []),
        }

        # Additional properties handling
        if "additionalProperties" in self.item_schema:
            wrapper_schema["additionalProperties"] = self.item_schema[
                "additionalProperties"
            ]

        self.form_adapter = JSONFormAdapter(
            wrapper_schema,
            initial_data=self.item_data,
            json_pointer_base="/items",  # Array item context
        )

        with Vertical(classes="object-item-modal"):
            # Title
            title = (
                f"Edit Item #{self.item_index + 1}"
                if self.item_index is not None
                else "Add New Item"
            )
            yield Label(title, classes="modal-title")

            # Generate form from item schema
            yield from self.form_adapter.generate_form()

            # Action buttons
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "save":
            # Get form data
            item_data = self.form_adapter.get_form_data()

            # Quick validation
            errors = self._validate_item(item_data)
            if errors:
                error_msg = "\n".join(errors)
                self.app.notify(error_msg, severity="error", title="Validation Error")
                return

            # Return the data with index
            self.dismiss({"index": self.item_index, "data": item_data})

        elif event.button.id == "cancel":
            self.dismiss(None)

    def _validate_item(self, data: Dict[str, Any]) -> List[str]:
        """Validate item data against schema.

        Args:
            data: Item data to validate

        Returns:
            List of error messages
        """
        errors = []
        required = self.item_schema.get("required", [])
        properties = self.item_schema.get("properties", {})

        # Check required fields
        for field in required:
            if field not in data or data[field] is None or data[field] == "":
                errors.append(f"{field} is required")

        # Validate each field
        for field, value in data.items():
            if field in properties:
                field_schema = properties[field]

                # Pattern validation
                if "pattern" in field_schema and isinstance(value, str):
                    import re

                    if value and not re.match(field_schema["pattern"], value):
                        pattern = field_schema["pattern"]
                        errors.append(f"{field}: Does not match pattern {pattern}")

                # Enum validation (should already be enforced by Select widget)
                if "enum" in field_schema and value not in field_schema["enum"]:
                    allowed = ", ".join(map(str, field_schema["enum"]))
                    errors.append(f"{field}: Must be one of {allowed}")

                # Range validation
                if (
                    field_schema.get("type") in ["integer", "number"]
                    and value is not None
                ):
                    if "minimum" in field_schema and value < field_schema["minimum"]:
                        errors.append(f"{field}: Must be >= {field_schema['minimum']}")
                    if "maximum" in field_schema and value > field_schema["maximum"]:
                        errors.append(f"{field}: Must be <= {field_schema['maximum']}")

        return errors
