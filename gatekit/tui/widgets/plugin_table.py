"""Plugin table widget that mimics DataTable appearance but uses real widgets."""

from typing import List, Dict, Any, Optional
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import Static
from textual.message import Message
from textual import on
from textual.events import Click, Resize
from gatekit.tui.constants import (
    PLUGIN_COL_ID_NAME,
    PLUGIN_COL_ID_SCOPE,
    PLUGIN_COL_ID_PRIORITY,
    GLOBAL_SCOPE,
)

from rich.text import Text

from gatekit.tui.widgets.ascii_checkbox import ASCIICheckbox
from gatekit.tui.widgets.selectable_static import SelectableStatic


# Removed ActionButton class - using Static like global plugins


class PluginActionClick(Message):
    """Message sent when a plugin action is clicked."""

    bubble = True  # Ensure this message bubbles up the widget tree

    def __init__(self, handler: str, plugin_type: str, action: str, scope: str) -> None:
        self.handler = handler
        self.plugin_type = plugin_type
        self.action = action
        self.scope = scope  # "_global" or server name
        super().__init__()


class PluginToggle(Message):
    """Message sent when a plugin checkbox is toggled."""

    bubble = True  # Ensure this message bubbles up the widget tree

    def __init__(self, handler: str, plugin_type: str, enabled: bool, scope: str) -> None:
        self.handler = handler
        self.plugin_type = plugin_type
        self.enabled = enabled
        self.scope = scope  # "_global" or server name
        super().__init__()


class HeaderClick(Message):
    """Message sent when a column header is clicked for sorting.

    Uses stable column IDs so label text can change without breaking logic.
    """

    def __init__(self, column_id: str, label: str | None = None) -> None:
        self.column_id = column_id
        # Optional human-readable label for logging/debugging
        self.label = label
        # Back-compat: provide `column` attribute if any listeners still read it
        self.column = column_id
        super().__init__()


