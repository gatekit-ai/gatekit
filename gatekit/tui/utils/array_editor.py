"""Array editor widget for JSON Schema arrays."""

from typing import Dict, Any, List, Optional
from textual.app import ComposeResult
from textual.widgets import Button, DataTable, Input, Checkbox, Static, Label
from textual.containers import Container, Vertical, Horizontal
from textual.message import Message
from textual.events import Key


class ArrayEditor(Container):
    """Widget for editing array values based on JSON Schema."""

    DEFAULT_CSS = """
    .array-editor {
        border: solid $border;
        padding: 1;
        margin: 1 0;
    }
    
    .array-title {
        text-style: bold;
        margin-bottom: 1;
    }
    
    .simple-array-table,
    .object-array-table {
        margin: 1 0;
        height: auto;
        max-height: 20;
    }
    
    DataTable:hover .datatable--cursor-cell:last-child {
        background: $primary-lighten-3;
    }
    
    .add-item-controls {
        margin-top: 1;
        padding-top: 1;
        border-top: solid $border;
    }
    
    .add-object-button {
        margin-top: 1;
    }
    
    .enum-array-select {
        height: auto;
        min-height: 5;
        max-height: 10;
        border: solid $border;
        padding: 1;
    }
    """

    class ItemAdded(Message):
        """Message when an item is added."""

        def __init__(self, item: Any):
            self.item = item
            super().__init__()

    class ItemRemoved(Message):
        """Message when an item is removed."""

        def __init__(self, index: int):
            self.index = index
            super().__init__()

    class ItemEdited(Message):
        """Message when an item is edited."""

        def __init__(self, index: int, item: Any):
            self.index = index
            self.item = item
            super().__init__()

    def __init__(
        self,
        name: str,
        schema: Dict[str, Any],
        items: List[Any] = None,
        json_pointer_base: str = "",
    ):
        """Initialize array editor.

        Args:
            name: Field name for the array
            schema: JSON Schema for the array
            items: Initial array items
            json_pointer_base: Base JSON Pointer path for this array
        """
        # Don't set ID here - let the field registry handle it like all other widgets
        super().__init__(classes="array-editor")

        self.field_name = name  # Use field_name instead of name to avoid conflict
        self.schema = schema
        self.items = items if items is not None else []
        self.item_schema = schema.get("items", {})
        self.json_pointer_base = json_pointer_base
        self.table = None

    def compose(self) -> ComposeResult:
        """Compose the array editor."""
        with Vertical():
            # Array title
            title = self.schema.get("title", self.field_name.replace("_", " ").title())
            yield Label(f"{title} ({len(self.items)} items)", classes="array-title")

            # Description if available
            if "description" in self.schema:
                yield Static(self.schema["description"], classes="field-description")

            # Different UI based on array type
            if self._is_enum_array():
                # Multi-select for enum arrays
                yield from self._compose_enum_array()
            elif self._is_simple_array():
                # Inline editing for simple types
                yield from self._compose_simple_array()
            else:
                # Table with modal editing for object arrays
                yield from self._compose_object_array()

    def _is_enum_array(self) -> bool:
        """Check if this is an array of enum values."""
        return "enum" in self.item_schema

    def _is_simple_array(self) -> bool:
        """Check if this is an array of simple types."""
        # Enum arrays take precedence over simple arrays
        if self._is_enum_array():
            return False
        item_type = self.item_schema.get("type")
        return item_type in ["string", "number", "integer", "boolean"]

    def _compose_enum_array(self) -> ComposeResult:
        """Compose UI for enum array (multi-select using checkboxes)."""
        # Use checkboxes for enum selection since SelectMultiple doesn't exist
        # and SelectionList API is complex for this use case
        from textual.widgets import Checkbox, Static
        from textual.containers import VerticalScroll
        import hashlib

        container_id = (
            f"{self.id}_enum_container"
            if self.id
            else f"{self.field_name}_enum_container"
        )

        # Use 'with' context to yield container with children
        with VerticalScroll(id=container_id, classes="enum-array-select"):
            enum_values = self.item_schema.get("enum", [])

            if not enum_values:
                # If no enum values, show a message
                yield Static("No options available", classes="no-options")
            else:
                for i, enum_value in enumerate(enum_values):
                    # Sanitize checkbox ID - use index and hash for uniqueness
                    # This avoids issues with spaces, special chars in enum values
                    value_hash = hashlib.md5(str(enum_value).encode()).hexdigest()[:8]
                    checkbox_id = f"{container_id}_item_{i}_{value_hash}"
                    checked = enum_value in self.items
                    yield Checkbox(
                        str(enum_value),
                        value=checked,
                        id=checkbox_id,
                        name=str(enum_value),  # Store the enum value in name attribute
                    )

    def _compose_simple_array(self) -> ComposeResult:
        """Compose UI for simple array (inline add/remove)."""
        # Table for existing items
        table_id = f"{self.id}_table" if self.id else f"array_{self.field_name}_table"
        table = DataTable(
            id=table_id,
            show_header=True,
            cursor_type="row",
            classes="simple-array-table",
        )
        table.add_columns("Value", "Actions")

        # Add existing items
        for _i, item in enumerate(self.items):
            table.add_row(str(item), "❌")

        self.table = table
        yield table

        # Add controls
        with Horizontal(classes="add-item-controls"):
            item_type = self.item_schema.get("type")
            # Use container ID as prefix for uniqueness
            widget_id = (
                f"{self.id}_new_item" if self.id else f"{self.field_name}_new_item"
            )

            if item_type == "boolean":
                yield Checkbox("New Value", id=widget_id)
            elif item_type in ["string", "number", "integer"]:
                placeholder = f"Enter {item_type}"
                if "pattern" in self.item_schema:
                    placeholder += f" (pattern: {self.item_schema['pattern']})"
                yield Input(placeholder=placeholder, id=widget_id)

            button_id = f"{self.id}_add" if self.id else f"add_{self.field_name}"
            yield Button("Add", id=button_id, variant="primary")

    def _compose_object_array(self) -> ComposeResult:
        """Compose UI for object array (table with modal editing)."""
        # Determine columns from object properties
        properties = self.item_schema.get("properties", {})

        # Use first 4 properties as columns (plus actions)
        display_props = list(properties.keys())[:4]
        columns = [prop.replace("_", " ").title() for prop in display_props]
        columns.extend(["Edit", "Remove"])

        # Create table
        table_id = f"{self.id}_table" if self.id else f"array_{self.field_name}_table"
        table = DataTable(
            id=table_id,
            show_header=True,
            cursor_type="row",
            classes="object-array-table",
        )
        table.add_columns(*columns)

        # Add existing items
        for item in self.items:
            if isinstance(item, dict):
                row_data = []
                for prop in display_props:
                    value = item.get(prop, "")
                    # Truncate long values
                    str_value = str(value)
                    if len(str_value) > 20:
                        str_value = str_value[:17] + "..."
                    row_data.append(str_value)
                row_data.extend(["✏️", "❌"])
                table.add_row(*row_data)

        self.table = table
        yield table

        # Add button
        button_id = f"{self.id}_add" if self.id else f"add_{self.field_name}"
        yield Button(
            f"Add {self.field_name.replace('_', ' ').title()}",
            id=button_id,
            variant="primary",
            classes="add-object-button",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        expected_id = f"{self.id}_add" if self.id else f"add_{self.field_name}"
        if event.button.id == expected_id:
            if self._is_simple_array():
                self._add_simple_item()
            else:
                self._add_object_item()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle cell selection in DataTable."""
        if not self.table:
            return

        row = event.coordinate.row
        col = event.coordinate.column
        col_count = self.table.column_count

        if self._is_simple_array():
            # Simple array - last column is remove
            if col == col_count - 1:  # Remove column
                self._remove_item(row)
        else:
            # Object array - last two columns are edit/remove
            if col == col_count - 2:  # Edit column
                self._edit_object_item(row)
            elif col == col_count - 1:  # Remove column
                self._remove_item(row)

    def on_key(self, event: Key) -> None:
        """Handle keyboard events for accessibility."""
        if event.key in ("delete", "backspace") and self.table:
            if self.table.cursor_row is not None and self.table.cursor_row < len(
                self.items
            ):
                self._remove_item(self.table.cursor_row)
                event.stop()

    def _add_simple_item(self):
        """Add a simple item from inline controls."""
        # Use container ID as prefix for uniqueness
        widget_id = f"{self.id}_new_item" if self.id else f"{self.field_name}_new_item"

        try:
            widget = self.query_one(f"#{widget_id}")

            if isinstance(widget, Input):
                value = widget.value.strip()
                if not value:
                    self.app.notify("Value is required", severity="error")
                    return

                # Type conversion
                item_type = self.item_schema.get("type")
                if item_type == "integer":
                    try:
                        value = int(value)
                    except ValueError:
                        self.app.notify("Must be an integer", severity="error")
                        return
                elif item_type == "number":
                    try:
                        value = float(value)
                    except ValueError:
                        self.app.notify("Must be a number", severity="error")
                        return

                # Pattern validation
                if "pattern" in self.item_schema and isinstance(value, str):
                    import re

                    if not re.match(self.item_schema["pattern"], value):
                        self.app.notify("Invalid format", severity="error")
                        return

                self.items.append(value)
                widget.value = ""  # Clear input

            elif isinstance(widget, Checkbox):
                self.items.append(widget.value)

            self._rebuild_table()
            self.post_message(self.ItemAdded(self.items[-1]))

        except Exception as e:
            self.app.notify(f"Error adding item: {e}", severity="error")

    def _add_object_item(self):
        """Open modal to add an object item."""
        from gatekit.tui.utils.object_item_modal import ObjectItemModal

        modal = ObjectItemModal(self.item_schema)
        self.app.push_screen(modal, self._handle_object_modal_result)

    def _edit_object_item(self, index: int):
        """Open modal to edit an object item."""
        if 0 <= index < len(self.items):
            from gatekit.tui.utils.object_item_modal import ObjectItemModal

            modal = ObjectItemModal(self.item_schema, self.items[index], index)
            self.app.push_screen(modal, self._handle_object_modal_result)

    def _handle_object_modal_result(self, result: Optional[Dict[str, Any]]):
        """Handle result from object item modal.

        Args:
            result: None if cancelled, or {"index": int/None, "data": dict}
        """
        if result is None:
            return  # Cancelled

        index = result.get("index")
        data = result.get("data")

        if index is None:
            # Adding new item
            self.items.append(data)
            self.post_message(self.ItemAdded(data))
        else:
            # Editing existing item
            if 0 <= index < len(self.items):
                self.items[index] = data
                self.post_message(self.ItemEdited(index, data))

        self._rebuild_table()

    def _remove_item(self, index: int):
        """Remove an item by index."""
        if 0 <= index < len(self.items):
            self.items.pop(index)
            self._rebuild_table()
            self.post_message(self.ItemRemoved(index))
            self.app.notify("Item removed", severity="information")

    def _rebuild_table(self):
        """Rebuild the table after changes."""
        if not self.table:
            return

        self.table.clear()

        if self._is_simple_array():
            # Simple array
            for item in self.items:
                self.table.add_row(str(item), "❌")
        else:
            # Object array
            properties = self.item_schema.get("properties", {})
            display_props = list(properties.keys())[:4]

            for item in self.items:
                if isinstance(item, dict):
                    row_data = []
                    for prop in display_props:
                        value = item.get(prop, "")
                        str_value = str(value)
                        if len(str_value) > 20:
                            str_value = str_value[:17] + "..."
                        row_data.append(str_value)
                    row_data.extend(["✏️", "❌"])
                    self.table.add_row(*row_data)

        # Update title with count
        title_label = self.query_one(".array-title", Label)
        title = self.schema.get("title", self.field_name.replace("_", " ").title())
        title_label.update(f"{title} ({len(self.items)} items)")

    def get_value(self) -> List[Any]:
        """Get the current array value.

        Note: For enum arrays with mixed types (e.g., 1 and "1"), this preserves
        the original type by matching string representation. In the rare case of
        ambiguous values, the first match in the enum list is used.
        """
        if self._is_enum_array():
            # Get selected values from checkboxes
            try:
                container_id = (
                    f"{self.id}_enum_container"
                    if self.id
                    else f"{self.field_name}_enum_container"
                )
                container = self.query_one(f"#{container_id}")

                selected_values = []
                for checkbox in container.query("Checkbox"):
                    if checkbox.value:
                        # Get the enum value from the name attribute
                        enum_value = checkbox.name
                        # Try to preserve original type if possible
                        # Edge case: if enum has both 1 and "1", first match wins
                        for original in self.item_schema["enum"]:
                            if str(original) == enum_value:
                                selected_values.append(original)
                                break

                return selected_values
            except Exception:
                # In test context, app might not exist - just return fallback
                # In real app context, this would be a compose issue
                return self.items

        return self.items
