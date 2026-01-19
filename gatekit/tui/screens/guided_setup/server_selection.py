"""Server selection screen - select servers to manage with Gatekit."""

from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Blur, Focus, Key, MouseDown, Resize
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static
from textual_fspicker import FileSave

from ...guided_setup.deduplication import deduplicate_servers
from ...guided_setup.detection import detect_all_clients, is_gatekit_command
from ...guided_setup.client_registry import get_supported_client_names
from ...guided_setup.models import (
    GuidedSetupState,
    NavigationAction,
    ScreenResult,
)
from ...widgets.selectable_static import SelectableStatic
from ..simple_modals import AllServersUsingGatekitModal, NoServersFoundModal
from ...utils.terminal_compat import get_info_icon

# Import shared wizard styles (after all imports to avoid E402)
WIZARD_CSS_PATH = Path(__file__).resolve().parent.parent.parent / "styles" / "wizard.tcss"
SHARED_WIZARD_CSS = WIZARD_CSS_PATH.read_text()


class ServerSelectionScreen(Screen[ScreenResult]):
    """Screen 1: Select MCP servers to manage with Gatekit.

    Discovers MCP clients, deduplicates servers, and lets user select which to manage.

    Contract:
    - Accepts optional GuidedSetupState (for rescan scenarios)
    - Returns ScreenResult with action and updated state
    - Calls dismiss(ScreenResult(...)) when transitioning
    """

    BINDINGS = [
        Binding("space", "toggle_selection", "Toggle", show=True),
        Binding("a", "select_all", "Select All", show=True),
        Binding("n", "select_none", "Select None", show=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "focus_up", "Up", show=False),
        Binding("down", "focus_down", "Down", show=False),
        Binding("left", "focus_left", "Left", show=False),
        Binding("right", "focus_right", "Right", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]

    CSS = SHARED_WIZARD_CSS + """
    /* ServerSelectionScreen-specific styles */

    ServerSelectionScreen .path-row {
        height: auto;
        align: left middle;
        margin-bottom: 1;
    }

    ServerSelectionScreen #change_config_location {
        width: auto;
        height: 1;
        padding: 0;
        margin-left: 2;
    }

    ServerSelectionScreen .description-row {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    ServerSelectionScreen .description-row .description {
        width: auto;
        margin: 0;
    }

    ServerSelectionScreen #server_info_icon {
        color: $primary;
        width: 3;
        height: 1;
        content-align: center middle;
    }

    ServerSelectionScreen #server_info_icon:hover {
        text-style: bold;
        background: $boost;
    }
    """

    def __init__(self, state: Optional[GuidedSetupState] = None) -> None:
        """Initialize server selection screen.

        Args:
            state: Optional existing state (for rescan scenarios)
        """
        super().__init__()
        # Use provided state or create new one
        self.state = state or GuidedSetupState()
        # Track if table columns have been initialized
        self._servers_table_initialized = False
        # Compute default config path for display
        self._default_config_path = self._get_smart_default_path()

    def compose(self) -> ComposeResult:
        """Build UI with servers table and selection controls."""
        yield Header()

        with Container(classes="wizard-screen"):
            with Container(classes="container"):
                with VerticalScroll(id="content_scroll", can_focus=False):
                    yield SelectableStatic("Select MCP Servers to Manage", classes="screen-title")

                    # Description with info icon
                    with Horizontal(classes="description-row"):
                        yield SelectableStatic(
                            "Selected MCP servers will be added to your Gatekit configuration",
                            classes="description",
                        )
                        yield Static(f" {get_info_icon()}", id="server_info_icon", classes="info-icon")

                    # Interactive servers table
                    # Start with cursor hidden since Next button has initial focus
                    table = DataTable(id="servers_table", cursor_type="row", zebra_stripes=True)
                    table.show_cursor = False
                    table.can_focus = True
                    yield table

                    # Selection summary
                    yield SelectableStatic("", id="selection_summary", classes="summary")

                    # Config path display with Change Location button
                    yield SelectableStatic("Configuration will be saved to:", classes="section-title")
                    with Horizontal(classes="path-row"):
                        yield SelectableStatic(
                            f"  {self._default_config_path}",
                            id="config_path_display",
                            classes="path-display",
                        )
                        yield Button("Change Location", id="change_config_location", variant="default", compact=True)

                # Action buttons (wizard pattern: Cancel ... Next)
                with Horizontal(classes="buttons"):
                    yield Button("Cancel", id="cancel_button", variant="default")
                    yield Static("", classes="button-spacer")
                    yield Button(
                        "Next",
                        id="next_button",
                        variant="primary",
                        classes="hidden",
                    )

        yield Footer()

    def _get_smart_default_path(self) -> Path:
        """Generate smart default config path with conflict avoidance.

        Returns:
            Absolute Path object for default config location (configs/gatekit.yaml or incremented)
        """
        base_path = Path("configs/gatekit.yaml").resolve()

        # If no conflict, use base path
        if not base_path.exists():
            return base_path

        # Find next available number
        counter = 1
        while True:
            candidate = Path(f"configs/gatekit-{counter}.yaml").resolve()
            if not candidate.exists():
                return candidate
            counter += 1
            # Safety limit to prevent infinite loops
            if counter > 1000:
                return Path(f"configs/gatekit-{counter}.yaml").resolve()

    async def on_mount(self) -> None:
        """Start detection when screen mounts."""
        # Set tooltip on info icon
        try:
            info_icon = self.query_one("#server_info_icon", Static)
            supported_clients = get_supported_client_names()
            clients_list = ", ".join(supported_clients)
            info_icon.tooltip = (
                f"Listed servers detected from existing MCP clients on this system. "
                f"Looked for {clients_list}"
            )
        except Exception:
            pass

        await self.run_detection()

    def _populate_servers_table(self) -> None:
        """Populate servers DataTable with selection indicators."""
        table = self.query_one("#servers_table", DataTable)

        # Initialize columns if needed
        if not self._servers_table_initialized:
            table.clear()
            table.add_column("")  # Selection indicator
            table.add_column("Server")
            table.add_column("Used By")
            table.add_column("Command/Transport")
            self._servers_table_initialized = True
        else:
            # Just clear rows, keep columns
            table.clear()

        # If no servers, show empty state
        if not self.state.deduplicated_servers:
            return

        # Add rows with selection state
        for dedupe_server in self.state.deduplicated_servers:
            server = dedupe_server.server
            is_selected = server.name in self.state.selected_server_names

            # Selection indicator
            if is_selected:
                indicator = Text("[X]")
            else:
                indicator = Text("[ ]", style="dim")

            # Server name (dim when unselected, normal when selected)
            server_name = Text(server.name, style="" if is_selected else "dim")

            # Command/Transport column
            if server.is_stdio():
                command_str = " ".join(server.command) if server.command else "N/A"
            else:
                command_str = f"{server.transport.value}: {server.url or 'N/A'}"

            # Used By column - include env vars info
            clients = ", ".join(dedupe_server.client_names)
            if dedupe_server.is_shared:
                used_by_parts = [f"Shared: {clients}"]
            else:
                used_by_parts = [clients]

            # Add env var count inline
            if server.has_env_vars():
                used_by_parts.append(f"[{len(server.env)} env vars]")

            used_by = " ".join(used_by_parts)

            table.add_row(
                indicator,
                server_name,
                Text(used_by, style="dim"),
                Text(command_str, style="dim"),
                key=server.name,  # Use server name as row key
            )

    def _filter_gatekit_servers(self, clients: list) -> list:
        """Filter out Gatekit servers from clients, returning new DetectedClient objects.

        Args:
            clients: List of DetectedClient objects

        Returns:
            List of DetectedClient objects with Gatekit servers removed
        """
        from ...guided_setup.models import DetectedClient
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event("filter_gatekit_servers_start", context={
                "input_clients": [c.client_type.value for c in clients],
                "input_server_counts": {c.client_type.value: len(c.servers) for c in clients},
            })

        filtered_clients = []
        for client in clients:
            if logger:
                logger.log_event("filter_client", context={
                    "client": client.client_type.value,
                    "servers": [s.name for s in client.servers],
                    "server_commands": {s.name: s.command for s in client.servers},
                })

            # Filter out gatekit-gateway servers
            non_gatekit_servers = []
            for s in client.servers:
                has_command = bool(s.command)
                is_gatekit = is_gatekit_command(s.command) if s.command else False
                keep = has_command and not is_gatekit

                if logger:
                    logger.log_event("filter_server", context={
                        "client": client.client_type.value,
                        "server": s.name,
                        "has_command": has_command,
                        "is_gatekit": is_gatekit,
                        "keep": keep,
                    })

                if keep:
                    non_gatekit_servers.append(s)

            # Only include client if it has non-Gatekit servers
            if non_gatekit_servers:
                # Create new client with filtered servers
                filtered_client = DetectedClient(
                    client_type=client.client_type,
                    config_path=client.config_path,
                    servers=non_gatekit_servers,
                    parse_errors=client.parse_errors,
                    gatekit_config_path=client.gatekit_config_path
                )
                filtered_clients.append(filtered_client)

        if logger:
            logger.log_event("filter_gatekit_servers_end", context={
                "output_clients": [c.client_type.value for c in filtered_clients],
                "output_server_counts": {c.client_type.value: len(c.servers) for c in filtered_clients},
            })

        return filtered_clients

    async def run_detection(self) -> None:
        """Run client detection, deduplicate servers, and populate table.

        Uses state.update_deduplicated_servers() to preserve existing selections.
        """
        # Run detection (sync function in thread worker)
        worker = self.run_worker(detect_all_clients, thread=True)
        detected_clients = await worker.wait()

        # SCENARIO 1: Zero clients detected at all
        # This is the "can't help you" case - show modal and exit wizard
        if len(detected_clients) == 0:
            supported_clients = get_supported_client_names()
            # Use push_screen with callback instead of push_screen_wait
            # to avoid blocking issues when called from on_mount
            self.app.push_screen(
                NoServersFoundModal(supported_clients),
                callback=self._on_no_servers_modal_dismissed,
            )
            return

        # Count total servers BEFORE filtering to distinguish "no servers" from "all using Gatekit"
        total_servers_before_filter = sum(len(client.servers) for client in detected_clients)

        # Deduplicate servers from ALL clients, but filter out Gatekit servers
        # This way users can add non-Gatekit servers even from clients that already use Gatekit
        all_clients_for_dedup = self._filter_gatekit_servers(detected_clients)
        deduplicated_servers = deduplicate_servers(all_clients_for_dedup)

        # Check if we have parse errors from any client
        all_parse_errors = []
        for client in detected_clients:
            all_parse_errors.extend(client.parse_errors)

        # If zero servers but we have parse errors, it means servers exist but failed to parse
        # Show errors to user so they can fix their config
        if len(deduplicated_servers) == 0 and all_parse_errors:
            # Show parse errors (first 3) so user knows what went wrong
            error_summary = "\n".join(f"• {err}" for err in all_parse_errors[:3])
            if len(all_parse_errors) > 3:
                error_summary += f"\n• ... and {len(all_parse_errors) - 3} more"

            self.notify(
                f"Found {len(detected_clients)} client(s) but all servers failed to parse:\n\n{error_summary}\n\n"
                f"Fix your client config files and restart guided setup.",
                severity="error",
                timeout=15
            )
            # Exit wizard - user needs to fix their configs
            self.dismiss(ScreenResult(action=NavigationAction.CANCEL, state=None))
            return

        # If zero non-Gatekit servers remaining, show appropriate modal
        if len(deduplicated_servers) == 0:
            # Distinguish between "no servers at all" vs "all servers already use Gatekit"
            if total_servers_before_filter > 0:
                # All detected servers are already using Gatekit
                self.app.push_screen(
                    AllServersUsingGatekitModal(detected_clients),
                    callback=self._on_no_servers_modal_dismissed,
                )
            else:
                # No servers configured in any client
                supported_clients = get_supported_client_names()
                self.app.push_screen(
                    NoServersFoundModal(supported_clients),
                    callback=self._on_no_servers_modal_dismissed,
                )
            return

        # Update state while preserving user selections (smart reconciliation)
        # Pass ALL detected clients (including those with Gatekit) so they appear on ClientSelectionScreen
        self.state.update_deduplicated_servers(deduplicated_servers, detected_clients)

        # Initialize selections if this is first visit
        if not self.state.selected_server_names and deduplicated_servers:
            self.state.selected_server_names = {
                ds.server.name for ds in deduplicated_servers
            }

        # Populate servers table
        self._populate_servers_table()

        # Update summary
        self._update_summary()

        # Show Next button (initially enabled since all servers selected by default)
        next_button = self.query_one("#next_button", Button)
        next_button.remove_class("hidden")
        # Focus Next button by default (primary action)
        next_button.focus()

        # Update button state based on current selection
        self._update_next_button_state()

    def _update_summary(self) -> None:
        """Update the selection summary."""
        selected_count = len(self.state.selected_server_names)
        total_count = len(self.state.deduplicated_servers)

        if total_count == 0:
            summary = "No servers found"
        else:
            summary = f"Selected {selected_count} of {total_count} server(s)"

        self.query_one("#selection_summary", SelectableStatic).update(summary)

    def _update_next_button_state(self) -> None:
        """Enable/disable Next button based on selection count.

        SCENARIO 2: Zero servers selected (preventable error state)
        Disable Next button and show clear feedback to user.
        """
        selected_count = len(self.state.selected_server_names)

        try:
            next_button = self.query_one("#next_button", Button)
            next_button.disabled = (selected_count == 0)
        except Exception:
            # Button may not exist yet during initialization
            pass

    def action_toggle_selection(self) -> None:
        """Toggle selection of the currently highlighted server."""
        table = self.query_one("#servers_table", DataTable)

        # Get the row key at cursor position
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return  # No row selected

        # Toggle selection state
        server_name = str(row_key.value)
        if server_name in self.state.selected_server_names:
            self.state.selected_server_names.remove(server_name)
        else:
            self.state.selected_server_names.add(server_name)

        # Refresh table to update visual state
        cursor_row = table.cursor_coordinate.row
        self._populate_servers_table()
        self._update_summary()
        self._update_next_button_state()

        # Restore cursor position
        table.move_cursor(row=cursor_row)

    def action_select_all(self) -> None:
        """Select all servers."""
        self.state.selected_server_names = {
            ds.server.name for ds in self.state.deduplicated_servers
        }
        cursor_row = self.query_one("#servers_table", DataTable).cursor_coordinate.row
        self._populate_servers_table()
        self._update_summary()
        self._update_next_button_state()
        # Restore cursor position
        self.query_one("#servers_table", DataTable).move_cursor(row=cursor_row)

    def action_select_none(self) -> None:
        """Deselect all servers."""
        self.state.selected_server_names.clear()
        cursor_row = self.query_one("#servers_table", DataTable).cursor_coordinate.row
        self._populate_servers_table()
        self._update_summary()
        self._update_next_button_state()
        # Restore cursor position
        self.query_one("#servers_table", DataTable).move_cursor(row=cursor_row)

    @on(DataTable.RowSelected, "#servers_table")
    def on_server_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter key) as toggle."""
        self.action_toggle_selection()

    @on(DataTable.RowHighlighted, "#servers_table")
    def on_server_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight (mouse click or keyboard navigation) - ensure cursor is visible."""
        table = self.query_one("#servers_table", DataTable)
        table.show_cursor = True

    def on_focus(self, event: Focus) -> None:
        """Handle focus events - show cursor when table gains focus (e.g., mouse click)."""
        if isinstance(event.widget, DataTable) and event.widget.id == "servers_table":
            event.widget.show_cursor = True

    def on_blur(self, event: Blur) -> None:
        """Handle blur events - hide cursor when table loses focus (e.g., clicking away)."""
        if isinstance(event.widget, DataTable) and event.widget.id == "servers_table":
            event.widget.show_cursor = False

    def on_mouse_down(self, event: MouseDown) -> None:
        """Handle mouse clicks - ensure table shows cursor when clicked."""
        # Check if click is on the servers table
        widget = self.get_widget_at(event.screen_x, event.screen_y)[0]
        if isinstance(widget, DataTable) and widget.id == "servers_table":
            widget.show_cursor = True
            widget.focus()

    @on(Button.Pressed, "#next_button")
    def on_next(self) -> None:
        """Handle next button press."""
        # Set config path in state
        self.state.config_path = self._default_config_path
        self.dismiss(
            ScreenResult(action=NavigationAction.CONTINUE, state=self.state)
        )

    @on(Button.Pressed, "#change_config_location")
    async def on_change_config_location(self) -> None:
        """Handle Change Location button - open file picker."""
        current_path = Path(self._default_config_path)

        # Determine initial directory
        if current_path.parent.exists():
            initial_location = current_path.parent
        else:
            initial_location = Path.cwd()

        # Ensure location is absolute
        if not initial_location.is_absolute():
            initial_location = Path.cwd() / initial_location

        # Open file picker with prepopulated filename
        try:
            selected_path = await self.app.push_screen_wait(
                FileSave(
                    location=initial_location,
                    title="Save Gatekit Configuration",
                    default_file=current_path.name,
                )
            )

            # Update path if user selected a path (didn't cancel)
            if selected_path is not None:
                # Ensure path is absolute
                self._default_config_path = Path(selected_path).resolve()
                # Update the display
                path_display = self.query_one("#config_path_display", SelectableStatic)
                path_display.update(f"  {self._default_config_path}")
        except Exception:
            # File picker cancelled or error - do nothing
            pass

    @on(Button.Pressed, "#cancel_button")
    def on_cancel(self) -> None:
        """Handle cancel button press."""
        self.dismiss(ScreenResult(action=NavigationAction.CANCEL, state=None))

    def action_cancel(self) -> None:
        """Handle escape key."""
        self.on_cancel()

    def _on_no_servers_modal_dismissed(self, _result: None) -> None:
        """Handle dismissal of the NoServersFoundModal.

        This is a callback for push_screen - must NOT return the AwaitComplete
        from dismiss(), or Textual will try to await it and raise ScreenError.
        """
        self.dismiss(ScreenResult(action=NavigationAction.CANCEL, state=None))

    def on_key(self, event: Key) -> None:
        """Handle keyboard navigation between table, Change Location button, and action buttons."""
        focused = self.focused

        # Handle down arrow when on the DataTable's last row
        if event.key == "down" and isinstance(focused, DataTable):
            table = focused
            # Check if cursor is on the last row
            if table.cursor_row is not None and table.row_count > 0:
                if table.cursor_row == table.row_count - 1:
                    # On last row - move focus to Change Location button (hide cursor)
                    try:
                        table.show_cursor = False
                        change_btn = self.query_one("#change_config_location", Button)
                        change_btn.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

        # Handle up arrow navigation
        elif event.key == "up":
            if isinstance(focused, Button):
                if focused.id in ("cancel_button", "next_button"):
                    # Up from Cancel/Next -> Change Location button
                    try:
                        change_btn = self.query_one("#change_config_location", Button)
                        change_btn.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "change_config_location":
                    # Up from Change Location -> table (last row)
                    try:
                        table = self.query_one("#servers_table", DataTable)
                        if table.row_count > 0:
                            table.show_cursor = True
                            table.focus()
                            table.move_cursor(row=table.row_count - 1)
                            event.prevent_default()
                            event.stop()
                    except Exception:
                        pass

        # Handle down arrow navigation
        elif event.key == "down":
            if isinstance(focused, Button):
                if focused.id == "change_config_location":
                    # Down from Change Location -> Next button
                    try:
                        next_btn = self.query_one("#next_button", Button)
                        if "hidden" not in next_btn.classes:
                            next_btn.focus()
                            event.prevent_default()
                            event.stop()
                    except Exception:
                        pass
                elif focused.id in ("cancel_button", "next_button"):
                    # Block wrap-around from Cancel/Next buttons
                    event.prevent_default()
                    event.stop()

        # Handle left arrow navigation
        elif event.key == "left":
            if isinstance(focused, Button):
                if focused.id == "next_button":
                    # Left from Next -> Cancel
                    try:
                        self.query_one("#cancel_button", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "change_config_location":
                    # Left from Change Location -> Cancel
                    try:
                        self.query_one("#cancel_button", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

        # Handle right arrow navigation
        elif event.key == "right":
            if isinstance(focused, Button):
                if focused.id == "cancel_button":
                    # Right from Cancel -> Next
                    try:
                        next_btn = self.query_one("#next_button", Button)
                        if "hidden" not in next_btn.classes:
                            next_btn.focus()
                            event.prevent_default()
                            event.stop()
                    except Exception:
                        pass
                elif focused.id == "change_config_location":
                    # Right from Change Location -> Next
                    try:
                        next_btn = self.query_one("#next_button", Button)
                        if "hidden" not in next_btn.classes:
                            next_btn.focus()
                            event.prevent_default()
                            event.stop()
                    except Exception:
                        pass

        # Handle PageUp/PageDown for scrolling content
        elif event.key == "pageup":
            try:
                scroll_container = self.query_one("#content_scroll", VerticalScroll)
                scroll_container.scroll_page_up()
                event.prevent_default()
                event.stop()
            except Exception:
                pass
        elif event.key == "pagedown":
            try:
                scroll_container = self.query_one("#content_scroll", VerticalScroll)
                scroll_container.scroll_page_down()
                event.prevent_default()
                event.stop()
            except Exception:
                pass

    def on_resize(self, event: Resize) -> None:
        """Recalculate column widths when terminal is resized."""
        # Refresh servers table
        self._populate_servers_table()

    def action_focus_right(self) -> None:
        """Move focus right (no-op, handled in on_key)."""
        pass

    def action_focus_left(self) -> None:
        """Move focus left (no-op, handled in on_key)."""
        pass

    def action_focus_up(self) -> None:
        """Move focus up (no-op, handled in on_key)."""
        pass

    def action_focus_down(self) -> None:
        """Move focus down (no-op, handled in on_key)."""
        pass

    def action_page_up(self) -> None:
        """Scroll page up (no-op, handled in on_key)."""
        pass

    def action_page_down(self) -> None:
        """Scroll page down (no-op, handled in on_key)."""
        pass
