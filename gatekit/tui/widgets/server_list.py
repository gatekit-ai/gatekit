"""Server list widget with focusable checkbox, name, and dynamic column cells."""

from typing import Any, Callable, Dict, List, Optional, Union
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static, OptionList
from textual.widgets.option_list import Option
from gatekit.tui.widgets.ascii_checkbox import ASCIICheckbox
from gatekit.tui.widgets.selectable_static import SelectableStatic
from gatekit.tui.utils.terminal_compat import get_selection_indicator


class DynamicColumnDefinition:
    """Definition of a dynamic column in the server list."""

    def __init__(
        self,
        column_id: str,
        header: str,
        width: int = 7,
        formatter: Optional[Callable[[Any], str]] = None,
        tooltip: Optional[str] = None,
        context_menu: Optional[List[Dict[str, str]]] = None,
        label: str = "",
        key: str = "",
        handler_name: str = "",
    ):
        """Initialize column definition.

        Args:
            column_id: Unique identifier for this column (handler__key)
            header: Column header text
            width: Column width in characters
            formatter: Optional function to format values
            tooltip: Optional hover text for the cell
            context_menu: List of context menu entries from the plugin schema
            label: Prefix label shown before value (e.g., "↑")
            key: Column key within the plugin (e.g., "input", "output")
            handler_name: Plugin handler name (e.g., "token_usage")
        """
        self.column_id = column_id
        self.header = header
        self.width = width
        self.formatter = formatter or str
        self.tooltip = tooltip
        self.context_menu = context_menu or []
        self.label = label
        self.key = key
        self.handler_name = handler_name

    def format_value(self, value: Any) -> str:
        """Format a value for display."""
        if value is None:
            return "—"
        return self.formatter(value)


class ServerEnabledToggle(Message):
    """Message sent when a server's enabled checkbox is toggled."""

    bubble = True

    def __init__(self, server_name: str, enabled: bool) -> None:
        self.server_name = server_name
        self.enabled = enabled
        super().__init__()


class ServerSelected(Message):
    """Message sent when a server name is selected (activated)."""

    bubble = True

    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        super().__init__()


class ColumnCellActivated(Message):
    """Message sent when a dynamic column cell is activated (Enter/Space/click)."""

    bubble = True

    def __init__(
        self, server_name: str, column_id: str, handler_name: str,
        cell_x: int = 0, cell_y: int = 0,
    ) -> None:
        self.server_name = server_name
        self.column_id = column_id
        self.handler_name = handler_name
        self.cell_x = cell_x
        self.cell_y = cell_y
        super().__init__()


class ColumnActionRequested(Message):
    """Message sent when user requests a column action from context menu."""

    bubble = True

    def __init__(
        self,
        column_id: str,
        handler_name: str,
        method_name: str,
        server_name: str,
        scope: str = "server",
        confirm_title: Optional[str] = None,
        confirm_message: Optional[str] = None,
    ) -> None:
        """
        Args:
            column_id: The column identifier
            handler_name: Plugin handler name
            method_name: Classmethod name to call on the plugin
            server_name: Server whose row was right-clicked
            scope: "server" for per-server action, "all_servers" for fan-out
            confirm_title: If set, show confirmation dialog with this title
            confirm_message: Body text for the confirmation dialog
        """
        self.column_id = column_id
        self.handler_name = handler_name
        self.method_name = method_name
        self.server_name = server_name
        self.scope = scope
        self.confirm_title = confirm_title
        self.confirm_message = confirm_message
        super().__init__()