class PluginRowWidget(Horizontal):
    """Individual plugin row widget."""

    DEFAULT_CSS = """
    PluginRowWidget {
        height: 1;
        width: 100%;
        align: left middle;
        padding: 0;
        margin: 0;
    }

    PluginRowWidget:hover {
        background: $boost;
    }

    PluginRowWidget > ASCIICheckbox {
        width: 3;
        min-width: 3;
        margin: 0 1;
    }

    PluginRowWidget > ASCIICheckbox:hover {
        background: $primary;
    }

    PluginRowWidget > ASCIICheckbox:disabled {
        opacity: 0.5;
    }

    PluginRowWidget > ASCIICheckbox:disabled:hover {
        background: transparent;
    }

    PluginRowWidget > .plugin-name {
        /* width: set programmatically */
        margin: 0 2 0 1;
        content-align: left middle;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Match global panels: dim name when disabled, normal/bold when enabled */
    PluginRowWidget.enabled > .plugin-name {
        color: $text;
        text-style: bold;
    }

    PluginRowWidget.disabled > .plugin-name {
        color: $text-muted;
        text-style: none;
    }

    PluginRowWidget > .plugin-status {
        /* width: set programmatically */
        /* display: set programmatically (none if hidden) */
        margin: 0 2 0 1;
        content-align: left middle;
        color: $text-muted;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    PluginRowWidget > .plugin-status.clickable {
        color: $text;
    }

    PluginRowWidget > .plugin-status.clickable:hover {
        color: $primary;
        background: $boost;
    }

    PluginRowWidget > .plugin-status.clickable:focus {
        color: $primary;
        background: $accent;
        text-style: bold;
    }

    PluginRowWidget > .plugin-priority {
        /* width: set programmatically */
        /* display: set programmatically (none if hidden) */
        margin: 0 2 0 1;
        content-align: center middle;
    }

    PluginRowWidget > .plugin-actions {
        /* width: auto (buttons size to content) */
        margin: 0 1;
        align: left middle;
    }

    PluginRowWidget .action-button {
        width: auto;
        min-width: 10;
        margin: 0 1 0 0;
        padding: 0 2;
        content-align: center middle;
        background: $secondary;
        color: $text;
    }

    PluginRowWidget .action-button:hover {
        background: $primary;
        color: $background;
    }

    PluginRowWidget .action-button:focus {
        background: $accent;
        color: $background;
        text-style: bold;
    }

    PluginRowWidget .action-button-secondary {
        width: auto;
        min-width: 10;
        margin: 0 1 0 0;
        padding: 0 2;
        content-align: center middle;
        background: $panel;
        color: $text;
    }

    PluginRowWidget .action-button-secondary:hover {
        background: $primary-darken-1;
        color: $background;
    }

    PluginRowWidget .action-button-secondary:focus {
        background: $accent-darken-1;
        color: $background;
        text-style: bold;
    }
    """

    def __init__(
        self,
        plugin_data: Dict[str, Any],
        plugin_type: str,
        scope: str,
        show_priority: bool = True,
        show_actions: bool = False,
        name_width: int = 25,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.plugin_data = plugin_data
        self.plugin_type = plugin_type
        self.scope = scope  # "_global" or server name
        self.show_priority = show_priority
        self.show_actions = show_actions
        self.name_width = name_width
        self.can_focus = False

    def compose(self) -> ComposeResult:
        # Debug logging
        try:
            from ..debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "PLUGIN_ROW_COMPOSE",
                    screen=None,
                    context={
                        "handler": self.plugin_data["handler"],
                        "plugin_type": self.plugin_type,
                        "enabled": self.plugin_data.get("enabled", False),
                        "inheritance": self.plugin_data.get("inheritance", ""),
                    },
                )
        except Exception:
            logger = None

        # Apply styling based on plugin enabled state (for dimming when unchecked)
        enabled_class = (
            "enabled" if self.plugin_data.get("enabled", False) else "disabled"
        )
        self.remove_class("enabled")
        self.remove_class("disabled")
        self.add_class(enabled_class)

        # Checkbox - disable if inherited from enabled global plugin
        inheritance = self.plugin_data.get("inheritance", "")
        global_enabled = self.plugin_data.get("global_enabled", False)
        is_inherited_from_global = (inheritance == "inherited" and global_enabled)

        checkbox = ASCIICheckbox(
            "",
            value=self.plugin_data.get("enabled", False),
            id=f"checkbox_{self.plugin_data['handler']}",
            classes="plugin-checkbox",
            disabled=is_inherited_from_global,
            tooltip="Locked by global config. To override global setting, use Configure button." if is_inherited_from_global else None,
        )
        yield checkbox

        # Name - use SelectableStatic to allow text selection and copy
        display_name = self.plugin_data.get("display_name", self.plugin_data["handler"])
        name_text = (
            f"⚠ {display_name} (not found)"
            if self.plugin_data.get("is_missing")
            else display_name
        )
        name_widget = SelectableStatic(
            name_text, classes="plugin-name", id=f"name_{self.plugin_data['handler']}"
        )
        name_widget.can_focus = False

        # Width will be set programmatically via apply_column_widths()

        # Add tooltip since name can truncate
        name_widget.tooltip = name_text

        yield name_widget

        # Scope/status text
        # Global plugins: use 'status' field (plugin-provided via describe_status)
        # Server plugins: use 'scope' field (TUI-generated scope/inheritance info)
        if self.scope == "_global":
            status_or_scope_text = self.plugin_data.get("status", "")
        else:
            status_or_scope_text = self.plugin_data.get("scope", "")

        # Check if status represents a clickable file path
        status_file_path = self.plugin_data.get("status_file_path")
        status_classes = "plugin-status"
        if status_file_path:
            status_classes += " clickable"
            # Use Text object with styling (not string markup) for proper SelectableStatic _text_content
            status_display_text = Text(status_or_scope_text)
            status_display_text.stylize("underline")
        else:
            status_display_text = status_or_scope_text

        # Use SelectableStatic to enable text selection and copy
        status_widget = SelectableStatic(
            status_display_text,
            classes=status_classes,
            id=f"status_{self.plugin_data['handler']}",
        )

        # Make focusable if clickable
        status_widget.can_focus = bool(status_file_path)

        # Add tooltip - show "Click to open" hint for clickable paths
        if status_or_scope_text:
            if status_file_path:
                status_widget.tooltip = f"{status_or_scope_text}\n(Click to open in editor, drag to select)"
            else:
                status_widget.tooltip = status_or_scope_text
        yield status_widget

        # Priority
        if self.show_priority:
            priority = self.plugin_data.get("priority", 50)
            priority_widget = Static(
                str(priority),
                classes="plugin-priority",
                id=f"priority_{self.plugin_data['handler']}",
            )
            priority_widget.can_focus = False
            yield priority_widget

        # Optional actions (hidden by default)
        if self.show_actions:
            button = Static(
                "Configure",
                classes="plugin-action action-button",
                id=f"action_configure_{self.plugin_data['handler']}",
            )
            button.can_focus = True
            yield button

        inheritance = self.plugin_data.get("inheritance", "")
        global_enabled = self.plugin_data.get("global_enabled", False)
        if (
            self.show_actions
            and global_enabled
            and inheritance
            in [
                "overrides",
                "overrides (config)",
                "overrides (disables)",
                "disabled",
                "server-only",
            ]
        ):
            button = Static(
                "Use Global",
                classes="plugin-action action-button-secondary",
                id=f"action_useglobal_{self.plugin_data['handler']}",
            )
            button.can_focus = True
            yield button

    def on_key(self, event) -> None:
        """Handle key events on focusable widgets - just like GlobalPluginItem."""
        # Debug logging
        try:
            from ..debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "PLUGIN_ROW_ON_KEY",
                    screen=self.app.screen if self.app else None,
                    context={
                        "key": event.key,
                        "focused_id": (
                            getattr(self.app.focused, "id", None)
                            if self.app and self.app.focused
                            else None
                        ),
                        "plugin_type": self.plugin_type,
                    },
                )
        except Exception:
            pass

        # Handle Enter and Space keys on action buttons (standard button activation keys)
        if event.key in ("enter", "space"):
            focused_widget = self.app.focused
            if focused_widget and hasattr(focused_widget, "id") and focused_widget.id:
                # Check if it's an action button
                if focused_widget.id.startswith("action_configure_"):
                    handler = focused_widget.id.replace("action_configure_", "")
                    msg = PluginActionClick(handler, self.plugin_data.get("plugin_type", self.plugin_type), "Configure", self.scope)

                    # Log message posting
                    try:
                        if logger:
                            logger.log_event(
                                "PLUGIN_ROW_POSTING_MESSAGE",
                                screen=self.app.screen if self.app else None,
                                context={
                                    "handler": handler,
                                    "action": "Configure",
                                    "msg_class": msg.__class__.__name__,
                                    "scope": self.scope,
                                },
                            )
                    except Exception:
                        pass

                    # Post directly to screen to ensure delivery like checkbox toggles
                    if self.app and self.app.screen:
                        self.app.screen.post_message(msg)
                    else:
                        self.post_message(msg)
                    event.prevent_default()
                    event.stop()
                elif focused_widget.id.startswith("action_useglobal_"):
                    handler = focused_widget.id.replace("action_useglobal_", "")
                    msg = PluginActionClick(handler, self.plugin_data.get("plugin_type", self.plugin_type), "Use Global", self.scope)

                    # Log message posting
                    try:
                        if logger:
                            logger.log_event(
                                "PLUGIN_ROW_POSTING_MESSAGE",
                                screen=self.app.screen if self.app else None,
                                context={
                                    "handler": handler,
                                    "action": "Use Global",
                                    "msg_class": msg.__class__.__name__,
                                    "scope": self.scope,
                                },
                            )
                    except Exception:
                        pass

                    # Post directly to screen to ensure delivery like checkbox toggles
                    if self.app and self.app.screen:
                        self.app.screen.post_message(msg)
                    else:
                        self.post_message(msg)
                    event.prevent_default()
                    event.stop()
                elif focused_widget.id.startswith("status_"):
                    # Handle Enter/Space on clickable status field
                    self._handle_status_click()
                    event.prevent_default()
                    event.stop()

    def on_click(self, event) -> None:
        """Handle click events on the plugin row - just like GlobalPluginItem."""
        # Check if click was on an action button or clickable status
        if hasattr(event.widget, "id") and event.widget.id:
            if event.widget.id.startswith("action_configure_"):
                handler = event.widget.id.replace("action_configure_", "")
                msg = PluginActionClick(handler, self.plugin_data.get("plugin_type", self.plugin_type), "Configure", self.scope)
                # Post directly to screen to ensure delivery like checkbox toggles
                if self.app and self.app.screen:
                    self.app.screen.post_message(msg)
                else:
                    self.post_message(msg)
                try:
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            elif event.widget.id.startswith("action_useglobal_"):
                handler = event.widget.id.replace("action_useglobal_", "")
                msg = PluginActionClick(handler, self.plugin_data.get("plugin_type", self.plugin_type), "Use Global", self.scope)
                # Post directly to screen to ensure delivery like checkbox toggles
                if self.app and self.app.screen:
                    self.app.screen.post_message(msg)
                else:
                    self.post_message(msg)
                try:
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            elif event.widget.id.startswith("status_"):
                # Handle click on clickable status field (e.g., auditing plugin output file)
                self._handle_status_click()
                try:
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass

    def _handle_status_click(self) -> None:
        """Handle click on status field to open file in editor."""
        from pathlib import Path
        from ..guided_setup.error_handling import EditorOpener
        from ..clipboard import copy_to_clipboard, is_ssh_session, SSH_CLIPBOARD_HINT, SSH_CLIPBOARD_TOAST_TIMEOUT

        status_file_path = self.plugin_data.get("status_file_path")
        if not status_file_path:
            return

        file_path = Path(status_file_path)
        opener = EditorOpener()
        success, error = opener.open_file(file_path)

        if success:
            if self.app:
                self.app.notify(f"Opened {file_path.name} in editor")
        else:
            # Editor failed - copy path to clipboard as fallback
            if self.app:
                copy_success, copy_error = copy_to_clipboard(self.app, str(file_path))
                if copy_success:
                    # Use cleaner messages - don't include full path in toast
                    if error and "file not found" in error.lower():
                        reason = "File not found"
                    elif error and "editor not found" in error.lower():
                        reason = "Editor not found"
                    else:
                        reason = error or "Editor not available"

                    if is_ssh_session():
                        self.app.notify(
                            f"{reason}, path copied to clipboard. Not working? {SSH_CLIPBOARD_HINT}",
                            severity="warning",
                            timeout=SSH_CLIPBOARD_TOAST_TIMEOUT
                        )
                    else:
                        self.app.notify(f"{reason}, path copied to clipboard.", severity="warning")
                else:
                    self.app.notify(error or "Failed to open editor", severity="error")

    def on_checkbox_value_changed(self, checkbox_widget, new_value: bool) -> None:
        """Handle checkbox value changes."""
        if (
            hasattr(checkbox_widget, "id")
            and checkbox_widget.id
            and checkbox_widget.id.startswith("checkbox_")
        ):
            # Update local state and CSS classes to reflect dimming immediately
            self.plugin_data["enabled"] = new_value
            self.remove_class("enabled")
            self.remove_class("disabled")
            self.add_class("enabled" if new_value else "disabled")

            # Post toggle message with new value directly to screen
            msg = PluginToggle(self.plugin_data["handler"], self.plugin_data.get("plugin_type", self.plugin_type), new_value, self.scope)
            # Post directly to screen to ensure it gets there
            if self.app and self.app.screen:
                self.app.screen.post_message(msg)
            else:
                self.post_message(msg)

    def apply_column_widths(self, widths: Dict[str, int]) -> None:
        """Apply calculated fixed widths to row columns.

        Args:
            widths: Dictionary of column widths from PluginTableWidget
        """
        try:
            # Checkbox
            checkbox = self.query_one("ASCIICheckbox")
            checkbox.styles.width = widths['checkbox']

            # Name
            name = self.query_one(".plugin-name")
            name.styles.width = widths['name']

            # Status/Scope
            status = self.query_one(".plugin-status")
            if widths['status'] > 0:
                status.styles.width = widths['status']
                status.styles.display = "block"
            else:
                status.styles.display = "none"

            # Priority
            if self.show_priority:
                priority = self.query_one(".plugin-priority")
                if widths['priority'] > 0:
                    priority.styles.width = widths['priority']
                    priority.styles.display = "block"
                else:
                    priority.styles.display = "none"

            # Actions (if shown)
            if self.show_actions:
                # Find the actions container and set its width
                actions_buttons = self.query(".plugin-action")
                if actions_buttons:
                    # The buttons are inside an implicit container created by yielding them sequentially
                    # We need to find the parent container or set width on individual buttons
                    # For now, we'll rely on the actions column having width: auto in CSS
                    # and the parent Horizontal layout will constrain it
                    pass

        except Exception:
            # Widgets may not be composed yet - will be called again
            pass

    # Remove on_key from PluginRowWidget since ActionButton handles its own keyboard events


