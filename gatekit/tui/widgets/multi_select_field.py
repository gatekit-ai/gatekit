"""MultiSelectField widget for selecting multiple values from a predefined list.

This widget provides an intuitive checkbox-based interface for selecting multiple
options from a constrained set of values, preventing users from entering invalid
options in configuration fields.
"""

from typing import List, Union, Tuple, Dict
from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Checkbox
from gatekit.tui.widgets.selectable_static import SelectableStatic


class MultiSelectField(Container):
    """A widget that allows users to select multiple values from a predefined list using checkboxes.

    This widget is designed for configuration fields where users need to select
    from a constrained set of options (e.g., secret types: aws_access_keys, github_tokens, etc.).
    """

    def __init__(
        self,
        field_name: str,
        options: Union[List[str], List[Tuple[str, str]], Dict[str, str]],
        selected_values: List[str] = None,
        **kwargs,
    ):
        """Initialize the multi-select field.

        Args:
            field_name: Name/ID of the field for form data collection
            options: Available options in one of these formats:
                    - List[str]: Simple list of values (e.g., ["us", "uk"])
                    - List[Tuple[str, str]]: List of (value, display_label) pairs (e.g., [("us", "US")])
                    - Dict[str, str]: Dictionary mapping value -> display_label (e.g., {"us": "US"})
            selected_values: List of currently selected values (using the value, not display label)
        """
        super().__init__(classes="multi-select-field", **kwargs)
        self.field_name = field_name

        # Normalize options to a consistent internal format: Dict[value, display_label]
        if isinstance(options, dict):
            self.option_map = options
        elif isinstance(options, list) and options and isinstance(options[0], tuple):
            self.option_map = dict(options)
        else:
            # List of strings - use the same string for both value and display
            self.option_map = {opt: opt for opt in options}

        self.selected_values = set(selected_values or [])

    def compose(self) -> ComposeResult:
        """Compose the multi-select field with checkboxes for each option."""
        if not self.option_map:
            yield SelectableStatic("No options available", classes="no-options")
            return

        for value, display_label in self.option_map.items():
            is_checked = value in self.selected_values
            yield Checkbox(
                label=display_label,
                value=is_checked,
                id=f"{self.field_name}_option_{value}",
                classes="multi-select-option",
            )

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox state changes to update selected values."""
        checkbox = event.checkbox
        if not checkbox.id:
            return

        # Extract option name from checkbox ID
        option_prefix = f"{self.field_name}_option_"
        if checkbox.id.startswith(option_prefix):
            option = checkbox.id[len(option_prefix) :]

            if checkbox.value:
                self.selected_values.add(option)
                # Remove unchecked class to show X
                checkbox.remove_class("unchecked")
            else:
                self.selected_values.discard(option)
                # Add unchecked class to hide X
                checkbox.add_class("unchecked")

    def on_mount(self) -> None:
        """Called when the widget is mounted - initialize checkbox visibility."""
        # Initialize all checkbox classes based on their current state
        for checkbox in self.query(Checkbox):
            if not checkbox.value:
                # Unchecked state - add unchecked class to hide X
                checkbox.add_class("unchecked")
            # Checked checkboxes don't need the unchecked class (default state)

    def get_selected_values(self) -> List[str]:
        """Get the currently selected values as a list."""
        return list(self.selected_values)

    def set_selected_values(self, values: List[str]) -> None:
        """Set the selected values and update checkbox states."""
        self.selected_values = set(values)

        # Update all checkboxes to match the new selection
        for value in self.option_map.keys():
            try:
                checkbox = self.query_one(
                    f"#{self.field_name}_option_{value}", Checkbox
                )
                is_selected = value in self.selected_values
                checkbox.value = is_selected

                # Update checkbox class for visual styling
                if is_selected:
                    checkbox.remove_class("unchecked")
                else:
                    checkbox.add_class("unchecked")
            except Exception:
                # If checkbox doesn't exist yet, continue
                pass