class ServerNameStatic(SelectableStatic):
    """Focusable server name that can be selected."""

    DEFAULT_CSS = """
    ServerNameStatic {
        width: 1fr;
        height: 1;
        padding: 0 1;
    }

    ServerNameStatic:hover {
        background: $boost;
    }

    ServerNameStatic:focus {
        background: $block-cursor-background;
        color: $block-cursor-foreground;
    }

    ServerNameStatic.disabled-server {
        color: $text-muted;
    }
    """

    def __init__(self, server_name: str, enabled: bool = True, **kwargs) -> None:
        super().__init__(server_name, can_focus=True, **kwargs)
        self.server_name = server_name
        if not enabled:
            self.add_class("disabled-server")

    def on_key(self, event) -> None:
        """Handle Enter/Space to select this server."""
        from ..debug import get_debug_logger

        logger = get_debug_logger()

        # Handle Enter and Space for selection (like PluginRowWidget pattern)
        if event.key in ("enter", "space"):
            if logger:
                logger.log_event(
                    "SERVER_NAME_ON_KEY_SELECT",
                    context={"server_name": self.server_name, "key": event.key},
                )
            self._post_server_selected()
            event.prevent_default()
            event.stop()
            return

        # Let parent handle other keys (like ctrl+c for copy)
        super().on_key(event)

    def on_mouse_up(self, event) -> None:
        """Handle mouse up - select server if it was a simple click (no text selection)."""
        from ..debug import get_debug_logger

        # Let parent handle the mouse up first (for text selection)
        super().on_mouse_up(event)

        # If no text was selected, treat as a click to select this server
        selected_text = self._get_selected_text()
        if not selected_text:
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "SERVER_NAME_CLICK_SELECT",
                    context={"server_name": self.server_name},
                )
            self._post_server_selected()

    def _post_server_selected(self) -> None:
        """Post ServerSelected message directly to screen for reliable delivery.

        Posts directly to self.app.screen rather than using message bubbling,
        which ensures the message reaches the screen's @on() handlers reliably.
        """
        msg = ServerSelected(self.server_name)
        if self.app and self.app.screen:
            self.app.screen.post_message(msg)
        else:
            self.post_message(msg)


class DynamicColumnCell(Static):
    """Focusable dynamic column cell that shows context menu on activation.

    Each cell displays a single value with optional label prefix.
    Uses Textual's animate() for smooth counter transitions.
    """

    DEFAULT_CSS = """
    DynamicColumnCell {
        height: 1;
        text-align: right;
        padding: 0 1;
        color: $text-muted;
    }

    DynamicColumnCell:hover {
        background: $boost;
    }

    DynamicColumnCell:focus {
        background: $block-cursor-background;
        color: $block-cursor-foreground;
    }
    """

    # Enable key bindings for this widget
    BINDINGS = [
        ("enter", "activate", "Activate"),
        ("space", "activate", "Activate"),
    ]

    # Animated counter value
    anim_value: reactive[float] = reactive(0.0, repaint=True)

    ANIMATION_DURATION = 0.4

    def __init__(
        self,
        server_name: str,
        column_id: str,
        handler_name: str,
        label: str = "",
        formatter: Optional[Callable] = None,
        context_menu: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> None:
        super().__init__("—", **kwargs)
        self.server_name = server_name
        self.column_id = column_id
        self.handler_name = handler_name
        self._label = label
        self._formatter = formatter or str
        self._context_menu = context_menu or []
        self._has_values = False
        self.can_focus = bool(self._context_menu)

    def update_value(self, value: Union[int, float]) -> None:
        """Update the cell value with animation.

        Args:
            value: The numeric value to display
        """
        if not self._has_values:
            # First data point - set immediately without animation.
            # This avoids a misleading "counting up from zero" effect on
            # startup when loading persisted state from the state file.
            self._has_values = True
            self.anim_value = float(value)
            self.refresh()
            return

        if self.anim_value != float(value):
            self.animate(
                "anim_value",
                float(value),
                duration=self.ANIMATION_DURATION,
                easing="out_cubic",
            )

    def render(self) -> str:
        """Render the current animated counter value."""
        if not self._has_values:
            return "—"
        return f"{self._label}{self._formatter(self.anim_value)}"

    def action_activate(self) -> None:
        """Handle Enter/Space to activate (show context menu)."""
        from ..debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "COLUMN_CELL_ACTIVATE",
                widget=self,
                context={
                    "server_name": self.server_name,
                    "column_id": self.column_id,
                },
            )
        self._post_activated()

    def on_click(self, event) -> None:
        """Handle click to activate (show context menu)."""
        from ..debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "COLUMN_CELL_CLICK",
                widget=self,
                context={
                    "server_name": self.server_name,
                    "column_id": self.column_id,
                    "button": event.button,
                },
            )
        self._post_activated()
        event.stop()

    def _post_activated(self) -> None:
        """Post ColumnCellActivated message to screen."""
        from ..debug import get_debug_logger

        # Get this cell's position for context menu placement
        region = self.region
        cell_x = region.x
        cell_y = region.y + region.height  # Position menu below the cell

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "COLUMN_CELL_POST_ACTIVATED",
                widget=self,
                context={
                    "server_name": self.server_name,
                    "column_id": self.column_id,
                    "cell_x": cell_x,
                    "cell_y": cell_y,
                    "region": str(region),
                },
            )

        msg = ColumnCellActivated(
            self.server_name, self.column_id, self.handler_name, cell_x, cell_y,
        )
        if self.app and self.app.screen:
            self.app.screen.post_message(msg)
        else:
            self.post_message(msg)


