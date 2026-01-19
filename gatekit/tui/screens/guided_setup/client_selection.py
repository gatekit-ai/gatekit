"""Client selection screen - select MCP clients to manage."""

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Blur, Focus, Key, MouseDown
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static
from textual_fspicker import SelectDirectory

from ...guided_setup.config_generation import generate_gatekit_config
from ...guided_setup.gateway import locate_gatekit_gateway
from ...guided_setup.migration_instructions import generate_migration_instructions
from ...guided_setup.restore_scripts import generate_restore_scripts
from ...guided_setup.models import ClientType, DetectedClient, GuidedSetupState, NavigationAction, ScreenResult
from ...guided_setup import client_registry
from ...utils.terminal_compat import get_info_icon

# Import shared wizard styles (after all imports to avoid E402)
WIZARD_CSS_PATH = Path(__file__).resolve().parent.parent.parent / "styles" / "wizard.tcss"
SHARED_WIZARD_CSS = WIZARD_CSS_PATH.read_text()


class ClientSelectionScreen(Screen[ScreenResult]):
    """Screen 2: Select MCP clients to manage with Gatekit.

    Contract:
    - Requires GuidedSetupState from ServerSelectionScreen
    - Returns ScreenResult with action and updated state
    - Sets restore_dir in state
    """

    BINDINGS = [
        Binding("space", "toggle_client_selection", "Toggle", show=True),
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
    /* ClientSelectionScreen-specific styles */

    ClientSelectionScreen .restore-title-row {
        width: 100%;
        height: auto;
        margin-top: 2;
        margin-bottom: 1;
    }

    ClientSelectionScreen .restore-title-row .section-title {
        width: auto;
        margin: 0;
    }

    ClientSelectionScreen #restore_info_icon {
        color: $primary;
        width: 3;
        height: 1;
        content-align: center middle;
    }

    ClientSelectionScreen #restore_info_icon:hover {
        text-style: bold;
        background: $boost;
    }
    """

    def __init__(self, state: GuidedSetupState) -> None:
        """Initialize client selection screen.

        Args:
            state: State from previous screen
        """
        super().__init__()
        self.state = state
        # Track available clients (for client selection DataTable)
        self._available_clients = []
        # Track which clients were actually detected (vs. placeholders for undetected clients)
        self._detected_client_types: set[ClientType] = set()
        # Track if clients table columns have been initialized
        self._clients_table_initialized = False
        # Track current cursor position for toggle action
        self._current_cursor_client_type = None
        # Track current restore path
        self._current_restore_path = (
            state.restore_dir if state.restore_dir
            else Path.home() / "Documents" / "gatekit-restore"
        )

    def _initialize_from_state(self) -> None:
        """Initialize from existing state (reuse detected clients, don't re-scan).

        This method:
        - Shows ALL supported clients (detected + undetected)
        - Reuses state.detected_clients (NO re-scanning)
        - Creates placeholder DetectedClient objects for undetected clients
        - Atomically populates state.already_configured_clients for next screen
        - Initializes selection state (first visit) or preserves it (BACK navigation)
        """
        # Track which clients were actually detected
        self._detected_client_types = {c.client_type for c in self.state.detected_clients}

        # Get all supported client types from registry
        all_client_types = {entry.client_type for entry in client_registry.CLIENT_REGISTRY}

        # Build list of all clients (detected + placeholders for undetected)
        self._available_clients = []

        # Add detected clients first
        detected_clients_by_type = {c.client_type: c for c in self.state.detected_clients}

        # Add all supported clients (detected or placeholder)
        for client_type in sorted(all_client_types, key=lambda ct: ct.value):
            if client_type in detected_clients_by_type:
                # Use the actual detected client
                self._available_clients.append(detected_clients_by_type[client_type])
            else:
                # Create a placeholder for undetected client
                # Get the expected config path from registry
                registry_entry = client_registry.get_registry_entry(client_type)
                if registry_entry:
                    expected_path = registry_entry.config_paths()
                    if expected_path is None:
                        expected_path = Path("(Unknown)")

                    placeholder = DetectedClient(
                        client_type=client_type,
                        config_path=expected_path,
                        servers=[],
                        parse_errors=[],
                    )
                    self._available_clients.append(placeholder)

        # ATOMICALLY rebuild already_configured_clients (prevents duplicates on BACK)
        # This is tracked for the next screen to inform the user
        # Only include detected clients (not placeholders)
        self.state.already_configured_clients.clear()
        for client in self._available_clients:
            if client.client_type in self._detected_client_types and client.has_gatekit():
                # Store full DetectedClient object (not just ClientType)
                self.state.already_configured_clients.append(client)

        # Initialize selection state (first visit) or preserve (BACK navigation)
        if not self.state.selected_client_types:
            # First visit: select only detected clients by default
            self.state.selected_client_types = {c.client_type for c in self._available_clients
                                                if c.client_type in self._detected_client_types}
        # else: BACK navigation, preserve existing selections

    def _populate_clients_table(self) -> None:
        """Populate clients DataTable with selection indicators.

        Following ServerSelectionScreen pattern:
        - Checkbox indicators ([X] or [ ])
        - Warning indicator (⚠️) for already-configured clients
        - Row styling based on selection state
        - "(Not detected)" for undetected clients
        """
        from rich.text import Text

        table = self.query_one("#clients_table", DataTable)

        # Initialize columns if needed
        if not self._clients_table_initialized:
            table.clear()
            table.add_column("")  # Selection indicator
            table.add_column("Client")
            table.add_column("Config Path")
            self._clients_table_initialized = True
        else:
            # Just clear rows, keep columns
            table.clear()

        # If no clients, show empty state
        if not self._available_clients:
            return

        # Add rows with selection state (sort by client type for consistency)
        sorted_clients = sorted(self._available_clients, key=lambda c: c.client_type.value)
        for client in sorted_clients:
            is_detected = client.client_type in self._detected_client_types
            is_selected = client.client_type in self.state.selected_client_types

            # Selection indicator
            if not is_detected:
                # Undetected clients can't be selected
                indicator = Text("[ ]", style="dim")
            elif is_selected:
                indicator = Text("[X]")
            else:
                indicator = Text("[ ]", style="dim")

            # Client name
            if not is_detected:
                client_name = Text(client.display_name(), style="dim")
            elif is_selected:
                client_name = Text(client.display_name(), style="")
            else:
                client_name = Text(client.display_name(), style="dim")

            # Config path
            if not is_detected:
                config_path_text = Text("(Not detected)", style="dim italic")
            else:
                config_path_text = Text(str(client.config_path), style="dim")

            table.add_row(
                indicator,
                client_name,
                config_path_text,
                key=client.client_type.value,  # Use client type as row key
            )

    def action_toggle_client_selection(self) -> None:
        """Toggle selection of the currently highlighted client."""
        # Try to get table, but handle case where it doesn't exist (for testing)
        try:
            table = self.query_one("#clients_table", DataTable)
        except Exception:
            table = None

        # Get the row key at cursor position
        if table:
            try:
                row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
                # Get ClientType from row key
                client_type_value = str(row_key.value)
                client_type = ClientType(client_type_value)
            except Exception:
                # If no cursor or no table, try using _current_cursor_client_type
                if self._current_cursor_client_type:
                    client_type = self._current_cursor_client_type
                else:
                    return  # No row selected
        else:
            # No table (testing mode), use _current_cursor_client_type
            if self._current_cursor_client_type:
                client_type = self._current_cursor_client_type
            else:
                return  # No cursor set

        # Don't allow toggling undetected clients
        if client_type not in self._detected_client_types:
            # Show notification that this client wasn't detected
            self.notify(
                f"{client_type.display_name()} was not detected on this system",
                severity="information",
                timeout=3,
            )
            return

        # Toggle selection state
        if client_type in self.state.selected_client_types:
            self.state.selected_client_types.remove(client_type)
        else:
            self.state.selected_client_types.add(client_type)

        # Refresh table and summary to update visual state (if table exists)
        if table:
            cursor_row = table.cursor_coordinate.row
            self._populate_clients_table()
            self._update_client_summary()

            # Restore cursor position
            try:
                table.move_cursor(row=cursor_row)
            except Exception:
                pass

    def action_select_all(self) -> None:
        """Select all detected clients."""
        # Only select detected clients (not placeholders)
        self.state.selected_client_types = self._detected_client_types.copy()
        cursor_row = self.query_one("#clients_table", DataTable).cursor_coordinate.row
        self._populate_clients_table()
        self._update_client_summary()
        # Restore cursor position
        self.query_one("#clients_table", DataTable).move_cursor(row=cursor_row)

    def action_select_none(self) -> None:
        """Deselect all clients."""
        self.state.selected_client_types.clear()
        cursor_row = self.query_one("#clients_table", DataTable).cursor_coordinate.row
        self._populate_clients_table()
        self._update_client_summary()
        # Restore cursor position
        self.query_one("#clients_table", DataTable).move_cursor(row=cursor_row)

    def _get_client_selection_summary(self) -> str:
        """Get client selection summary text.

        Returns:
            Summary text like "Selected 1 of 2 detected client(s)"
        """
        selected_count = len(self.state.selected_client_types)
        detected_count = len(self._detected_client_types)

        if detected_count == 0:
            return "No clients detected"
        else:
            return f"Selected {selected_count} of {detected_count} detected client(s)"

    def _update_client_summary(self) -> None:
        """Update the client selection summary display."""
        summary_text = self._get_client_selection_summary()
        try:
            summary_widget = self.query_one("#client_selection_summary", Static)
            summary_widget.update(summary_text)
        except Exception:
            # Widget doesn't exist yet (during compose)
            pass

    async def on_mount(self) -> None:
        """Initialize when screen mounts."""
        # Initialize state from detected clients
        self._initialize_from_state()

        # Populate the clients table
        self._populate_clients_table()

        # Update summary
        self._update_client_summary()

        # Set tooltip on info icon
        try:
            info_icon = self.query_one("#restore_info_icon", Static)
            info_icon.tooltip = (
                "You will receive instructions on the next page to update the MCP clients you want to use with Gatekit. "
                "If you decide Gatekit isn't for you, the scripts and instructions stored in this directory will help you "
                "revert back to your original state."
            )
        except Exception:
            pass

        # Focus Next button by default (primary action)
        next_button = self.query_one("#next", Button)
        next_button.focus()

    def compose(self) -> ComposeResult:
        """Build the client selection UI."""
        yield Header()

        with Container(classes="wizard-screen"):
            with Container(classes="container"):
                with VerticalScroll(id="content_scroll", can_focus=False):
                    yield Static("Select MCP Clients to Manage", classes="screen-title")
                    yield Static(
                        "Choose which MCP clients you want setup instructions for. No automated changes will be made.",
                        classes="description",
                    )

                    # Client selection DataTable
                    table = DataTable(id="clients_table", cursor_type="row", zebra_stripes=True)
                    table.show_cursor = False
                    table.can_focus = True
                    yield table

                    # Selection summary
                    yield Static("", id="client_selection_summary", classes="summary")

                    # Restore directory section with info icon
                    with Horizontal(classes="restore-title-row"):
                        yield Static("Restore scripts will be saved to:", classes="section-title")
                        yield Static(f" {get_info_icon()}", id="restore_info_icon", classes="info-icon")
                    with Horizontal(classes="path-row"):
                        yield Static(
                            f"  {self._current_restore_path}",
                            id="restore_path_display",
                            classes="path-display",
                        )
                        yield Button("Change Location", id="change_restore_location", variant="default", compact=True)

                # Action buttons (wizard pattern: Back ... Cancel ... Next)
                with Horizontal(classes="buttons"):
                    yield Button("Back", id="back", variant="default")
                    yield Static("", classes="button-spacer")
                    yield Button("Cancel", id="cancel", variant="default")
                    yield Button("Next", id="next", variant="primary")

        yield Footer()

    @on(DataTable.RowSelected, "#clients_table")
    def on_client_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection (Enter key) as toggle."""
        self.action_toggle_client_selection()

    @on(DataTable.RowHighlighted, "#clients_table")
    def on_client_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Handle row highlight (mouse click or keyboard navigation) - ensure cursor is visible."""
        table = self.query_one("#clients_table", DataTable)
        table.show_cursor = True

    def on_focus(self, event: Focus) -> None:
        """Handle focus events - show cursor when table gains focus."""
        if isinstance(event.widget, DataTable) and event.widget.id == "clients_table":
            event.widget.show_cursor = True

    def on_blur(self, event: Blur) -> None:
        """Handle blur events - hide cursor when table loses focus."""
        if isinstance(event.widget, DataTable) and event.widget.id == "clients_table":
            event.widget.show_cursor = False

    def on_mouse_down(self, event: MouseDown) -> None:
        """Handle mouse clicks - ensure table shows cursor when clicked."""
        widget = self.get_widget_at(event.screen_x, event.screen_y)[0]
        if isinstance(widget, DataTable) and widget.id == "clients_table":
            widget.show_cursor = True
            widget.focus()

    def _generate_all_files_worker(self) -> None:
        """Worker that calls existing generation modules (synchronous).

        IMPORTANT: This is a synchronous function (not async def) because:
        - It runs in a thread (thread=True in run_worker)
        - The existing generation modules are synchronous
        - File I/O is inherently blocking anyway

        Calls:
        - config_generation.generate_gatekit_config()
        - migration_instructions.generate_migration_instructions()
        - restore_scripts.generate_restore_scripts()

        Does NOT reimplement file writing logic - delegates to existing modules.

        Raises:
            Exception: If file generation fails
        """
        # Clear result lists from any previous attempts (for retry scenarios)
        # This prevents duplicates and stale errors on retries
        self.state.created_files.clear()
        self.state.generation_errors.clear()
        self.state.migration_instructions.clear()

        # Get selected clients for migration
        all_selected_clients = self.state.get_selected_clients()

        # Debug logging
        from ...debug import get_debug_logger
        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "client_selection_filtering",
                screen=self,
                context={
                    "all_selected_clients_count": len(all_selected_clients),
                    "all_selected_clients": [
                        {
                            "client_type": str(c.client_type),
                            "server_count": len(c.servers),
                            "server_names": [s.name for s in c.servers],
                        }
                        for c in all_selected_clients
                    ],
                    "selected_server_names": list(self.state.selected_server_names),
                }
            )

        # Filter each client's servers to only include selected ones
        # We need TWO lists:
        # - filtered_clients: For config generation and restore (only selected servers)
        # - all_selected_clients: For migration instructions (need all servers for "preserve" messaging)
        filtered_clients = []
        for client in all_selected_clients:
            # Filter servers to only those the user selected
            filtered_servers = [
                server for server in client.servers
                if server.name in self.state.selected_server_names
            ]

            # Create a new DetectedClient with filtered servers
            # Use dataclass replace to preserve all other fields
            from dataclasses import replace
            filtered_client = replace(client, servers=filtered_servers)
            filtered_clients.append(filtered_client)

        # Debug logging after filtering
        if logger:
            logger.log_event(
                "client_selection_after_filtering",
                screen=self,
                context={
                    "filtered_clients_count": len(filtered_clients),
                    "filtered_clients": [
                        {
                            "client_type": str(c.client_type),
                            "server_count": len(c.servers),
                            "server_names": [s.name for s in c.servers],
                            "stdio_server_count": len(c.get_stdio_servers()),
                        }
                        for c in filtered_clients
                    ],
                }
            )

        # Generate Gatekit configuration (use filtered clients - only selected servers)
        config_result = generate_gatekit_config(filtered_clients)
        config_path = self.state.config_path

        # Write config to file using centralized save_config
        from ...guided_setup.config_generation import generate_config_header
        from gatekit.config.persistence import save_config

        header = generate_config_header(config_result.stdio_servers)
        save_config(
            config_path,
            config_result.config,
            allow_incomplete=False,  # Guided setup generates complete configs
            header=header,
            atomic=True,  # Use atomic writes for safety
        )

        # Track created files
        self.state.created_files.append(config_path)

        # Locate gatekit-gateway executable
        gateway_path = locate_gatekit_gateway()

        # Generate migration instructions (use unfiltered clients - need all servers for "preserve" messaging)
        migration_instructions = generate_migration_instructions(
            all_selected_clients, self.state.selected_server_names, gateway_path, config_path
        )
        self.state.migration_instructions = migration_instructions

        # Generate restore scripts (use filtered clients - only restore servers that were actually migrated)
        if self.state.restore_dir:
            restore_scripts = generate_restore_scripts(filtered_clients, self.state.restore_dir)
            # Store mapping of client type to restore script path (for ClientSetupScreen)
            self.state.restore_script_paths = restore_scripts
            # Add restore script paths to created_files
            self.state.created_files.extend(restore_scripts.values())

    @on(Button.Pressed, "#next")
    async def on_next(self) -> None:
        """Generate files via worker and advance to completion screen."""
        # Use the current restore path from state
        self.state.restore_dir = self._current_restore_path
        # Restore script generation is now mandatory
        self.state.generate_restore = True

        try:
            # Spawn thread worker (synchronous function in thread)
            # Note: thread=True means run in thread, exclusive=True means only one worker
            worker = self.run_worker(self._generate_all_files_worker, thread=True, exclusive=True)
            await worker.wait()

            # Check if worker raised an exception
            if worker.error:
                raise worker.error

            # Advance to completion screen
            self.dismiss(ScreenResult(action=NavigationAction.CONTINUE, state=self.state))

        except Exception as e:

            # Show error notification
            self.notify("File generation failed", severity="error", timeout=5)

            # Log error to state
            self.state.generation_errors.append(str(e))

            # Show error modal with details
            # Note: For now we just show notification, ErrorModal will be added if needed
            self.notify(
                f"Failed to generate configuration files:\n\n{str(e)}",
                severity="error",
                timeout=10,
            )
            # Don't dismiss screen - user can retry or go back

    @on(Button.Pressed, "#back")
    def on_back(self) -> None:
        """Handle back button."""
        self.dismiss(ScreenResult(action=NavigationAction.BACK, state=self.state))

    @on(Button.Pressed, "#cancel")
    def on_cancel_button(self) -> None:
        """Handle cancel button."""
        self.dismiss(ScreenResult(action=NavigationAction.CANCEL, state=None))

    def action_cancel(self) -> None:
        """Handle escape key - cancel wizard."""
        self.dismiss(ScreenResult(action=NavigationAction.CANCEL, state=None))

    @on(Button.Pressed, "#change_restore_location")
    async def on_change_restore_location(self) -> None:
        """Handle change restore location button - open directory picker."""
        # Determine initial directory from current path
        current_path = Path(self._current_restore_path)
        # Use current path if it exists, otherwise use parent or cwd
        if current_path.exists():
            initial_location = current_path
        elif current_path.parent.exists():
            initial_location = current_path.parent
        else:
            initial_location = Path.home() / "Documents"

        # Ensure location is absolute
        if not initial_location.is_absolute():
            initial_location = Path.cwd() / initial_location

        # Open directory picker
        try:
            selected_path = await self.app.push_screen_wait(
                SelectDirectory(
                    location=initial_location,
                    title="Select Restore Scripts Directory",
                )
            )

            # Update path if user selected a directory (not cancelled)
            if selected_path is not None:
                self._current_restore_path = selected_path
                # Update the display
                path_display = self.query_one("#restore_path_display", Static)
                path_display.update(f"  {selected_path}")
        except Exception as e:
            self.notify(f"Failed to open directory picker: {e}", severity="error")

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

    def on_key(self, event: Key) -> None:
        """Handle keyboard navigation between table, change location button, and action buttons."""
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
                        change_btn = self.query_one("#change_restore_location", Button)
                        change_btn.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

        # Handle up arrow navigation from Change Location button to table
        elif event.key == "up":
            if isinstance(focused, Button) and focused.id == "change_restore_location":
                # Move focus to table (last row) and show cursor
                try:
                    table = self.query_one("#clients_table", DataTable)
                    if table.row_count > 0:
                        table.show_cursor = True
                        table.focus()
                        table.move_cursor(row=table.row_count - 1)
                        event.prevent_default()
                        event.stop()
                except Exception:
                    pass
            # Handle up arrow navigation from Back/Cancel/Next buttons to Change Location button
            elif isinstance(focused, Button) and focused.id in ("back", "cancel", "next"):
                try:
                    change_btn = self.query_one("#change_restore_location", Button)
                    change_btn.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass

        # Handle down arrow navigation from Change Location button to Next button
        elif event.key == "down":
            if isinstance(focused, Button) and focused.id == "change_restore_location":
                try:
                    next_btn = self.query_one("#next", Button)
                    next_btn.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            # Handle down arrow on Back/Cancel/Next buttons (block wrap-around)
            elif isinstance(focused, Button) and focused.id in ("back", "cancel", "next"):
                event.prevent_default()
                event.stop()

        # Handle left/right arrow navigation between buttons
        elif event.key == "left":
            if isinstance(focused, Button):
                if focused.id == "next":
                    # Left from Next -> Cancel
                    try:
                        self.query_one("#cancel", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "cancel":
                    # Left from Cancel -> Back
                    try:
                        self.query_one("#back", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "change_restore_location":
                    # Left from Change Location -> Back
                    try:
                        self.query_one("#back", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
        elif event.key == "right":
            if isinstance(focused, Button):
                if focused.id == "back":
                    # Right from Back -> Cancel
                    try:
                        self.query_one("#cancel", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "cancel":
                    # Right from Cancel -> Next
                    try:
                        self.query_one("#next", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "change_restore_location":
                    # Right from Change Location -> Next
                    try:
                        self.query_one("#next", Button).focus()
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