class PluginTableHeader(Horizontal):
    """Header row for the plugin table."""

    DEFAULT_CSS = """
    PluginTableHeader {
    height: 1;
        width: 100%;
        align: left middle;
        padding: 0;
        margin: 0;
    background: $secondary;
        color: $text;
        text-style: bold;
    }

    PluginTableHeader > .header-checkbox {
        width: 3;
        min-width: 3;
        margin: 0 1;
    }

    PluginTableHeader > .header-name {
        /* width: set programmatically */
        margin: 0 2 0 1;
        content-align: left middle;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    PluginTableHeader > .header-name:hover {
        background: $boost;
    }

    PluginTableHeader > .header-status {
        /* width: set programmatically */
        /* display: set programmatically (none if hidden) */
        margin: 0 2 0 1;
        content-align: left middle;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    PluginTableHeader > .header-status:hover {
        background: $boost;
    }

    PluginTableHeader > .header-priority {
        /* width: set programmatically */
        /* display: set programmatically (none if hidden) */
        margin: 0 2 0 1;
        content-align: center middle;
    }

    PluginTableHeader > .header-priority:hover {
        background: $boost;
    }

    PluginTableHeader > .header-actions {
        /* width: set programmatically */
        margin: 0 1;
        content-align: left middle;
    }
    """

    def __init__(
        self,
        show_priority: bool = True,
        plugin_type: str = "",
        show_actions: bool = False,
        name_width: int = 25,
        **kwargs,
    ):
        """Initialize header.

        Args:
            show_priority: Whether to show priority column
        """
        super().__init__(**kwargs)
        self.show_priority = show_priority
        self.plugin_type = plugin_type
        self.show_actions = show_actions
        self.name_width = name_width

    def compose(self) -> ComposeResult:
        """Compose header widgets."""
        # Debug: trace header composition
        try:
            from ..debug import get_debug_logger  # type: ignore

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TABLE_HEADER_COMPOSE",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "show_priority": self.show_priority,
                        "classes": (
                            list(self.classes) if hasattr(self, "classes") else []
                        ),
                    },
                )
        except Exception:
            pass
        # Determine first column label based on plugin type
        plugin_label_map = {
            "security": "Security Plugins",
            "middleware": "Middleware Plugins",
            "auditing": "Auditing Plugins",
        }
        name_label = plugin_label_map.get((self.plugin_type or "").lower(), "Plugin")

        # Empty space for checkbox column alignment
        checkbox_header = Static("", classes="header-checkbox")
        checkbox_header.can_focus = False  # Headers should not be focusable
        yield checkbox_header

        # Column headers - NOT focusable to avoid navigation issues
        name_header = Static(name_label, classes="header-name")
        name_header.can_focus = False  # Headers should not be focusable

        # Width will be set programmatically via apply_column_widths()

        yield name_header

        status_header = Static("Scope", classes="header-status")
        status_header.can_focus = False  # Headers should not be focusable
        yield status_header

        if self.show_priority:
            priority_header = Static("Priority", classes="header-priority")
            priority_header.can_focus = False  # Headers should not be focusable
            yield priority_header

        # Always include an Actions column cell for alignment, but hide its label when disabled
        actions_label = "Actions" if self.show_actions else ""
        actions_header = Static(actions_label, classes="header-actions")
        actions_header.can_focus = False  # Headers should not be focusable
        yield actions_header

    def apply_column_widths(self, widths: Dict[str, int]) -> None:
        """Apply calculated fixed widths to header columns.

        Args:
            widths: Dictionary of column widths from PluginTableWidget
        """
        try:
            # Checkbox spacer
            checkbox = self.query_one(".header-checkbox")
            checkbox.styles.width = widths['checkbox']

            # Name column
            name = self.query_one(".header-name")
            name.styles.width = widths['name']

            # Status/Scope column
            status = self.query_one(".header-status")
            if widths['status'] > 0:
                status.styles.width = widths['status']
                status.styles.display = "block"
            else:
                status.styles.display = "none"  # Hide if no space

            # Priority column
            if self.show_priority:
                priority = self.query_one(".header-priority")
                if widths['priority'] > 0:
                    priority.styles.width = widths['priority']
                    priority.styles.display = "block"
                else:
                    priority.styles.display = "none"

            # Actions column
            actions = self.query_one(".header-actions")
            actions.styles.width = widths['actions']

        except Exception:
            # Widgets may not be composed yet - will be called again
            pass

    async def on_mount(self) -> None:
        """Log when header is mounted to help diagnose visibility issues."""
        try:
            from ..debug import get_debug_logger  # type: ignore

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TABLE_HEADER_MOUNTED",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "size": (
                            self.size.width if self.size else None,
                            self.size.height if self.size else None,
                        ),
                    },
                )
        except Exception:
            pass

    async def on_resize(self, event: Resize) -> None:
        """Log real size after layout; on_mount may not have size yet."""
        try:
            from ..debug import get_debug_logger  # type: ignore

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TABLE_HEADER_RESIZED",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "width": event.width,
                        "height": event.height,
                    },
                )
        except Exception:
            pass

    async def on_click(self, event: Click) -> None:
        """Handle clicks on headers."""
        # Get the widget that was clicked
        target = self.app.get_widget_at(*event.screen_offset)

        if isinstance(target, Static):
            if "header-name" in target.classes:
                self.post_message(HeaderClick(PLUGIN_COL_ID_NAME, label="Plugin Name"))
            elif "header-status" in target.classes:
                self.post_message(HeaderClick(PLUGIN_COL_ID_SCOPE, label="Scope"))
            elif "header-priority" in target.classes:
                self.post_message(HeaderClick(PLUGIN_COL_ID_PRIORITY, label="Priority"))