class ColumnContextMenu(OptionList):
    """Context menu overlay for dynamic column actions."""

    DEFAULT_CSS = """
    ColumnContextMenu {
        layer: dialog;
        width: 24;
        height: auto;
        max-height: 6;
        border: solid $primary;
        background: $surface;
        padding: 0;
    }

    ColumnContextMenu:focus {
        border: solid $accent;
    }

    ColumnContextMenu > .option-list--option-highlighted {
        background: $accent;
        color: $text;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Dismiss"),
    ]

    def __init__(
        self,
        server_name: str,
        column_id: str,
        handler_name: str,
        context_menu: Optional[List[Dict[str, str]]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.server_name = server_name
        self.column_id = column_id
        self.handler_name = handler_name
        self._context_menu = context_menu or []
        self._dismissed = False
        self._restore_focus_widget = None  # Widget to restore focus to on dismiss
        # Build entries indexed by option ID
        self._menu_entries: Dict[str, Dict[str, Any]] = {}

    def on_mouse_down(self, event) -> None:
        """Dismiss if click lands outside the menu."""
        if self._dismissed:
            return
        if not self.region.contains(event.screen_x, event.screen_y):
            self._dismissed = True
            self._cleanup()
            self.remove()

    def on_mount(self) -> None:
        """Add menu options on mount from context_menu schema."""
        # Capture mouse so clicks anywhere on screen are routed to this widget,
        # allowing click-outside-to-dismiss behavior.
        self.capture_mouse()

        # Capture the currently focused widget so we can restore focus on dismiss
        if self.app:
            self._restore_focus_widget = self.app.focused
        for idx, entry in enumerate(self._context_menu):
            label_template = entry.get("label", "")
            method_name = entry.get("method", "")
            scope = entry.get("scope", "server")
            option_id = f"menu_{idx}"

            # Interpolate {server_name} using .replace() (NOT .format())
            display_label = label_template.replace("{server_name}", self.server_name)

            # Interpolate {server_name} in confirm fields (same safe .replace())
            confirm_title = entry.get("confirm_title")
            confirm_message = entry.get("confirm_message")
            if confirm_title:
                confirm_title = confirm_title.replace("{server_name}", self.server_name)
            if confirm_message:
                confirm_message = confirm_message.replace("{server_name}", self.server_name)

            self._menu_entries[option_id] = {
                "method_name": method_name,
                "label_template": label_template,
                "scope": scope,
                "confirm_title": confirm_title,
                "confirm_message": confirm_message,
            }

            self.add_option(Option(display_label, id=option_id))

        # Highlight the first option so keyboard navigation works immediately
        if self._menu_entries:
            self.highlighted = 0
        self.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        if self._dismissed:
            return

        self._dismissed = True
        option_id = event.option.id
        entry = self._menu_entries.get(option_id)

        if not entry:
            self._cleanup()
            self.remove()
            return

        msg = ColumnActionRequested(
            column_id=self.column_id,
            handler_name=self.handler_name,
            method_name=entry["method_name"],
            server_name=self.server_name,
            scope=entry.get("scope", "server"),
            confirm_title=entry.get("confirm_title"),
            confirm_message=entry.get("confirm_message"),
        )

        if self.app and self.app.screen:
            self.app.screen.post_message(msg)
        else:
            self.post_message(msg)

        self._cleanup()
        self.remove()

    def _cleanup(self) -> None:
        """Release mouse capture and restore focus before removal."""
        self.release_mouse()
        widget = self._restore_focus_widget
        if widget is not None:
            try:
                if getattr(widget, "can_focus", False) and widget.is_attached:
                    widget.focus()
            except Exception:
                pass

    def action_dismiss(self) -> None:
        """Dismiss the menu without action."""
        if not self._dismissed:
            self._dismissed = True
            self._cleanup()
            self.remove()

    def on_blur(self, event) -> None:
        """Dismiss when focus is lost."""
        # Small delay to allow option selection to process first
        if not self._dismissed:
            self.set_timer(0.1, self._check_dismiss_on_blur)

    def _check_dismiss_on_blur(self) -> None:
        """Check if we should dismiss after blur."""
        if not self._dismissed and not self.has_focus:
            self._dismissed = True
            self._cleanup()
            self.remove()


class ServerRowWidget(Container):
    """Individual server row with selection indicator, checkbox, name, and dynamic columns."""

    DEFAULT_CSS = """
    ServerRowWidget {
        height: 1;
        width: 100%;
        layout: horizontal;
        padding: 0;
        margin: 0;
    }

    ServerRowWidget:hover {
        background: $boost;
    }

    ServerRowWidget > .selection-indicator {
        width: 2;
        min-width: 2;
    }

    ServerRowWidget > ASCIICheckbox {
        width: 3;
        min-width: 3;
        margin: 0;
    }

    ServerRowWidget > ASCIICheckbox:hover {
        background: $primary;
    }

    ServerRowWidget.disabled-row > ServerNameStatic {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        server_name: str,
        enabled: bool = True,
        dynamic_columns: Optional[List[DynamicColumnDefinition]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.server_name = server_name
        self.server_enabled = enabled
        self.can_focus = False  # Row itself not focusable, children are
        self._is_selected = False
        self._dynamic_columns = dynamic_columns or []
        self._column_values: Dict[str, Any] = {}

        if not enabled:
            self.add_class("disabled-row")

    def compose(self) -> ComposeResult:
        # Selection indicator (▶ or space)
        indicator = get_selection_indicator()
        indicator_placeholder = " " * len(indicator)
        yield Static(
            indicator_placeholder,
            classes="selection-indicator",
            id=f"indicator_{self.server_name}",
        )

        checkbox = ASCIICheckbox(
            "",
            value=self.server_enabled,
            id=f"server_checkbox_{self.server_name}",
            classes="server-checkbox",
        )
        yield checkbox

        name_widget = ServerNameStatic(
            self.server_name,
            enabled=self.server_enabled,
            id=f"server_name_{self.server_name}",
        )
        yield name_widget

        # Add dynamic columns (right-aligned after server name)
        for col in self._dynamic_columns:
            col_widget = DynamicColumnCell(
                server_name=self.server_name,
                column_id=col.column_id,
                handler_name=col.handler_name,
                label=col.label,
                formatter=col.formatter,
                context_menu=col.context_menu,
                id=f"col_{col.column_id}_{self.server_name}",
            )
            # Set tooltip from column def (skip if None)
            if col.tooltip:
                col_widget.tooltip = col.tooltip
            # Set width programmatically to avoid CSS specificity conflicts
            col_widget.styles.width = col.width
            col_widget.styles.min_width = col.width
            col_widget.styles.max_width = col.width
            yield col_widget

    def update_column_value(self, column_id: str, value: Union[int, float]) -> None:
        """Update a dynamic column's value with animation.

        Args:
            column_id: The column identifier
            value: The integer value to display
        """
        self._column_values[column_id] = value

        try:
            col_widget = self.query_one(
                f"#col_{column_id}_{self.server_name}", DynamicColumnCell
            )
            col_widget.update_value(value)
        except Exception:
            pass

    def get_column_value(self, column_id: str) -> Any:
        """Get the current value of a dynamic column."""
        return self._column_values.get(column_id)

    def set_selected(self, selected: bool) -> None:
        """Update the selection indicator visibility."""
        self._is_selected = selected
        indicator = get_selection_indicator()
        indicator_placeholder = " " * len(indicator)
        try:
            indicator_widget = self.query_one(".selection-indicator", Static)
            indicator_widget.update(indicator if selected else indicator_placeholder)
        except Exception:
            pass

    def on_checkbox_value_changed(self, checkbox: ASCIICheckbox, value: bool) -> None:
        """Handle checkbox value change via callback from ASCIICheckbox.watch_value.

        Note: Message-based handlers (on_ascii_checkbox_changed) don't work reliably
        on Container widgets like ServerRowWidget. We use this callback pattern instead.
        """
        from ..debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "SERVER_CHECKBOX_CALLBACK",
                context={
                    "server_name": self.server_name,
                    "new_value": value,
                },
            )

        self.server_enabled = value

        # Update visual state
        try:
            name_widget = self.query_one(ServerNameStatic)
            if value:
                self.remove_class("disabled-row")
                name_widget.remove_class("disabled-server")
            else:
                self.add_class("disabled-row")
                name_widget.add_class("disabled-server")
        except Exception:
            pass


class ServerListWidget(Vertical):
    """Container for server rows with checkbox, name, and dynamic columns."""

    DEFAULT_CSS = """
    ServerListWidget {
        height: auto;
        max-height: 100%;
        width: 100%;
        overflow-y: auto;
    }

    ServerListWidget:focus-within {
        /* Visual indicator when list has focus */
    }
    """

    def __init__(
        self,
        dynamic_columns: Optional[List[DynamicColumnDefinition]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.can_focus = False  # Container not focusable, rows are
        self._server_rows: List[ServerRowWidget] = []
        self._dynamic_columns = dynamic_columns or []

    async def clear(self) -> None:
        """Remove all server rows."""
        for row in self._server_rows:
            await row.remove()
        self._server_rows = []

    def add_server(self, server_name: str, enabled: bool = True) -> ServerRowWidget:
        """Add a server row."""
        row = ServerRowWidget(
            server_name=server_name,
            enabled=enabled,
            dynamic_columns=self._dynamic_columns,
            id=f"server_row_{server_name}",
        )
        self._server_rows.append(row)
        self.mount(row)
        return row

    def set_dynamic_columns(self, columns: List[DynamicColumnDefinition]) -> None:
        """Set the dynamic column definitions.

        Note: This should be called before adding servers. Existing rows
        will not be updated with new columns.

        Args:
            columns: List of column definitions
        """
        self._dynamic_columns = columns

    def update_column_value(self, server_name: str, column_id: str, value: Union[int, float]) -> None:
        """Update a column value for a specific server.

        Args:
            server_name: The server to update
            column_id: The column identifier
            value: The integer value to display
        """
        row = self.get_row(server_name)
        if row:
            row.update_column_value(column_id, value)

    def update_all_column_values(self, column_id: str, values: Dict[str, Any]) -> None:
        """Update a column's value for multiple servers at once.

        Args:
            column_id: The column identifier
            values: Dictionary mapping server names to their values
        """
        for server_name, value in values.items():
            self.update_column_value(server_name, column_id, value)

    def get_row(self, server_name: str) -> Optional[ServerRowWidget]:
        """Get a server row by name."""
        for row in self._server_rows:
            if row.server_name == server_name:
                return row
        return None

    def get_all_server_names(self) -> List[str]:
        """Get all server names in order."""
        return [row.server_name for row in self._server_rows]

    def focus_server_name(self, server_name: str) -> bool:
        """Focus the name widget of a specific server. Returns True if successful."""
        row = self.get_row(server_name)
        if row:
            try:
                name_widget = row.query_one(ServerNameStatic)
                name_widget.focus()
                return True
            except Exception:
                pass
        return False

    def focus_server_checkbox(self, server_name: str) -> bool:
        """Focus the checkbox of a specific server. Returns True if successful."""
        row = self.get_row(server_name)
        if row:
            try:
                checkbox = row.query_one(ASCIICheckbox)
                checkbox.focus()
                return True
            except Exception:
                pass
        return False

    def focus_server_column(
        self, server_name: str, column_id: str
    ) -> bool:
        """Focus a specific dynamic column cell for a server. Returns True if successful."""
        row = self.get_row(server_name)
        if row:
            try:
                cell = row.query_one(
                    f"#col_{column_id}_{server_name}", DynamicColumnCell
                )
                if cell.can_focus:
                    cell.focus()
                    return True
            except Exception:
                pass
        return False

    @property
    def row_count(self) -> int:
        """Number of server rows."""
        return len(self._server_rows)

    def get_first_focusable(self) -> Optional[ServerNameStatic]:
        """Get the first focusable element (first server name)."""
        if self._server_rows:
            try:
                return self._server_rows[0].query_one(ServerNameStatic)
            except Exception:
                pass
        return None

    def set_selected_server(self, server_name: Optional[str]) -> None:
        """Set the selected server and update all selection indicators."""
        for row in self._server_rows:
            row.set_selected(row.server_name == server_name)
