"""Welcome screen for Gatekit TUI with recent files display."""

from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Header, Footer, DataTable
from textual.screen import Screen
from textual.binding import Binding
from textual.events import Key

from ..recent_files import RecentFiles, humanize_timestamp
from .simple_modals import ConfirmModal
from ..widgets.selectable_static import SelectableStatic


def truncate_long_path(path_str: str, max_length: int = 50) -> str:
    """Truncate long paths intelligently by collapsing the middle.

    Platform-agnostic - handles both Unix-style (/) and Windows-style (\\) paths.

    Examples:
        ~/very/long/path/to/configs/file.yaml -> ~/very/.../configs/file.yaml
        C:\\Users\\very\\long\\path\\file.yaml -> C:\\Users\\...\\path\\file.yaml

    Args:
        path_str: Path string to truncate
        max_length: Maximum length before truncation kicks in

    Returns:
        Truncated path with ellipsis in the middle if needed
    """
    if len(path_str) <= max_length:
        return path_str

    # Detect the separator used in the path (Windows \ or Unix /)
    separator = '\\' if '\\' in path_str else '/'

    # Split path into parts using the detected separator
    # This works cross-platform regardless of runtime OS
    parts = path_str.split(separator)

    # Handle absolute paths (Unix: /usr/local -> ['', 'usr', 'local'])
    # Keep the leading empty string for absolute paths, it will be joined back
    is_absolute_unix = (separator == '/' and parts and parts[0] == '')
    is_unc_path = (separator == '\\' and path_str.startswith('\\\\'))

    # For UNC paths, the first part after split is also empty \\server\share -> ['', '', 'server', 'share']
    # We want to keep the empty parts to reconstruct \\server later

    # Need at least 3 non-empty parts to truncate meaningfully (start, ..., end)
    # But count empty parts differently
    if is_unc_path:
        # UNC path needs at least 5 parts: ['', '', 'server', 'share', 'file']
        # to truncate to \\server\....\share\file
        if len(parts) < 5:
            return path_str
        # Keep first 3 parts (empty, empty, server) and last 2
        start_parts = parts[:3]
        end_parts = parts[-2:]
        start_idx = 3
    elif is_absolute_unix:
        # Unix absolute needs at least 4 parts: ['', 'usr', 'local', 'file']
        # to truncate to /usr/.../local/file
        if len(parts) < 4:
            return path_str
        # Keep first 2 parts (empty, first dir) and last 2
        start_parts = parts[:2]
        end_parts = parts[-2:]
        start_idx = 2
    else:
        # Regular relative or Windows paths need 3+ parts
        if len(parts) < 3:
            return path_str
        start_parts = [parts[0]]
        end_parts = parts[-2:]
        start_idx = 1

    # Try adding more parts from the start until we exceed length
    for i in range(start_idx, len(parts) - 2):
        candidate = separator.join(start_parts + [parts[i]] + ['...'] + end_parts)
        if len(candidate) <= max_length:
            start_parts.append(parts[i])
        else:
            break

    # Build final truncated path with original separator
    return separator.join(start_parts + ['...'] + end_parts)


def normalize_path_for_display(file_path: str) -> str:
    """Normalize file path for display following CWD-relative → ~ shortening pattern.

    Args:
        file_path: Absolute path to the file

    Returns:
        Normalized path string (relative to CWD if possible, otherwise ~ shortening),
        intelligently truncated if too long
    """
    path = Path(file_path)
    cwd = Path.cwd()

    # Try CWD-relative first
    try:
        rel_path = path.relative_to(cwd)
        normalized = str(rel_path)
    except ValueError:
        # Not relative to CWD, fall back to ~ shortening
        home = Path.home()
        try:
            rel_home = path.relative_to(home)
            normalized = f"~/{rel_home}"
        except ValueError:
            # Not under home either, return as-is
            normalized = str(path)

    # Truncate if needed
    return truncate_long_path(normalized)


