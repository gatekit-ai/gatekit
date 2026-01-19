"""Main plugin configuration modal orchestrator.

This module contains the main PluginConfigModal class that orchestrates
all the other components to provide dynamic plugin configuration capabilities.
"""

import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Label
from textual.events import Key
from rich.text import Text

from gatekit.tui.widgets.selectable_static import SelectableStatic
from gatekit.tui.widgets.multi_select_field import MultiSelectField
from gatekit.tui.widgets.file_path_field import FilePathField
from gatekit.plugins.interfaces import PluginInterface
from gatekit.tui.guided_setup.error_handling import EditorOpener

# Validation infrastructure
from gatekit.tui.config_adapter import (
    PluginFormState,
    build_form_state,
    merge_with_passthrough,
    serialize_form_data,
)
from gatekit.tui.utils.schema_cache import get_schema_validator
from gatekit.tui.utils.field_registry import FieldRegistry
from gatekit.tui.utils.error_parser import map_errors_to_widgets
from gatekit.tui.utils.json_pointer import extract_required_leaf_fields
from gatekit.tui.utils.json_form_adapter import JSONFormAdapter


class PluginConfigModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen for configuring plugins dynamically based on their schema."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "save", "OK", show=True),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]

    CSS = """
    PluginConfigModal {
        align: center middle;
    }
    
    PluginConfigModal > .dialog {
        align: center middle;
    }
    
    .dialog {
        width: 90;
        max-width: 100;
        height: 90%;
        max-height: 90%;
        background: $surface;
        border: heavy $primary;
        padding: 1;
    }
    
    .title {
        text-align: center;
        margin-bottom: 1;
        color: $primary;
        text-style: bold;
    }
    
    .form-content {
        height: 1fr;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
        margin-bottom: 1;
    }
    
    .field-label {
        margin-top: 1;
        margin-bottom: 0;
        height: auto;
        text-style: bold;
        color: $text;
    }
    
    .field-description {
        height: auto;
    }
    
    .button-row {
        dock: bottom;
        height: 3;
        layout: horizontal;
        align: center middle;
        padding: 0 1;
        background: $surface;
    }
    
    .button-row Button {
        margin: 0 1;
    }
    
    /* Inline checkbox styling - no borders unless focused */
    Checkbox.inline-checkbox {
        height: 3;
        margin-top: 0;
        margin-bottom: 0;
        background: transparent;
        color: $text;
        border: solid transparent;
    }

    Checkbox.inline-checkbox > .toggle--button {
        background: $surface-lighten-2;
        color: $text;
    }

    Checkbox.inline-checkbox > .toggle--label {
        color: $text;
        padding-left: 1;
    }
    
    Checkbox.inline-checkbox:focus {
        background: $surface-lighten-1;
        border: solid $primary;
    }
    
    /* Improve visibility of non-focused form controls */
    Input {
        height: auto;
        background: $surface-lighten-1;
        border: solid $surface-lighten-3;
        color: $text;
    }
    
    Input:focus {
        background: $surface-lighten-2;
        border: solid $primary;
    }
    
    /* Make integer and number inputs narrower */
    Input.integer-input, Input.number-input {
        width: 20;
        max-width: 30;
    }
    
    /* Validation feedback styling - only show invalid state */
    Input.-invalid {
        border: heavy $error;
        background: $surface-lighten-1;
    }
    
    /* Style the inner SelectCurrent display component */
    Select {
        height: auto;
    }
    
    SelectCurrent {
        background: $surface-lighten-1;
        color: $text;
        border: $surface-lighten-3;
    }
    
    /* Focused state for SelectCurrent */
    Select:focus > SelectCurrent {
        background: $surface-lighten-2;
        border: solid $primary;
    }
    
    /* Style the dropdown overlay for consistency */
    Select > SelectOverlay {
        background: $surface-lighten-1;
        border: solid $surface-lighten-3;
    }
    
    /* Override default Checkbox styling for better dark theme visibility */
    Checkbox .toggle--button {
        background: $surface-lighten-3;
    }
    
    Checkbox .toggle--button:hover {
        background: $surface-lighten-2;
    }
    
    /* Hide X character for unchecked checkboxes */
    Checkbox.unchecked .toggle--button {
        color: $surface-lighten-3;
    }
    
    /* Nested object container styling */
    .nested-object-container {
        height: auto;
        margin-left: 0;
        margin-top: 1;
        margin-bottom: 1;
        margin-right: 1;
        padding: 1 1;
        border: round $surface-lighten-2;
        border-title-color: $text;
        border-title-style: bold;
        background: transparent;
    }

    /* Framework fields container (enabled, critical, priority) */
    .framework-fields-container {
        height: auto;
        margin-top: 0;
        margin-bottom: 1;
        margin-right: 1;
        padding: 1 1;
        border: round $surface-lighten-2;
        border-title-color: $text;
        border-title-style: bold;
        background: transparent;
    }

    .nested-field-label {
        margin-top: 1;
        margin-bottom: 0;
        text-style: bold;
        color: $text;
    }
    
    /* MultiSelectField styling */
    .multi-select-field {
        height: auto;
        margin-top: 1;
        margin-bottom: 0;
        padding-left: 1;
        background: transparent;
        border: none;
    }
    
    .multi-select-option {
        margin: 0;
        margin-bottom: 1;
        padding: 0;
        background: transparent;
        color: $text;
        border: none;
        outline: none;
    }
    
    .multi-select-option:focus {
        background: $surface-lighten-1;
    }
    
    /* Override default Checkbox styling in multi-select context */
    .multi-select-field Checkbox .toggle--button {
        background: $surface-lighten-3;
    }
    
    .multi-select-field Checkbox .toggle--button:hover {
        background: $surface-lighten-2;
    }
    
    /* Hide X character for unchecked checkboxes in multi-select */
    .multi-select-field Checkbox.unchecked .toggle--button {
        color: $surface-lighten-3;
    }
    
    .no-options {
        color: $text-muted;
        text-style: italic;
        margin: 1 0;
    }
    
    .field-error {
        color: $error;
        margin-top: 0;
        margin-bottom: 1;
        text-style: italic;
        padding-left: 1;
    }
    
    /* Disabled checkbox styling */
    Checkbox:disabled {
        opacity: 0.5;
        color: $text-disabled;
    }
    
    Checkbox:disabled .toggle--button {
        background: $surface-lighten-1;
        color: $text-disabled;
    }
    
    Checkbox.disabled-checkbox {
        opacity: 0.5;
        color: $text-disabled;
    }
    
    Checkbox.disabled-checkbox .toggle--button {
        background: $surface-lighten-1;
        color: $text-disabled;
    }

    /* Plugin description styling */
    .plugin-description {
        color: $text-muted;
        text-style: italic;
        height: auto;
        margin-bottom: 1;
    }

    /* Plugin source path row styling */
    .plugin-path-row {
        height: auto;
        align: left middle;
        margin-bottom: 1;
    }

    .plugin-path-combined {
        color: $text-muted;
        width: auto;
        height: auto;
    }

    .inline-button {
        width: auto;
        min-width: 0;
        height: 1;
        padding: 0 1;
        margin-left: 1;
    }

    """

    def __init__(
        self,
        plugin_class: Type[PluginInterface],
        handler_slug: str,
        current_config: Dict[str, Any],
        read_only: bool = False,
        show_override_button: bool = False,
        discovery_context: Optional[Dict[str, Any]] = None,
        config_file_path: Optional[Path] = None,
    ):
        """Initialize the plugin configuration modal.

        Args:
            plugin_class: The plugin class to configure
            handler_slug: The handler slug for this plugin (e.g., "basic_pii_filter", "tool_manager")
            current_config: Current configuration values
            read_only: Whether the modal should be read-only
            show_override_button: Whether to show override button for global plugins
            discovery_context: Context for tool discovery (for tool_manager plugin)
            config_file_path: Path to the configuration file (for resolving relative paths)
        """
        super().__init__()
        self.plugin_class = plugin_class
        self.handler_slug = handler_slug
        self._form_state: PluginFormState = build_form_state(
            plugin_class, current_config
        )
        self.current_config = self._form_state.initial_data.copy()
        self.read_only = read_only
        self.show_override_button = show_override_button
        self.discovery_context = discovery_context or {}
        self.config_file_path = config_file_path

        self.json_schema = self._form_state.schema

        self.validator = get_schema_validator()  # Cached singleton
        self.field_registry = FieldRegistry()  # Central field registry
        self.required_fields = extract_required_leaf_fields(self.json_schema)
        self.error_labels = {}  # Widget ID -> error label mapping

        # Build ui_context for form generation
        ui_context: Dict[str, Any] = {}
        if self.discovery_context:
            ui_context["tool_selector"] = {"discovery": self.discovery_context}
        if config_file_path:
            ui_context["config_dir"] = config_file_path.parent

        # Create JSONFormAdapter for form generation
        # Enable framework field grouping for visual separation
        self.form_adapter = JSONFormAdapter(
            self.json_schema,
            self.current_config,
            json_pointer_base="",
            field_registry=self.field_registry,
            ui_context=ui_context if ui_context else None,
            group_framework_fields=True,
        )

        self.validation_errors: List[str] = []

    def compose(self) -> ComposeResult:
        """Compose the modal layout with scrollable content and docked buttons."""
        plugin_name = getattr(
            self.plugin_class, "DISPLAY_NAME", self.plugin_class.__name__
        )

        # Get plugin source file path (may not be available for dynamically loaded plugins)
        try:
            plugin_path = Path(inspect.getfile(self.plugin_class))
        except (TypeError, OSError):
            plugin_path = None

        with Container(classes="dialog"):
            # Fixed title at top
            yield SelectableStatic(f"Configure: {plugin_name}", classes="title")

            # Check if plugin has schema
            if not self.json_schema or not self.form_adapter.can_generate_form():
                yield SelectableStatic(
                    "This plugin does not define a configuration schema."
                )
                yield SelectableStatic(
                    "Configuration must be done manually in the config file."
                )
                yield SelectableStatic("Click OK to close this dialog.")
            else:
                # Scrollable content area for form fields using JSONFormAdapter
                with VerticalScroll(classes="form-content"):
                    # Plugin description (if available)
                    description = getattr(self.plugin_class, "DESCRIPTION", "")
                    if description:
                        yield SelectableStatic(description, classes="plugin-description")

                    # Plugin source path with Open and Copy buttons (only if path is available)
                    if plugin_path:
                        # Display relative path for readability
                        try:
                            display_path = plugin_path.relative_to(Path.cwd())
                        except ValueError:
                            # Path not relative to cwd, try home directory
                            try:
                                display_path = Path("~") / plugin_path.relative_to(Path.home())
                            except ValueError:
                                display_path = plugin_path

                        with Horizontal(classes="plugin-path-row"):
                            # Merge "Source:" and path into single widget for cross-selection
                            source_text = Text()
                            source_text.append("Source:", style="bold")
                            source_text.append(f" {display_path}")
                            yield SelectableStatic(source_text, classes="plugin-path-combined")
                            yield Button(
                                "Open",
                                id="open_plugin_source",
                                variant="default",
                                compact=True,
                                classes="inline-button",
                            )
                            yield Button(
                                "Copy Path",
                                id="copy_plugin_path",
                                variant="default",
                                compact=True,
                                classes="inline-button",
                            )

                    yield from self.form_adapter.generate_form()

            # Fixed buttons docked at bottom
            with Container(classes="button-row"):
                if self.json_schema and self.form_adapter.can_generate_form():
                    if self.read_only:
                        # Read-only mode - show Override and Close buttons
                        if self.show_override_button:
                            yield Button(
                                "Override Global Plugin Config",
                                id="override_btn",
                                variant="warning",
                            )
                        yield Button("Close", id="cancel_btn", variant="primary")
                    else:
                        # Edit mode - show normal buttons
                        yield Button("OK", id="save_btn", variant="primary")
                        yield Button("Cancel", id="cancel_btn")
                else:
                    yield Button("OK", id="cancel_btn", variant="primary")

    @on(Button.Pressed, "#save_btn")
    def on_save_button(self) -> None:
        """Handle OK button press."""
        self._handle_save_action()

    @on(Button.Pressed, "#cancel_btn")
    def on_cancel_button(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    @on(Button.Pressed, "#override_btn")
    def on_override_button(self) -> None:
        """Handle override button press - validate and return form data."""
        # Use same validation/save logic as OK button so user's changes are saved
        self._handle_save_action()

    @on(Button.Pressed, "#open_plugin_source")
    def on_open_plugin_source(self) -> None:
        """Handle Open button press to open plugin source file in editor."""
        try:
            plugin_path = Path(inspect.getfile(self.plugin_class))
        except (TypeError, OSError):
            self.notify("Source file not available", severity="error")
            return

        opener = EditorOpener()
        success, error = opener.open_file(plugin_path)

        if success:
            self.notify(f"Opened {plugin_path.name} in editor")
        else:
            self.notify(error or "Failed to open editor", severity="error")

    @on(Button.Pressed, "#copy_plugin_path")
    def on_copy_plugin_path(self) -> None:
        """Handle Copy button press to copy full plugin path to clipboard."""
        try:
            plugin_path = Path(inspect.getfile(self.plugin_class))
        except (TypeError, OSError):
            self.notify("Source file not available", severity="error")
            return

        from ...clipboard import copy_to_clipboard, is_ssh_session, SSH_CLIPBOARD_HINT, SSH_CLIPBOARD_TOAST_TIMEOUT

        success, error = copy_to_clipboard(self.app, str(plugin_path))
        if success:
            if is_ssh_session():
                self.notify(
                    f"✅ Path copied. Not working? {SSH_CLIPBOARD_HINT}",
                    timeout=SSH_CLIPBOARD_TOAST_TIMEOUT
                )
            else:
                self.notify("📋 Path copied to clipboard")
        else:
            self.notify(error or "Failed to copy to clipboard", severity="error")

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes for inline validation (Phase 3a requirement)."""
        input_widget = event.input
        if not input_widget.id:
            return

        # Get the field info from registry
        field_info = self.field_registry.get_by_widget_id(input_widget.id)
        if not field_info:
            return

        self._validate_input_field(input_widget, field_info)

    def _validate_file_path_field(
        self, file_path_field: FilePathField, field_info: Any
    ) -> None:
        """Validate a FilePathField and show inline errors."""
        field_value = file_path_field.value

        # Check required field validation
        if field_info.required and not field_value:
            self._show_field_error(file_path_field.id, "This field is required")
            return

        # Clear any previous errors
        self._clear_field_error(file_path_field.id)

    @on(FilePathField.Changed)
    def on_file_path_field_changed(self, event: FilePathField.Changed) -> None:
        """Handle file path field changes for inline validation."""
        file_path_field = event.file_path_field
        if not file_path_field.id:
            return

        # Get the field info from registry
        field_info = self.field_registry.get_by_widget_id(file_path_field.id)
        if not field_info:
            return

        self._validate_file_path_field(file_path_field, field_info)

    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key on Input fields.

        For FilePathField inputs, advance focus to next widget outside the
        FilePathField (skipping the Browse button). This provides better UX
        for auditing plugin config modals where the user has finished entering
        the output path and wants to move to the next form control.
        """
        input_widget = event.input

        # Check if this input belongs to a FilePathField
        # FilePathField inputs have IDs like "{field_id}_input"
        if input_widget.id and input_widget.id.endswith("_input"):
            # Check if parent is a FilePathField
            parent = input_widget.parent
            if isinstance(parent, FilePathField):
                event.stop()
                self._navigate_past_file_path_field(parent)

    def _validate_input_field(self, input_widget: Input, field_info: Any) -> None:
        """Validate an Input field and show inline errors."""

        # Validate just this field
        field_value = input_widget.value
        field_schema = field_info.schema

        # Type conversion based on schema
        field_type = field_schema.get("type")
        if field_type == "integer":
            try:
                field_value = int(field_value) if field_value else None
            except ValueError:
                # Show inline error
                self._show_field_error(input_widget.id, "Must be an integer")
                return
        elif field_type == "number":
            try:
                field_value = float(field_value) if field_value else None
            except ValueError:
                # Show inline error
                self._show_field_error(input_widget.id, "Must be a number")
                return

        # Check required field validation
        # For numeric fields, use 'is None' to allow legitimate 0 values
        # For string fields, also check for empty string
        if field_info.required:
            if field_type in ["integer", "number"]:
                if field_value is None:
                    self._show_field_error(input_widget.id, "This field is required")
                    return
            else:
                # String or other types: empty string or None triggers required error
                if field_value is None or field_value == "":
                    self._show_field_error(input_widget.id, "This field is required")
                    return

        # Clear any previous errors
        self._clear_field_error(input_widget.id)

        # Additional validation (min/max, pattern, etc.)
        if field_type in ["integer", "number"]:
            if "minimum" in field_schema and field_value is not None:
                if field_value < field_schema["minimum"]:
                    self._show_field_error(
                        input_widget.id, f"Must be at least {field_schema['minimum']}"
                    )
                    return
            if "maximum" in field_schema and field_value is not None:
                if field_value > field_schema["maximum"]:
                    self._show_field_error(
                        input_widget.id, f"Must be at most {field_schema['maximum']}"
                    )
                    return
        elif field_type == "string":
            if "minLength" in field_schema and field_value:
                if len(field_value) < field_schema["minLength"]:
                    min_len = field_schema['minLength']
                    char_word = "character" if min_len == 1 else "characters"
                    self._show_field_error(
                        input_widget.id,
                        f"Must be at least {min_len} {char_word}",
                    )
                    return
            if "maxLength" in field_schema and field_value:
                if len(field_value) > field_schema["maxLength"]:
                    max_len = field_schema['maxLength']
                    char_word = "character" if max_len == 1 else "characters"
                    self._show_field_error(
                        input_widget.id,
                        f"Must be at most {max_len} {char_word}",
                    )
                    return
            if "pattern" in field_schema and field_value:
                import re

                if not re.match(field_schema["pattern"], field_value):
                    self._show_field_error(
                        input_widget.id,
                        f"Must match pattern: {field_schema['pattern']}",
                    )
                    return

    @on(Select.Changed)
    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select change for inline validation (Phase 3a requirement)."""
        select_widget = event.select
        if not select_widget.id:
            return

        # Get the field info from registry
        field_info = self.field_registry.get_by_widget_id(select_widget.id)
        if not field_info:
            return

        # Validate enum value
        field_value = select_widget.value
        field_schema = field_info.schema

        if "enum" in field_schema:
            if field_value not in field_schema["enum"] and field_value != Select.BLANK:
                self._show_field_error(
                    select_widget.id, f"Invalid option: {field_value}"
                )
                return

        # Check required field validation
        if field_info.required and field_value == Select.BLANK:
            self._show_field_error(select_widget.id, "This field is required")
            return

        # Clear any previous errors
        self._clear_field_error(select_widget.id)

    @on(Checkbox.Changed)
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox state changes to update styling and validate."""
        checkbox = event.checkbox

        if checkbox.value:
            # Checked state - remove unchecked class to show X
            checkbox.remove_class("unchecked")
        else:
            # Unchecked state - add unchecked class to hide X
            checkbox.add_class("unchecked")

        # Inline validation for checkbox (Phase 3a requirement)
        if checkbox.id:
            field_info = self.field_registry.get_by_widget_id(checkbox.id)
            # For boolean fields, both true and false are valid values
            # A checkbox always has a value (true or false), so it can never be "missing"
            # Therefore, we should never show "This field is required" for checkboxes
            if field_info:
                # Always clear any errors for checkboxes since they always have valid values
                self._clear_field_error(checkbox.id)

    def _show_field_error(self, widget_id: str, error_message: str) -> None:
        """Show an inline error message for a field."""
        # Check if widget_id is empty - this can happen when validation fails
        # but the error mapper can't determine which widget caused the error
        if not widget_id:
            # Show a general error notification instead
            self.app.notify(
                f"Validation error: {error_message}",
                severity="error",
                title="Configuration Error",
            )
            return

        # Create error label ID
        error_label_id = f"{widget_id}_error"

        # Try to find existing error label
        try:
            error_label = self.query_one(f"#{error_label_id}", Label)
            error_label.update(error_message)
        except Exception:
            # Create new error label if it doesn't exist
            try:
                widget = self.query_one(f"#{widget_id}")
                if widget:
                    # Create error label
                    error_label = Label(
                        error_message, id=error_label_id, classes="field-error"
                    )
                    # Insert after the widget
                    widget.parent.mount(error_label, after=widget)
            except Exception:
                # If we can't find the widget, show a general error
                self.app.notify(
                    f"Validation error: {error_message}",
                    severity="error",
                    title="Configuration Error",
                )
                return

        # Store error for tracking
        self.error_labels[widget_id] = error_message

    def _clear_field_error(self, widget_id: str) -> None:
        """Clear any error messages for a field."""
        if widget_id in self.error_labels:
            del self.error_labels[widget_id]

        # Remove error label widget
        error_label_id = f"{widget_id}_error"
        try:
            error_label = self.query_one(f"#{error_label_id}", Label)
            error_label.remove()
        except Exception:
            pass  # Label doesn't exist, nothing to remove

    def on_mount(self) -> None:
        """Called when the modal is mounted - initialize checkbox visibility and set initial focus."""
        # Initialize all checkbox classes based on their current state
        for checkbox in self.query(Checkbox):
            if not checkbox.value:
                # Unchecked state - add unchecked class to hide X
                checkbox.add_class("unchecked")
            # Checked checkboxes don't need the unchecked class (default state)

        # Set initial focus using call_after_refresh to ensure UI is fully rendered
        self.call_after_refresh(self._set_initial_focus_sync)

    def action_save(self) -> None:
        """Handle Ctrl+S shortcut."""
        if self.json_schema:  # Only allow OK if we have a schema
            self._handle_save_action()

    def on_key(self, event: Key) -> None:
        """Handle key events in the modal."""
        # Debug logging for key events in modal
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_user_input(
                input_type="keypress",
                key=event.key,
                screen=self,
                widget=self.focused,
                screen_name=type(self).__name__,
                focused_widget=type(self.focused).__name__ if self.focused else None,
                modal_context="plugin_config",
            )

        # Check if a Select dropdown overlay is currently focused
        # When a Select dropdown is open, focus moves to a SelectOverlay widget
        # We should let it handle its own arrow key navigation
        if self.focused and type(self.focused).__name__ == "SelectOverlay":
            return  # Let the SelectOverlay handle dropdown navigation

        # Handle arrow key navigation between form controls
        if event.key == "up":
            self._navigate_to_previous_widget()
            event.stop()  # Prevent VerticalScroll from handling the key
        elif event.key == "down":
            self._navigate_to_next_widget()
            event.stop()  # Prevent VerticalScroll from handling the key
        # Handle PageUp/PageDown for scrolling content
        elif event.key == "pageup":
            try:
                scroll_container = self.query_one(".form-content", VerticalScroll)
                scroll_container.scroll_page_up()
                event.stop()
            except Exception:
                pass
        elif event.key == "pagedown":
            try:
                scroll_container = self.query_one(".form-content", VerticalScroll)
                scroll_container.scroll_page_down()
                event.stop()
            except Exception:
                pass

    def action_cancel(self) -> None:
        """Handle Escape key press to cancel modal."""
        self.dismiss(None)

    def action_page_up(self) -> None:
        """Scroll page up (no-op, handled in on_key)."""
        pass

    def action_page_down(self) -> None:
        """Scroll page down (no-op, handled in on_key)."""
        pass

    def _get_handler_name(self) -> str:
        """Get the handler name for the plugin class.

        Returns the handler slug that was passed during initialization.
        """
        return self.handler_slug

    def _handle_save_action(self) -> None:
        """Handle the OK action with validation."""
        # Check for existing inline validation errors before proceeding
        # These are set by field-level validation (blur handlers) and must be resolved
        if self.error_labels:
            # There are visible inline errors - don't dismiss
            # Notify user that they need to fix the errors
            self.app.notify(
                "Please fix the validation errors before saving",
                severity="warning",
            )
            return

        # Also check for errors in ToolSelectionField widgets
        from gatekit.tui.widgets.tool_selection_field import ToolSelectionField
        for tool_field in self.query(ToolSelectionField):
            if tool_field.has_validation_errors():
                self.app.notify(
                    "Please fix the validation errors before saving",
                    severity="warning",
                )
                return

        # Collect current form data using JSONFormAdapter
        raw_form_data = self.form_adapter.get_form_data()
        serialized_config = serialize_form_data(self._form_state, raw_form_data)

        # Get handler name for validation
        handler_name = self._get_handler_name()

        # Use NEW JSON Schema validation (don't add handler field - schema doesn't expect it)
        validation_errors = []
        try:
            errors = self.validator.validate(handler_name, serialized_config)
            validation_errors = errors if errors else []
        except Exception as e:
            # Log validation exception for debugging
            self.app.log.exception(f"Validation error: {e}")
            validation_errors = [str(e)]

        if validation_errors:
            # Map errors to widgets using error parser and field registry
            widget_errors = map_errors_to_widgets(
                validation_errors, self.field_registry
            )

            # Clear all previous errors first
            for widget_id in list(self.error_labels.keys()):
                self._clear_field_error(widget_id)

            # Display errors inline (Phase 3a requirement)
            for widget_id, error_msgs in widget_errors.items():
                # Show the first error message for each field
                if error_msgs:
                    self._show_field_error(widget_id, error_msgs[0])

            # Store validation errors for display
            self.validation_errors = validation_errors
        else:
            final_config = merge_with_passthrough(
                self._form_state, serialized_config
            )
            self.dismiss(final_config)

    def update_discovery(self, discovery: Dict[str, Any]) -> None:
        """Update discovery data for tool selection fields.
        
        This is called when discovery data becomes available after the modal is opened.
        Typically happens when using --open-plugin flag on startup.
        """
        self.discovery_context = discovery
        
        # Update all ToolSelectionField widgets with new discovery data
        from gatekit.tui.widgets.tool_selection_field import ToolSelectionField
        
        for tool_field in self.query(ToolSelectionField):
            tool_field.update_discovery(discovery)

    def _set_initial_focus_sync(self) -> None:
        """Set initial focus to the first form control."""
        # Disable can_focus on all VerticalScroll containers to prevent them from capturing focus
        for scroll in self.query(VerticalScroll):
            scroll.can_focus = False

        # Find the first focusable form control
        focusable_widgets = [
            *self.query(Checkbox),
            *self.query(Input),
            *self.query(Select),
            *self.query(MultiSelectField),
            *self.query(Button),
        ]

        # Filter to only widgets that can receive focus
        focusable_widgets = [
            w for w in focusable_widgets if getattr(w, "can_focus", False)
        ]

        if focusable_widgets:
            # Focus the first widget
            focusable_widgets[0].focus()

    def _get_focusable_widgets(self):
        """Get all focusable widgets in the modal in order."""
        focusable = []

        # Get all form controls in document order
        for widget in self.query("Checkbox, Input, Select, MultiSelectField, Button"):
            if getattr(widget, "can_focus", False):
                focusable.append(widget)

        return focusable

    def _navigate_to_next_widget(self):
        """Navigate to the next focusable widget."""
        focusable = self._get_focusable_widgets()
        if not focusable:
            return

        current = self.focused
        if current in focusable:
            current_index = focusable.index(current)
            next_index = (current_index + 1) % len(focusable)
            focusable[next_index].focus()
        elif focusable:
            focusable[0].focus()

    def _navigate_past_file_path_field(self, file_path_field: FilePathField):
        """Navigate to the next focusable widget that is not inside the FilePathField.

        This is used when Enter is pressed on a FilePathField's input to skip
        past the Browse button and move to the next form control.
        """
        focusable = self._get_focusable_widgets()
        if not focusable:
            return

        # Find the first widget that is not a descendant of the FilePathField
        current = self.focused
        if current in focusable:
            current_index = focusable.index(current)
            # Start looking from the next widget
            for i in range(1, len(focusable)):
                next_index = (current_index + i) % len(focusable)
                next_widget = focusable[next_index]
                # Check if this widget is inside the FilePathField
                if not self._is_descendant_of(next_widget, file_path_field):
                    next_widget.focus()
                    return
        # Fallback: just focus the first widget
        elif focusable:
            focusable[0].focus()

    def _is_descendant_of(self, widget, ancestor) -> bool:
        """Check if widget is a descendant of ancestor."""
        current = widget.parent
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False

    def _navigate_to_previous_widget(self):
        """Navigate to the previous focusable widget."""
        focusable = self._get_focusable_widgets()
        if not focusable:
            return

        current = self.focused
        if current in focusable:
            current_index = focusable.index(current)
            prev_index = (current_index - 1) % len(focusable)
            focusable[prev_index].focus()
        elif focusable:
            focusable[-1].focus()