class PluginTableWidget(Container):
    """Plugin table widget (DataTable does not support themes)"""

    # NOTE: Prior revisions gave PluginTableWidget a dynamic height clamp
    # similar to the global plugin pane (min-height 5, max_visible_rows, etc.)
    # and wrapped the body in a nested VerticalScroll. That approach kept the
    # widget compact but created large voids in the per-server panel once only
    # a handful of rows were present. The code that implemented that behavior
    # has been removed below; if we ever need to restore the dynamic clamp, see
    # the commented block at the end of this class for reference.

    DEFAULT_CSS = """
    PluginTableWidget {
        width: auto;
        height: auto;
        margin: 0 1 1 1;
        border: solid $secondary;
        background: $surface;
    }

    PluginTableWidget:focus-within {
        border: solid $accent;
    }

    PluginTableWidget > .table-scroll {
        height: auto;
        overflow: hidden;
    }

    PluginTableWidget .empty-state {
        height: 5;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
        margin: 1;
    }

    /* Global display mode - cleaner look */
    PluginTableWidget.global-mode {
        border: none;
        margin: 0;
    }

    PluginTableWidget.global-mode PluginRowWidget {
        height: 1;  /* Tighter rows */
    }

    PluginTableWidget.global-mode PluginRowWidget > ASCIICheckbox {
        margin: 0 1 0 0;  /* No left margin for global tables */
    }

    PluginTableWidget.global-mode PluginRowWidget .action-button {
        margin: 0;  /* No right margin for global tables */
    }

    PluginTableWidget.global-mode PluginTableHeader > .header-checkbox {
        margin: 0 1 0 0;  /* No left margin for global tables */
    }
    """

    # Height configuration
    DEFAULT_MAX_VISIBLE_ROWS = 5
    # Header + borders padding to compute total height from content rows
    _HEIGHT_PADDING = 3
    _EMPTY_HEIGHT = 5

    # Column width constraints
    _NAME_MIN = 15
    _NAME_MAX = 35
    _STATUS_MIN = 10
    _STATUS_MAX = 30

    def __init__(
        self,
        plugin_type: str,
        server_name: str,
        plugins_data: List[Dict[str, Any]] = None,
        show_priority: bool = True,
        show_header: bool = True,
        max_visible_rows: int = DEFAULT_MAX_VISIBLE_ROWS,
        **kwargs,
    ):
        """Initialize plugin table widget.

        Args:
            plugin_type: Type of plugins (security/middleware/auditing)
            server_name: Name of the server (or GLOBAL_SCOPE for global plugins)
            plugins_data: List of plugin data dictionaries
            show_priority: Whether to show priority column
            show_header: Whether to show table header
            max_visible_rows: Maximum number of visible rows before scrolling
        """
        super().__init__(**kwargs)
        self.plugin_type = plugin_type
        self.server_name = server_name
        self.plugins_data = plugins_data or []
        self.show_priority = show_priority
        self.show_header = show_header
        self.sort_column = None  # stores column ID
        self.sort_descending = False
        self.can_focus = False  # The table widget itself should not be focusable
        self.max_visible_rows = max_visible_rows

        # Calculate name column width based on data
        self.name_width = self._calculate_name_width()

        # Column width management for fixed-width layout
        self._column_widths: Optional[Dict[str, int]] = None
        self._last_container_width: int = 0

        # Add CSS class for global mode styling
        if server_name == GLOBAL_SCOPE:
            self.add_class("global-mode")

    def _calculate_name_width(self) -> int:
        """Calculate optimal name column width based on plugin data."""
        if not self.plugins_data:
            return 25  # Default width

        # Calculate max length accounting for "⚠ " prefix and " (not found)" suffix
        max_name_len = 0
        for p in self.plugins_data:
            display_name = p.get("display_name", p.get("handler", ""))
            if p.get("is_missing"):
                # "⚠ {name} (not found)" = 2 + name + 12
                name_len = len(display_name) + 14
            else:
                name_len = len(display_name)
            max_name_len = max(max_name_len, name_len)

        # Add padding and cap at reasonable max
        return min(max_name_len + 2, 35)

    def _get_max_name_width(self) -> int:
        """Calculate the maximum width needed for plugin names based on actual data.

        Reads from self.plugins_data instead of rendered widgets, since widgets
        may not be populated yet when this is called.

        Returns:
            Maximum length of plugin names in current data
        """
        max_width = 0
        measurements = []

        try:
            from ..debug import get_debug_logger
            logger = get_debug_logger()
        except Exception:
            logger = None

        try:
            # Measure header label based on plugin type
            plugin_label_map = {
                "security": "Security Plugins",
                "middleware": "Middleware Plugins",
                "auditing": "Auditing Plugins",
            }
            header_text = plugin_label_map.get(self.plugin_type.lower(), "Plugin")
            header_len = len(header_text)
            max_width = max(max_width, header_len)
            measurements.append(f"Header: '{header_text}' = {header_len}")

            # Measure plugin names from data (not from widgets which may not be populated)
            for plugin_data in self.plugins_data:
                display_name = plugin_data.get("display_name", plugin_data.get("handler", ""))

                # Account for "⚠ " prefix and " (not found)" suffix for missing plugins
                if plugin_data.get("is_missing"):
                    name_text = f"⚠ {display_name} (not found)"
                else:
                    name_text = display_name

                name_len = len(name_text)
                max_width = max(max_width, name_len)
                measurements.append(f"Data: '{name_text}' = {name_len}")

        except Exception as e:
            # Fallback if data access fails
            if logger:
                logger.log_event(
                    "NAME_WIDTH_MEASUREMENT_FAILED",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={"error": str(e)}
                )
            return 15  # Default minimum

        result = max_width if max_width > 0 else 15

        if logger:
            logger.log_event(
                "NAME_WIDTH_MEASURED",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "measurements": measurements,
                    "max_width": result,
                }
            )

        return result

    def _get_max_status_width(self) -> int:
        """Calculate the maximum width needed for status/scope text based on actual data.

        Reads from self.plugins_data instead of rendered widgets, since widgets
        may not be populated yet when this is called.

        Returns:
            Maximum length of status/scope text in current data
        """
        max_width = 0
        measurements = []

        try:
            from ..debug import get_debug_logger
            logger = get_debug_logger()
        except Exception:
            logger = None

        try:
            # Measure status/scope from plugin data (not from widgets which may not be populated)
            # Global tables use "status" field, server tables use "scope" field
            field_name = "status" if self.server_name == GLOBAL_SCOPE else "scope"
            for plugin_data in self.plugins_data:
                status_text = plugin_data.get(field_name, "")
                status_len = len(status_text)
                max_width = max(max_width, status_len)
                measurements.append(f"Data[{field_name}]: '{status_text}' = {status_len}")

        except Exception as e:
            # Fallback if data access fails
            if logger:
                logger.log_event(
                    "STATUS_WIDTH_MEASUREMENT_FAILED",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={"error": str(e)}
                )
            return 10  # Default minimum

        result = max_width if max_width > 0 else 10

        if logger:
            logger.log_event(
                "STATUS_WIDTH_MEASURED",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "measurements": measurements,
                    "max_width": result,
                }
            )

        return result

    def _calculate_content_based_widths(
        self,
        container_width: int,
        max_name_width: int,
        max_status_width: int,
        checkbox_width: int,
        actions_width: int,
        priority_width: int,
        border_padding: int,
        total_margins: int,
    ) -> Dict[str, int]:
        """Calculate column widths based on content size with container constraint.

        Args:
            container_width: Maximum width available
            max_name_width: Maximum width needed for name column
            max_status_width: Maximum width needed for status column
            checkbox_width: Fixed width for checkbox column
            actions_width: Fixed width for actions column
            priority_width: Fixed width for priority column
            border_padding: Border overhead
            total_margins: Total margin space

        Returns:
            Dictionary mapping column names to integer widths
        """
        try:
            from ..debug import get_debug_logger
            logger = get_debug_logger()
        except Exception:
            logger = None

        # Calculate available space
        available = container_width - border_padding - total_margins

        # Calculate ideal widths based on content
        ideal_name_min_or_measured = max(self._NAME_MIN, max_name_width)
        ideal_name = min(self._NAME_MAX, ideal_name_min_or_measured)

        ideal_status_min_or_measured = max(self._STATUS_MIN, max_status_width)
        ideal_status = min(self._STATUS_MAX, ideal_status_min_or_measured)

        # Priority column - always show for non-auditing plugins
        priority = priority_width if self.show_priority else 0

        # Calculate total needed
        fixed_columns = checkbox_width + actions_width + priority
        ideal_total = fixed_columns + ideal_name + ideal_status

        ideal_fits = ideal_total <= available

        if logger:
            logger.log_event(
                "SERVER_WIDTH_CALC_START",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "INPUTS": {
                        "container_width": container_width,
                        "border_padding": border_padding,
                        "total_margins": total_margins,
                        "available_formula": f"{container_width} - {border_padding} - {total_margins}",
                        "available": available,
                        "measured_max_name_width": max_name_width,
                        "measured_max_status_width": max_status_width,
                    },
                    "IDEAL_CALC": {
                        "name_min_or_measured_formula": f"max({self._NAME_MIN}, {max_name_width})",
                        "name_min_or_measured": ideal_name_min_or_measured,
                        "ideal_name_formula": f"min({self._NAME_MAX}, {ideal_name_min_or_measured})",
                        "ideal_name": ideal_name,
                        "status_min_or_measured_formula": f"max({self._STATUS_MIN}, {max_status_width})",
                        "status_min_or_measured": ideal_status_min_or_measured,
                        "ideal_status_formula": f"min({self._STATUS_MAX}, {ideal_status_min_or_measured})",
                        "ideal_status": ideal_status,
                        "name_bounds": f"{self._NAME_MIN}-{self._NAME_MAX}",
                        "status_bounds": f"{self._STATUS_MIN}-{self._STATUS_MAX}",
                    },
                    "FIXED_COLUMNS": {
                        "checkbox": checkbox_width,
                        "actions": actions_width,
                        "priority": priority,
                        "priority_reason": f"show_priority={self.show_priority}",
                        "fixed_total_formula": f"{checkbox_width} + {actions_width} + {priority}",
                        "fixed_total": fixed_columns,
                    },
                    "IDEAL_CHECK": {
                        "ideal_total_formula": f"{fixed_columns} + {ideal_name} + {ideal_status}",
                        "ideal_total": ideal_total,
                        "available": available,
                        "comparison": f"{ideal_total} <= {available}",
                        "fits": ideal_fits,
                    }
                }
            )

        # If ideal fits, use it
        if ideal_fits:
            name = ideal_name
            status = ideal_status
            decision = "IDEAL_FITS"
            decision_detail = {"path": "ideal_fits", "name": name, "status": status}
        else:
            # Need to shrink - prioritize name over status
            remaining = available - fixed_columns
            both_min_fit = remaining >= self._NAME_MIN + self._STATUS_MIN

            if both_min_fit:
                # Both can fit at minimum
                name = min(ideal_name, remaining - self._STATUS_MIN)
                status = remaining - name
                decision = "SHRINK_BOTH"
                decision_detail = {
                    "path": "shrink_both",
                    "remaining": remaining,
                    "remaining_formula": f"{available} - {fixed_columns}",
                    "both_min_fit_check": f"{remaining} >= {self._NAME_MIN} + {self._STATUS_MIN} = {self._NAME_MIN + self._STATUS_MIN}",
                    "name_formula": f"min({ideal_name}, {remaining} - {self._STATUS_MIN}) = min({ideal_name}, {remaining - self._STATUS_MIN})",
                    "name": name,
                    "status_formula": f"{remaining} - {name}",
                    "status": status,
                }
            else:
                # Very cramped - give name minimum, rest to status
                name = self._NAME_MIN
                status = max(0, remaining - name)
                decision = "CRAMPED"
                decision_detail = {
                    "path": "cramped",
                    "remaining": remaining,
                    "name": name,
                    "status_formula": f"max(0, {remaining} - {name})",
                    "status": status,
                }

        widths = {
            'checkbox': checkbox_width,
            'name': name,
            'status': status,
            'priority': priority,
            'actions': actions_width,
        }

        if logger:
            logger.log_event(
                "SERVER_WIDTH_CALC_RESULT",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "decision": decision,
                    "decision_detail": decision_detail,
                    "ALLOCATED": widths,
                    "total_allocated": sum(widths.values()),
                    "total_with_overhead_formula": f"{sum(widths.values())} + {border_padding} + {total_margins}",
                    "total_with_overhead": sum(widths.values()) + border_padding + total_margins,
                }
            )

        return widths

    def _calculate_column_widths(self, container_width: int) -> Dict[str, int]:
        """Calculate fixed column widths with content-aware allocation.

        For global tables: fills available space to match panel width.
        For server tables: sizes to content for a more compact appearance.

        Args:
            container_width: Total width available to the table widget

        Returns:
            Dictionary mapping column names to integer widths
        """
        try:
            from ..debug import get_debug_logger
            logger = get_debug_logger()
        except Exception:
            logger = None

        # Constants
        CHECKBOX_WIDTH = 3
        PRIORITY_WIDTH = 8

        # Border and margin overhead depends on mode
        # Global mode: border: none, margin: 0 → overhead = 0
        # Server mode: border: solid (2), margin: 0 1 1 1 (2) → overhead = 4
        is_global = self.server_name == GLOBAL_SCOPE
        BORDER_PADDING = 0 if is_global else 4

        # Actions column width depends on button count
        # Global: "Configure" button = 13 columns (9 chars + 2 left pad + 2 right pad, no margins)
        # Server: "Configure" button = 14 columns (9 chars + 2 left pad + 2 right pad + 1 right margin)
        #         OR both "Configure" + "Use Global" = 30 columns (both buttons + margins)
        if is_global:
            ACTIONS_WIDTH = 13
        else:
            ACTIONS_WIDTH = 30  # Server mode with potentially 2 buttons

        # Calculate margins:
        # checkbox: 0 1 (1 right)
        # name: 0 2 0 1 (1 left, 2 right)
        # status: 0 2 0 1 (1 left, 2 right)
        # priority: 0 2 0 1 (1 left, 2 right)
        # actions: 0 1 (1 left, 1 right)
        #
        # Gaps: checkbox[1]name[2]status[2]priority[2]actions = 7 gaps
        # Without priority: checkbox[1]name[2]status[2]actions = 5 gaps
        total_margins = 7 if self.show_priority else 5

        if logger:
            logger.log_event(
                "CALC_WIDTH_CONSTANTS",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "CONSTANTS": {
                        "CHECKBOX_WIDTH": CHECKBOX_WIDTH,
                        "PRIORITY_WIDTH": PRIORITY_WIDTH,
                        "ACTIONS_WIDTH": ACTIONS_WIDTH,
                        "actions_width_reason": "global: Configure (13)" if is_global else "server: Configure+UseGlobal (30)",
                    },
                    "MODE": {
                        "is_global": is_global,
                        "show_priority": self.show_priority,
                        "BORDER_PADDING": BORDER_PADDING,
                        "border_padding_reason": "no border in global mode" if is_global else "solid border (2) + margin (2)",
                        "total_margins": total_margins,
                        "margins_reason": "7 gaps with priority" if self.show_priority else "5 gaps without priority",
                    },
                    "BOUNDS": {
                        "NAME_MIN": self._NAME_MIN,
                        "NAME_MAX": self._NAME_MAX,
                        "STATUS_MIN": self._STATUS_MIN,
                        "STATUS_MAX": self._STATUS_MAX,
                    }
                }
            )

        # Measure actual content widths
        max_name_width = self._get_max_name_width()
        max_status_width = self._get_max_status_width()

        # For server tables, use content-based sizing instead of filling container
        if not is_global:
            if logger:
                logger.log_event(
                    "CALLING_SERVER_CALC",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "server_name": self.server_name,
                        "plugin_type": self.plugin_type,
                        "ARGS": {
                            "container_width": container_width,
                            "max_name_width": max_name_width,
                            "max_status_width": max_status_width,
                            "checkbox_width": CHECKBOX_WIDTH,
                            "actions_width": ACTIONS_WIDTH,
                            "priority_width": PRIORITY_WIDTH,
                            "border_padding": BORDER_PADDING,
                            "total_margins": total_margins,
                        }
                    }
                )
            return self._calculate_content_based_widths(
                container_width, max_name_width, max_status_width,
                CHECKBOX_WIDTH, ACTIONS_WIDTH, PRIORITY_WIDTH,
                BORDER_PADDING, total_margins
            )

        # For global tables, use space-filling logic (original behavior)
        # Available space after accounting for borders and margins
        available = container_width - BORDER_PADDING - total_margins

        if logger:
            logger.log_event(
                "GLOBAL_WIDTH_CALC_START",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "show_priority": self.show_priority,
                    "CALCULATION": {
                        "container_width": container_width,
                        "BORDER_PADDING": BORDER_PADDING,
                        "total_margins": total_margins,
                        "available_formula": f"{container_width} - {BORDER_PADDING} - {total_margins}",
                        "available_result": available,
                    },
                    "MEASURED_CONTENT": {
                        "max_name_width": max_name_width,
                        "max_status_width": max_status_width,
                    },
                    "BOUNDS": {
                        "NAME_MIN": self._NAME_MIN,
                        "NAME_MAX": self._NAME_MAX,
                        "STATUS_MIN": self._STATUS_MIN,
                        "STATUS_MAX": self._STATUS_MAX,
                    }
                }
            )

        # Allocation: Content-aware with priority-based constraints

        # CRITICAL: Always show at full width
        checkbox = CHECKBOX_WIDTH
        actions = ACTIONS_WIDTH
        critical_total = checkbox + actions
        remaining = available - critical_total

        if logger:
            logger.log_event(
                "GLOBAL_CRITICAL_COLS",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "checkbox": checkbox,
                    "actions": actions,
                    "critical_total_formula": f"{checkbox} + {actions}",
                    "critical_total": critical_total,
                    "remaining_formula": f"{available} - {critical_total}",
                    "remaining": remaining,
                }
            )

        # HIGH PRIORITY: Name - allocate based on actual content with bounds
        # Step 1: Calculate ideal name width
        name_min_or_measured = max(self._NAME_MIN, max_name_width)
        name_needed = min(self._NAME_MAX, name_min_or_measured)

        # Step 2: Check if we need to protect status
        space_left_for_status = remaining - name_needed
        needs_status_protection = space_left_for_status < self._STATUS_MIN

        if needs_status_protection:
            name_before_protection = name_needed
            remaining_minus_status_min = remaining - self._STATUS_MIN
            name = max(self._NAME_MIN, remaining_minus_status_min)
            name_decision = f"PROTECTED_STATUS: needed {name_before_protection}, gave {name} to leave {self._STATUS_MIN} for status"
        else:
            name = name_needed
            name_decision = f"FULL_NEED: gave {name}"
        remaining_after_name = remaining - name

        if logger:
            logger.log_event(
                "GLOBAL_NAME_ALLOCATION",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "STEP1_IDEAL_CALC": {
                        "max_name_width_measured": max_name_width,
                        "NAME_MIN": self._NAME_MIN,
                        "NAME_MAX": self._NAME_MAX,
                        "name_min_or_measured_formula": f"max({self._NAME_MIN}, {max_name_width})",
                        "name_min_or_measured": name_min_or_measured,
                        "name_needed_formula": f"min({self._NAME_MAX}, {name_min_or_measured})",
                        "name_needed": name_needed,
                    },
                    "STEP2_STATUS_PROTECTION_CHECK": {
                        "remaining": remaining,
                        "name_needed": name_needed,
                        "space_left_for_status_formula": f"{remaining} - {name_needed}",
                        "space_left_for_status": space_left_for_status,
                        "STATUS_MIN": self._STATUS_MIN,
                        "needs_protection": needs_status_protection,
                        "comparison": f"{space_left_for_status} < {self._STATUS_MIN}",
                    },
                    "STEP3_FINAL_NAME": {
                        "name_allocated": name,
                        "decision": name_decision,
                        "remaining_after_name_formula": f"{remaining} - {name}",
                        "remaining_after_name": remaining_after_name,
                    }
                }
            )

        # MEDIUM PRIORITY: Priority column - show if we have room
        priority_space_needed = PRIORITY_WIDTH + self._STATUS_MIN
        priority_check = self.show_priority and remaining_after_name >= priority_space_needed

        if priority_check:
            priority = PRIORITY_WIDTH
            remaining_after_priority = remaining_after_name - priority
            priority_decision = f"SHOWN: {priority} cols"
        else:
            # Not enough space - hide priority column entirely
            priority = 0
            remaining_after_priority = remaining_after_name
            if self.show_priority:
                priority_decision = f"HIDDEN: needed {priority_space_needed}, had {remaining_after_name}"
            else:
                priority_decision = "DISABLED: show_priority=False"

        if logger:
            logger.log_event(
                "GLOBAL_PRIORITY_ALLOCATION",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "show_priority_flag": self.show_priority,
                    "remaining_after_name": remaining_after_name,
                    "PRIORITY_WIDTH": PRIORITY_WIDTH,
                    "STATUS_MIN": self._STATUS_MIN,
                    "priority_space_needed_formula": f"{PRIORITY_WIDTH} + {self._STATUS_MIN}",
                    "priority_space_needed": priority_space_needed,
                    "check_formula": f"{self.show_priority} and {remaining_after_name} >= {priority_space_needed}",
                    "check_result": priority_check,
                    "priority_allocated": priority,
                    "remaining_after_priority": remaining_after_priority,
                    "decision": priority_decision,
                }
            )

        # LOW PRIORITY: Status/Scope - gets all remaining space
        # This maximizes visibility of status messages
        status_fits = remaining_after_priority >= self._STATUS_MIN

        if status_fits:
            status = remaining_after_priority
            status_decision = f"ALLOCATED: {status} cols (all remaining)"
        else:
            # Too cramped - hide status column
            status = 0
            status_decision = f"HIDDEN: only {remaining_after_priority} available, need {self._STATUS_MIN}"

        if logger:
            logger.log_event(
                "GLOBAL_STATUS_ALLOCATION",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "remaining_after_priority": remaining_after_priority,
                    "STATUS_MIN": self._STATUS_MIN,
                    "check_formula": f"{remaining_after_priority} >= {self._STATUS_MIN}",
                    "status_fits": status_fits,
                    "status_allocated": status,
                    "decision": status_decision,
                }
            )

        widths = {
            'checkbox': checkbox,
            'name': name,
            'status': status,
            'priority': priority,
            'actions': actions,
        }

        if logger:
            logger.log_event(
                "GLOBAL_WIDTH_CALC_RESULT",
                widget=self,
                screen=self.app.screen if getattr(self, "app", None) else None,
                context={
                    "server_name": self.server_name,
                    "plugin_type": self.plugin_type,
                    "DECISIONS": {
                        "name": name_decision,
                        "priority": priority_decision,
                        "status": status_decision,
                    },
                    "ALLOCATED": widths,
                    "total_allocated": sum(widths.values()),
                    "expected_total": available + BORDER_PADDING + total_margins,
                }
            )

        return widths

    def _apply_column_widths(self) -> None:
        """Apply calculated column widths to header and all rows."""
        if not self._column_widths:
            return

        try:
            from ..debug import get_debug_logger
            logger = get_debug_logger()
        except Exception:
            logger = None

        try:
            # For server-mode tables, set explicit width on the container
            # to prevent expansion beyond content
            if self.server_name != GLOBAL_SCOPE:
                # Width = column widths + border_padding (4) + total_margins (7 or 5)
                # With priority: columns + 4 + 7 = columns + 11
                # Without priority: columns + 4 + 5 = columns + 9
                overhead = 11 if self.show_priority else 9
                needed_width = sum(self._column_widths.values()) + overhead
                scroll = self.query_one(".table-scroll")
                scroll.styles.width = needed_width

                if logger:
                    logger.log_event(
                        "SERVER_CONTAINER_WIDTH_SET",
                        widget=self,
                        screen=self.app.screen if getattr(self, "app", None) else None,
                        context={
                            "server_name": self.server_name,
                            "plugin_type": self.plugin_type,
                            "column_widths": self._column_widths,
                            "total_columns": sum(self._column_widths.values()),
                            "overhead": overhead,
                            "needed_width": needed_width,
                        }
                    )

            # Apply to header (if present)
            headers = self.query(PluginTableHeader)
            if headers:
                header = headers.first()
                header.apply_column_widths(self._column_widths)

            # Apply to all rows
            row_count = 0
            for row in self.query(PluginRowWidget):
                row.apply_column_widths(self._column_widths)
                row_count += 1

            if logger:
                logger.log_event(
                    "WIDTHS_APPLIED",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "server_name": self.server_name,
                        "plugin_type": self.plugin_type,
                        "widths": self._column_widths,
                        "applied_to_rows": row_count,
                        "applied_to_header": headers is not None,
                    }
                )

        except Exception as e:
            # Fail gracefully - widgets may not be mounted yet
            if logger:
                logger.log_event(
                    "column_width_application_failed",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={"error": str(e)}
                )

    def compose(self) -> ComposeResult:
        """Compose the table structure."""
        # Debug: start compose
        try:
            from ..debug import get_debug_logger  # type: ignore

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TABLE_WIDGET_COMPOSE_START",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "plugin_type": self.plugin_type,
                        "server_name": self.server_name,
                        "rows": len(self.plugins_data),
                        "show_priority": self.show_priority,
                        "show_header": self.show_header,
                    },
                )
        except Exception:
            _logger = None  # best-effort

        # Header - only render if show_header is True
        if self.show_header:
            yield PluginTableHeader(
                show_priority=self.show_priority,
                plugin_type=self.plugin_type,
                show_actions=False,
                name_width=self.name_width,
            )
            try:
                if _logger:
                    _logger.log_event(
                        "PLUGIN_TABLE_WIDGET_HEADER_ADDED",
                        widget=self,
                        screen=self.app.screen if getattr(self, "app", None) else None,
                    )
            except Exception:
                pass

        # Content area - allow it to grow with all rows (no internal scrolling)
        rows_container = Container(classes="table-scroll")
        rows_container.can_focus = False  # Container should not be focusable
        with rows_container:
            for plugin_data in self.plugins_data:
                yield PluginRowWidget(
                    plugin_data,
                    self.plugin_type,
                    scope=self.server_name,  # Pass scope to rows
                    show_priority=self.show_priority,
                    show_actions=True,
                    name_width=self.name_width,
                )

        # No dynamic clamp required; ensure legacy state cleared after render
        self.call_after_refresh(self._apply_height_limit)

    async def on_mount(self) -> None:
        """Ensure height limits are in place once the widget is mounted."""
        self._apply_height_limit()

        # Debug: log post-mount state
        try:
            from ..debug import get_debug_logger  # type: ignore

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TABLE_WIDGET_MOUNTED",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "max_height": str(self.styles.max_height),
                        "min_height": str(self.styles.min_height),
                        "rows": len(self.plugins_data),
                    },
                )
        except Exception:
            pass

    async def on_resize(self, event: Resize) -> None:
        """Recalculate and apply column widths when container resizes."""
        # Debug logging
        try:
            from ..debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "PLUGIN_TABLE_WIDGET_RESIZE",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "server_name": self.server_name,
                        "plugin_type": self.plugin_type,
                        "event_width": event.size.width,
                        "event_height": event.size.height,
                        "last_width": self._last_container_width,
                        "width_changed": event.size.width != self._last_container_width,
                        "self_size": f"{self.size.width}x{self.size.height}" if self.size else "None",
                        "parent_size": f"{self.parent.size.width}x{self.parent.size.height}" if self.parent and self.parent.size else "None",
                    }
                )
        except Exception:
            pass

        # Only recalculate if width actually changed
        if event.size.width != self._last_container_width:
            self._last_container_width = event.size.width
            self._column_widths = self._calculate_column_widths(event.size.width)
            self._apply_column_widths()

    def update_plugins(self, plugins_data: List[Dict[str, Any]]) -> None:
        """Update the displayed plugins.

        Args:
            plugins_data: New list of plugin data
        """
        self.plugins_data = plugins_data
        self.name_width = self._calculate_name_width()  # Recalculate for new data
        self.refresh_table()

    def refresh_table(self) -> None:
        """Refresh the table display."""
        # Remove old content
        rows_container = self.query_one(".table-scroll", Container)
        rows_container.remove_children()

        # Apply current sorting if any
        sorted_data = self._sort_data(self.plugins_data)

        # Create new rows
        for plugin_data in sorted_data:
            row = PluginRowWidget(
                plugin_data,
                self.plugin_type,
                scope=self.server_name,  # Pass scope to rows
                show_priority=self.show_priority,
                show_actions=True,
                name_width=self.name_width,
            )
            rows_container.mount(row)

        # Re-apply column widths AFTER refresh completes (newly mounted widgets need time to compose)
        if self._column_widths:
            self.call_after_refresh(self._apply_column_widths)

        # Re-apply height clamp after content changes
        self._apply_height_limit()

    def _apply_height_limit(self) -> None:
        """Allow the table to expand naturally to fit all rows."""
        self.styles.height = "auto"
        self.styles.max_height = None
        self.styles.min_height = None
        # Debug height info
        try:
            from ..debug import get_debug_logger  # type: ignore

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TABLE_WIDGET_HEIGHT",
                    widget=self,
                    screen=self.app.screen if getattr(self, "app", None) else None,
                    context={
                        "plugin_type": self.plugin_type,
                        "row_count": len(self.plugins_data),
                        "max_height": None,
                        "min_height": None,
                    },
                )
        except Exception:
            pass

    def _sort_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort plugin data based on current sort settings.

        Args:
            data: Plugin data to sort

        Returns:
            Sorted plugin data
        """
        if not self.sort_column:
            return data

        sorted_data = data.copy()

        if self.sort_column == PLUGIN_COL_ID_NAME:
            sorted_data.sort(
                key=lambda x: x.get("display_name", ""), reverse=self.sort_descending
            )
        elif self.sort_column == PLUGIN_COL_ID_SCOPE:
            # Global plugins use 'status', server plugins use 'scope'
            field_name = "status" if self.server_name == GLOBAL_SCOPE else "scope"
            sorted_data.sort(
                key=lambda x: x.get(field_name, ""), reverse=self.sort_descending
            )
        elif self.sort_column == PLUGIN_COL_ID_PRIORITY:
            sorted_data.sort(
                key=lambda x: int(x.get("priority", 50)), reverse=self.sort_descending
            )

        return sorted_data

    @on(HeaderClick)
    def on_header_click(self, event: HeaderClick) -> None:
        """Handle header clicks for sorting."""
        column_id = getattr(event, "column_id", getattr(event, "column", None))
        if self.sort_column == column_id:
            # Toggle sort direction
            self.sort_descending = not self.sort_descending
        else:
            # New column, start with ascending
            self.sort_column = column_id
            self.sort_descending = False

        self.refresh_table()
        event.stop()

    # Don't handle these messages here - let them bubble naturally to the screen
    # The messages have bubble=True set, so they will propagate up automatically