class WelcomeScreen(Screen[Optional[str]]):
    """Welcome screen with recent files and action buttons.

    Returns:
        - Path string if user selects a recent file or "open_file"
        - "create_new" if user wants to create new config
        - "guided_setup" if user wants guided setup
        - None if user wants to quit
    """

    BINDINGS = [
        Binding("escape", "quit_app", "Quit", priority=True),
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        Binding("up", "focus_previous", "Previous", show=False),
        Binding("down", "focus_next", "Next", show=False),
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
    ]

    CSS = """
    WelcomeScreen {
        align: center middle;
    }

    WelcomeScreen .welcome-container {
        width: 80;
        height: auto;
        max-height: 90%;
        background: $background;
        border: heavy $primary;
        padding: 0;
    }

    WelcomeScreen .welcome-scroll {
        height: auto;
        max-height: 100%;
        padding: 2 3;
    }

    /* Hide welcome content when wizard is active to prevent flash during transitions */
    WelcomeScreen.wizard-active .welcome-container {
        display: none;
    }

    WelcomeScreen .welcome-header {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 2;
        height: auto;
    }

    WelcomeScreen .section-title {
        text-style: bold;
        color: $text;
        margin-top: 1;
        margin-bottom: 1;
        height: auto;
    }

    WelcomeScreen .table-container {
        height: auto;
        max-height: 30;
        margin-bottom: 1;
    }

    WelcomeScreen .recent-files-container {
        height: auto;
        max-height: 30;
        margin-bottom: 2;
    }

    WelcomeScreen #recent_files_table {
        height: auto;
        max-height: 100%;
    }

    WelcomeScreen .empty-state {
        text-align: center;
        color: $text-muted;
        margin: 2 0;
        height: auto;
    }

    WelcomeScreen .action-buttons {
        align: center middle;
        height: auto;
        margin-top: 1;
    }

    WelcomeScreen .action-buttons Button {
        margin: 0 1;
    }

    WelcomeScreen .action-buttons .clear-link {
        margin: 0;
    }

    WelcomeScreen .clear-link-container {
        align: right middle;
        height: auto;
        margin-top: 1;
        margin-bottom: 1;
    }

    WelcomeScreen .clear-link {
        width: auto;
        height: auto;
        min-width: 0;
        padding: 0;
        background: transparent;
        border: none;
        color: $text-muted;
        text-style: none;
    }

    WelcomeScreen .clear-link:hover {
        background: transparent;
        color: $text;
        text-style: underline;
    }

    WelcomeScreen .clear-link:focus {
        background: transparent;
        color: $accent;
        text-style: underline;
    }

    WelcomeScreen .link-prefix {
        color: $text-muted;
        height: auto;
        width: auto;
        margin-right: 0;
    }

    /* FR-3: Secondary button styling for Open File */
    WelcomeScreen #open_file {
        background: $secondary;
        color: $text;
        border: tall $secondary;
    }

    WelcomeScreen #open_file:hover {
        background: $secondary-lighten-1;
        border: tall $secondary-lighten-1;
    }

    WelcomeScreen #open_file:focus {
        background: $secondary-darken-1;
        border: tall $accent;
    }
    """

    def __init__(self) -> None:
        """Initialize welcome screen."""
        super().__init__()
        self.recent_files = RecentFiles()
        # Store mapping of row keys to file paths for lookup on selection
        self._row_to_path = {}
        # Track current sort column and direction
        self._sort_column = None
        self._sort_reverse = False

    def has_recent_files(self) -> bool:
        """Check if user has any recent files.

        Returns:
            True if recent files exist, False otherwise
        """
        return len(self.recent_files.get_all()) > 0

    def on_mount(self) -> None:
        """Set initial focus based on whether recent files exist."""
        if self.has_recent_files():
            # Focus the DataTable with cursor on first row for immediate Enter
            try:
                table = self.query_one("#recent_files_table", DataTable)
                table.focus()
                # Ensure cursor is on first row
                if table.row_count > 0:
                    table.move_cursor(row=0)
            except Exception:
                pass
        else:
            # No recent files - focus Guided Setup button
            self._focus_guided_setup()

    def compose(self) -> ComposeResult:
        """Create welcome screen layout."""
        yield Header()

        with Container(classes="welcome-container"):
            with VerticalScroll(classes="welcome-scroll"):
                yield SelectableStatic("Gatekit Configuration Editor", classes="welcome-header")

                # Recent files section
                recent_list = self.recent_files.get_all()

                if recent_list:
                    yield SelectableStatic("Recent Files", classes="section-title")

                    # Wrap table in container for dynamic sizing
                    with Container(classes="table-container"):
                        # Create DataTable with recent files
                        table = DataTable(id="recent_files_table", cursor_type="row")
                        table.add_columns("Filename", "Path", "Modified")

                        # Add rows for each recent file
                        for entry in recent_list:
                            parent_path = normalize_path_for_display(str(Path(entry['path']).parent))
                            time_ago = humanize_timestamp(entry['last_opened'])
                            row_key = table.add_row(
                                entry['display_name'],
                                parent_path,
                                time_ago
                            )
                            # Store mapping of row key to full file path
                            self._row_to_path[row_key] = entry['path']

                        yield table

                    # Clear recent files link right under the list
                    with Horizontal(classes="clear-link-container"):
                        yield Button("Clear recent files", id="clear_recent", classes="clear-link")
                else:
                    # First-run welcome message (FR-1: First-Run Welcome Experience)
                    # Kept compact so action buttons appear above the fold on default terminal size
                    yield SelectableStatic(
                        "No recent files\n\n"
                        "Guided Setup auto-detects MCP clients on your system.",
                        classes="empty-state",
                    )

                # Action buttons (FR-3: Button Hierarchy)
                # Priority order: Guided Setup (primary) → Open File (secondary via CSS) → Create New (link)
                with Horizontal(classes="action-buttons"):
                    yield Button("Guided Setup", id="guided_setup", variant="primary")
                    yield Button("Open File...", id="open_file", variant="default")  # Styled with $secondary via CSS

                # Create New as link-style (de-emphasized, outside action-buttons container)
                with Horizontal(classes="action-buttons"):
                    yield SelectableStatic("or", classes="link-prefix")
                    yield Button("create a blank configuration", id="create_new", classes="clear-link")

        yield Footer()

    def on_key(self, event: Key) -> None:
        """Handle keyboard navigation between table, clear link, and action buttons."""
        focused = self.focused

        # Handle down arrow when on the DataTable
        if event.key == "down" and isinstance(focused, DataTable):
            table = focused
            # Check if cursor is on the last row
            if table.cursor_row is not None and table.row_count > 0:
                if table.cursor_row == table.row_count - 1:
                    # On last row - move focus to "Clear recent files" link
                    try:
                        clear_button = self.query_one("#clear_recent", Button)
                        clear_button.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

        # Handle up arrow navigation
        elif event.key == "up":
            if isinstance(focused, Button) and focused.id == "clear_recent":
                # Move focus back to table (last row)
                try:
                    table = self.query_one("#recent_files_table", DataTable)
                    if table.row_count > 0:
                        table.focus()
                        event.prevent_default()
                        event.stop()
                except Exception:
                    pass
            # Up from "Guided Setup" or "Open File" goes to "Clear recent files"
            elif isinstance(focused, Button) and focused.id in ("guided_setup", "open_file"):
                try:
                    clear_button = self.query_one("#clear_recent", Button)
                    clear_button.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            # Up from "create_new" link goes to "Guided Setup" button
            elif isinstance(focused, Button) and focused.id == "create_new":
                try:
                    guided_setup_button = self.query_one("#guided_setup", Button)
                    guided_setup_button.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass

        # Handle down arrow navigation
        elif event.key == "down":
            if isinstance(focused, Button) and focused.id == "clear_recent":
                # Move focus to "Guided Setup" button
                try:
                    guided_setup_button = self.query_one("#guided_setup", Button)
                    guided_setup_button.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            # Down from "Guided Setup" or "Open File" goes to "create_new" link
            elif isinstance(focused, Button) and focused.id in ("guided_setup", "open_file"):
                try:
                    create_new_button = self.query_one("#create_new", Button)
                    create_new_button.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            # Block down arrow on "create_new" to prevent wrap-around
            elif isinstance(focused, Button) and focused.id == "create_new":
                event.prevent_default()
                event.stop()

        # Handle left/right arrow navigation between "Guided Setup" and "Open File"
        elif event.key in ("left", "right"):
            if isinstance(focused, Button):
                if focused.id == "guided_setup" and event.key == "right":
                    # Right from Guided Setup goes to Open File
                    try:
                        open_file_button = self.query_one("#open_file", Button)
                        open_file_button.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "open_file" and event.key == "left":
                    # Left from Open File goes to Guided Setup
                    try:
                        guided_setup_button = self.query_one("#guided_setup", Button)
                        guided_setup_button.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click - sort the table by that column."""
        table = event.data_table

        # Get column label and strip sort indicators (▲ or ▼)
        # event.label is a Rich Text object, so convert to plain string first
        column_label = str(event.label).replace(" ▲", "").replace(" ▼", "")

        # Toggle sort direction if clicking the same column, otherwise default to ascending
        if self._sort_column == column_label:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_label
            self._sort_reverse = False

        # Re-sort and rebuild the table
        self._rebuild_table_sorted(table)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle DataTable row selection - user clicked a recent file."""
        # Look up the file path for this row
        file_path = self._row_to_path.get(event.row_key)
        if file_path:
            self.dismiss(file_path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        button = event.button

        # Handle action buttons
        button_id = button.id
        if button_id == "open_file":
            self.dismiss("open_file")
        elif button_id == "create_new":
            self.dismiss("create_new")
        elif button_id == "guided_setup":
            # Launch the guided setup wizard
            self.run_worker(self._launch_guided_setup())
        elif button_id == "clear_recent":
            # Show confirmation dialog before clearing
            self.run_worker(self._confirm_and_clear_recent())

    def action_quit_app(self) -> None:
        """Handle quit action."""
        self.dismiss(None)

    async def _launch_guided_setup(self) -> None:
        """Launch the guided setup wizard and handle the result."""
        from .guided_setup import launch_guided_setup
        from .simple_modals import MessageModal

        # Hide welcome screen content during wizard to prevent flash during transitions
        self.add_class("wizard-active")

        try:
            config_path = await launch_guided_setup(self.app)
            if config_path:
                # Schedule info modal to appear after config editor loads
                def show_info_modal() -> None:
                    self.app.push_screen(
                        MessageModal(
                            title="Configuration Ready",
                            message=(
                                "You're now viewing the configuration you created. "
                                "Your MCP clients will use the Gatekit gateway with this config after you restart them.\n\n"
                                "From here you can:\n"
                                "• Add and remove MCP servers from this configuration\n"
                                "• Enable and disable functionality via plugins\n"
                                "• Configure security, middleware, and auditing plugins\n\n"
                                "Restart your MCP client(s) to apply changes.\n\n"
                                "To verify it's working: ask your AI to use an MCP tool, then ask "
                                '"what does the Gatekit call trace say" (make sure the Call Trace plugin is enabled).'
                            ),
                            button_delay=3,
                        )
                    )

                self.app.set_timer(2, show_info_modal)
                # User completed setup, load the config
                self.dismiss(str(config_path))
            else:
                # Wizard was cancelled, show welcome content again
                self.remove_class("wizard-active")
        except Exception:
            # On any error, restore welcome content
            self.remove_class("wizard-active")
            raise

    async def _confirm_and_clear_recent(self) -> None:
        """Show confirmation dialog and clear recent files if confirmed."""
        confirmed = await self.app.push_screen_wait(
            ConfirmModal(
                title="Clear Recent Files?",
                message="This will remove all recent files from the list.\n\nThe configuration files themselves will not be deleted.",
                confirm_label="Clear",
                cancel_label="Cancel",
                confirm_variant="warning",
            )
        )

        if confirmed:
            self.action_clear_recent()

    def action_clear_recent(self) -> None:
        """Clear recent files list and refresh the screen."""
        self.recent_files.clear()
        # Clear the row-to-path mapping
        self._row_to_path.clear()
        # Refresh the screen by recomposing
        self.refresh(recompose=True)
        # After refresh, the "Clear recent files" button no longer exists
        # Set focus to the "Guided Setup" button
        self.call_after_refresh(self._focus_guided_setup)

    def _focus_guided_setup(self) -> None:
        """Focus the Guided Setup button (helper for post-refresh focus restoration)."""
        try:
            guided_setup = self.query_one("#guided_setup", Button)
            guided_setup.focus()
        except Exception:
            # If button doesn't exist (shouldn't happen), just pass
            pass

    def _rebuild_table_sorted(self, table: DataTable) -> None:
        """Rebuild the table with sorted data.

        Args:
            table: The DataTable widget to rebuild
        """
        # Get all recent files
        recent_list = self.recent_files.get_all()

        # Define sort key functions for each column (without indicators)
        base_columns = ["Filename", "Path", "Modified"]
        sort_keys = {
            "Filename": lambda x: x['display_name'].lower(),
            "Path": lambda x: normalize_path_for_display(str(Path(x['path']).parent)).lower(),
            "Modified": lambda x: x['last_opened'],  # ISO timestamp sorts naturally
        }

        # Sort the list based on the selected column
        if self._sort_column and self._sort_column in base_columns:
            recent_list.sort(key=sort_keys[self._sort_column], reverse=self._sort_reverse)

        # Clear both rows AND columns (clear() only clears rows by default)
        table.clear(columns=True)
        self._row_to_path.clear()

        # Re-add columns with sort indicators
        sort_indicator = " ▼" if self._sort_reverse else " ▲"
        for col in base_columns:
            label = col + (sort_indicator if col == self._sort_column else "")
            table.add_column(label)

        # Re-add rows
        for entry in recent_list:
            parent_path = normalize_path_for_display(str(Path(entry['path']).parent))
            time_ago = humanize_timestamp(entry['last_opened'])
            row_key = table.add_row(
                entry['display_name'],
                parent_path,
                time_ago
            )
            # Store mapping of row key to full file path
            self._row_to_path[row_key] = entry['path']

    def action_focus_next(self) -> None:
        """Move focus to next button (down/right arrow)."""
        focusable = self._get_focusable_buttons()
        if not focusable:
            return

        current = self.focused
        if current in focusable:
            current_index = focusable.index(current)
            next_index = (current_index + 1) % len(focusable)
            focusable[next_index].focus()
        elif focusable:
            # Nothing focused, focus first button
            focusable[0].focus()

    def action_focus_previous(self) -> None:
        """Move focus to previous button (up/left arrow)."""
        focusable = self._get_focusable_buttons()
        if not focusable:
            return

        current = self.focused
        if current in focusable:
            current_index = focusable.index(current)
            prev_index = (current_index - 1) % len(focusable)
            focusable[prev_index].focus()
        elif focusable:
            # Nothing focused, focus last button
            focusable[-1].focus()

    def _get_focusable_buttons(self):
        """Get all focusable buttons in order (recent cards + action buttons)."""
        return [w for w in self.query("Button") if getattr(w, "can_focus", False)]
