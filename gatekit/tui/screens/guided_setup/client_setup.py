"""Client Setup screen for Guided Setup - displays client setup instructions."""

import platform
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Union

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.widgets import Button, Static, Header, Footer, TextArea
from textual.screen import Screen
from textual.binding import Binding

from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions
from gatekit.tui.guided_setup.models import (
    GuidedSetupState,
    NavigationAction,
    ScreenResult,
    DetectedClient,
    ClientType,
)
from gatekit.tui.guided_setup.error_handling import EditorOpener
from gatekit.tui.guided_setup import client_registry
from gatekit.tui.widgets.selectable_static import SelectableStatic
from gatekit.tui.utils.terminal_compat import get_warning_icon


class ClipboardShortcutTextArea(TextArea):
    """TextArea that normalizes clipboard shortcuts and selection behavior.

    Adds a Ctrl+A binding for selecting all text and routes Ctrl+C through the
    provided clipboard helper so the flow can fall back to platform copy
    utilities on terminals where OSC 52 writes are unreliable.
    """

    BINDINGS = [
        *TextArea.BINDINGS,
        Binding("ctrl+a", "select_all", "Select all", show=False, priority=True),
    ]

    def __init__(
        self,
        *args,
        copy_handler: Callable[[str], None] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._copy_handler = copy_handler

    def _log_debug_event(self, event_type: str, **context: object) -> None:
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    event_type,
                    widget=self,
                    screen=self.screen,
                    context=context,
                )
        except Exception:
            pass

    def _run_copy_handler(self, text: str) -> bool:
        if self._copy_handler is None:
            return False

        self._log_debug_event(
            "clipboard_shortcut_copy_handler",
            text_preview=text[:60],
            length=len(text),
            handler=getattr(self._copy_handler, "__qualname__", str(self._copy_handler)),
        )
        self._copy_handler(text)
        return True

    def action_copy(self) -> None:
        """Copy selection via the provided helper with Textual fallback."""
        selected_text = self.selected_text

        if selected_text and self._run_copy_handler(selected_text):
            # Keep Textual's internal clipboard state in sync for widgets relying on it.
            TextArea.action_copy(self)
            return

        if selected_text:
            self._log_debug_event(
                "clipboard_shortcut_textual_fallback",
                selected=True,
                handler_present=self._copy_handler is not None,
            )
        TextArea.action_copy(self)

    def handle_smart_copy(self) -> bool:
        """Integrate with app-level smart copy pipeline."""
        selected_text = self.selected_text
        if not selected_text:
            self._log_debug_event("clipboard_shortcut_no_selection")
            return False

        if self._run_copy_handler(selected_text):
            return True

        self._log_debug_event(
            "clipboard_shortcut_textual_fallback",
            selected=True,
            handler_present=False,
        )
        TextArea.action_copy(self)
        return True


class ClientListItem(Static):
    """A selectable client list item in the master panel.

    Displays client name and warning indicator if already configured.
    Changes appearance when selected.

    Attributes:
        client_type: Type of MCP client
        is_already_configured: Whether client already uses Gatekit
    """

    DEFAULT_CSS = """
    ClientListItem {
        height: auto;
        padding: 1 2;
        background: $surface;
        color: $text;
    }

    ClientListItem.selected {
        background: $surface-lighten-2;
        color: $text;
        text-style: bold;
    }

    ClientListItem.selected:focus {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    ClientListItem:hover {
        background: $surface-lighten-1;
    }
    """

    # Enable keyboard focus for navigation
    can_focus = True

    def __init__(
        self,
        client_type: ClientType,
        is_already_configured: bool = False,
        **kwargs
    ):
        """Initialize client list item.

        Args:
            client_type: Type of MCP client
            is_already_configured: Whether client already uses Gatekit
            **kwargs: Additional arguments passed to Static
        """
        # Use platform-appropriate warning icon (with or without variation selector)
        icon = f"{get_warning_icon()}  " if is_already_configured else ""
        display_name = client_type.display_name()
        content = f"{icon}{display_name}"

        super().__init__(content, **kwargs)

        self.client_type = client_type
        self.is_already_configured = is_already_configured

    def on_click(self, event: Click) -> None:
        """Handle click to select this client.

        Args:
            event: Click event from Textual
        """
        self.post_message(self.ClientSelected(self.client_type))
        event.stop()  # Prevent event from bubbling to screen

    class ClientSelected(Message):
        """Message posted when client is selected.

        This message bubbles up to the screen to trigger selection.
        """

        def __init__(self, client_type: ClientType):
            super().__init__()
            self.client_type = client_type


class AlreadyConfiguredAlert(Container):
    """Alert box shown when client is already configured to use Gatekit.

    Shows warning message, explains situation, displays paths, and provides
    a copyable command to edit the existing Gatekit configuration in the TUI.

    Attributes:
        client_config_path: Path to client's MCP config file (e.g., claude_desktop_config.json)
        gatekit_config_path: Path to Gatekit config file the client is using
    """

    DEFAULT_CSS = """
    AlreadyConfiguredAlert {
        height: auto;
        border: solid $primary;
        background: $panel;
        padding: 1 2;
        margin-bottom: 2;
    }

    AlreadyConfiguredAlert .alert-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
        height: auto;
    }

    AlreadyConfiguredAlert .alert-message {
        color: $text;
        margin-bottom: 1;
        height: auto;
    }

    AlreadyConfiguredAlert .alert-message-tight {
        color: $text;
        margin-bottom: 0;
        height: auto;
    }

    AlreadyConfiguredAlert .config-path {
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }

    AlreadyConfiguredAlert .command-label {
        color: $text;
        margin-top: 0;
        margin-bottom: 0;
        height: auto;
    }

    AlreadyConfiguredAlert TextArea {
        height: 3;
        margin-top: 0;
        margin-bottom: 1;
    }
    """

    def __init__(self, client_config_path: Path, gatekit_config_path: str, **kwargs):
        """Initialize alert with config paths.

        Args:
            client_config_path: Path to client's MCP config file
            gatekit_config_path: Path to Gatekit config the client is using
            **kwargs: Additional arguments passed to Container
        """
        super().__init__(**kwargs)
        self.client_config_path = client_config_path
        self.gatekit_config_path = gatekit_config_path

    def compose(self) -> ComposeResult:
        """Build alert widget content."""
        yield SelectableStatic(f"{get_warning_icon()}  Already Using Gatekit", classes="alert-title")
        yield SelectableStatic(
            "This client is currently configured to use Gatekit via:",
            classes="alert-message"
        )
        yield SelectableStatic(str(self.client_config_path), classes="config-path")
        yield SelectableStatic(
            "You may either:\n"
            "1. Edit the existing Gatekit configuration by running:\n",
            classes="alert-message-tight"
        )

        # Show copyable command to open existing Gatekit config in TUI
        command = f"gatekit {self.gatekit_config_path}"
        yield ClipboardShortcutTextArea(
            command,
            read_only=True,
            show_line_numbers=False,
            id="gatekit_edit_command",
            copy_handler=lambda text: self.screen._copy_to_clipboard(text) if hasattr(self.screen, '_copy_to_clipboard') else None,
        )

        yield SelectableStatic(
            "   - OR -\n\n"
            "2. Follow instructions below to switch to the new Gatekit config",
            classes="alert-message-tight"
        )


class ClientSetupScreen(Screen[Union[ScreenResult, Optional[str]]]):
    """Client Setup screen showing setup instructions for each selected client.

    Contract:
    - Requires GuidedSetupState from ClientSelectionScreen
    - Returns ScreenResult with BACK/CONTINUE/CANCEL actions
    - BACK returns to ClientSelectionScreen
    - CONTINUE (Next button) proceeds to SetupCompleteScreen (summary)
    - CANCEL exits wizard
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+q", "cancel", "Cancel", priority=True),
        Binding("up", "focus_up", "Up", show=False),
        Binding("down", "focus_down", "Down", show=False),
        Binding("left", "focus_left", "Left", show=False),
        Binding("right", "focus_right", "Right", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]

    CSS = """
    ClientSetupScreen {
        align: center middle;
    }

    ClientSetupScreen .client-setup-container {
        width: 95%;
        height: 90%;
        background: $background;
        border: heavy $primary;
        padding: 1 2;
    }

    /* Screen title (matches wizard pattern) */
    ClientSetupScreen .screen-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        height: auto;
    }

    /* Screen description (matches wizard pattern) */
    ClientSetupScreen .screen-description {
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }

    /* Master-detail layout */
    ClientSetupScreen #master_detail {
        height: 1fr;
        layout: horizontal;
        margin-top: 0;
        margin-bottom: 0;
    }

    /* Master panel: Fixed width to accommodate client names */
    ClientSetupScreen #master_panel {
        width: 30;
        border-right: solid $primary;
        height: 100%;
    }

    /* Detail panel: Takes remaining space */
    ClientSetupScreen #detail_panel {
        width: 1fr;
        height: 100%;
        padding: 0 2;
    }

    ClientSetupScreen #detail_panel:focus {
        border-left: solid $accent;
    }

    /* Client list items */
    ClientSetupScreen ClientListItem {
        height: auto;
        padding: 1 2;
        background: $surface;
        color: $text;
    }

    ClientSetupScreen ClientListItem.selected {
        background: $surface-lighten-2;
        color: $text;
        text-style: bold;
    }

    ClientSetupScreen ClientListItem.selected:focus {
        background: $primary;
        color: $text;
        text-style: bold;
    }

    ClientSetupScreen ClientListItem:hover {
        background: $surface-lighten-1;
    }

    /* Detail panel content */
    ClientSetupScreen .client-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        height: auto;
    }

    ClientSetupScreen .client-config-path {
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }

    ClientSetupScreen .instruction-label {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
        margin-top: 1;
        height: auto;
    }

    ClientSetupScreen .helper-text {
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }

    ClientSetupScreen .helper-with-button {
        height: auto;
        margin-bottom: 1;
        align: left middle;
    }

    ClientSetupScreen .helper-text-inline {
        color: $text-muted;
        height: auto;
        width: auto;
        padding-right: 0;
    }

    ClientSetupScreen .restore-info {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 1;
        height: auto;
    }

    ClientSetupScreen .restart-note {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        margin-bottom: 2;
        height: auto;
    }

    ClientSetupScreen TextArea {
        height: auto;
        max-height: 15;
        margin-bottom: 1;
    }

    /* Action buttons */
    ClientSetupScreen .action-buttons {
        margin-bottom: 1;
        height: auto;
    }

    ClientSetupScreen .action-buttons Button {
        margin-right: 1;
    }

    ClientSetupScreen .path-button {
        width: auto;
        min-width: 15;
    }

    /* Bottom action bar (wizard-consistent) */
    ClientSetupScreen .bottom-actions {
        align: left middle;
        height: auto;
        margin-top: 1;
        padding-top: 1;
        border-top: solid $primary;
    }

    ClientSetupScreen .bottom-actions Button {
        margin: 0 1;
    }

    ClientSetupScreen .button-spacer {
        width: 1fr;
    }

    /* Empty state */
    ClientSetupScreen .empty-state {
        height: 1fr;
        align: center middle;
        padding: 4;
    }

    ClientSetupScreen .empty-state-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 2;
        height: auto;
    }

    ClientSetupScreen .empty-state-message {
        text-align: center;
        color: $text-muted;
        height: auto;
    }
    """

    def __init__(
        self,
        state: Optional[GuidedSetupState] = None,
        migration_instructions: Optional[List[MigrationInstructions]] = None,
        # Legacy parameters for backward compatibility
        gatekit_config_path: Optional[Path] = None,
        restore_script_dir: Optional[Path] = None,
    ) -> None:
        """Initialize setup complete screen.

        Args:
            state: State from ConfigurationSummaryScreen with created files (new flow)
            migration_instructions: List of migration instructions
            gatekit_config_path: Legacy parameter for old flow
            restore_script_dir: Legacy parameter for old flow
        """
        super().__init__()

        # Support both old and new calling patterns
        if state is not None:
            # New flow: use state
            self.state = state
            self.gatekit_config_path = state.config_path
            self.restore_script_dir = state.restore_dir if state.generate_restore else None
            # Use migration_instructions from state if available, otherwise fall back to parameter
            self.migration_instructions = state.migration_instructions or migration_instructions or []
            self.already_configured_clients = state.already_configured_clients or []
        else:
            # Old flow: use direct parameters
            self.state = None
            self.gatekit_config_path = gatekit_config_path
            self.restore_script_dir = restore_script_dir
            self.migration_instructions = migration_instructions or []
            self.already_configured_clients = []

        # Track selected client (index into migration_instructions)
        self.selected_client_index = 0 if self.migration_instructions else None

        # Track which client's content is currently displayed in detail panel
        # This prevents unnecessary rebuilds that cause duplicate ID errors
        self.displayed_client_index: Optional[int] = None

    def compose(self) -> ComposeResult:
        """Create setup complete screen layout with master-detail pattern."""
        yield Header()

        with Container(classes="client-setup-container"):
            # Screen title
            yield SelectableStatic("MCP Client Setup Instructions", classes="screen-title")

            # Description text
            yield SelectableStatic(
                "Use these instructions to configure your MCP clients to use Gatekit. "
                "Select a client from the list to view setup instructions for it.",
                classes="screen-description"
            )

            # Master-detail split (if we have migration instructions)
            if self.migration_instructions:
                with Horizontal(id="master_detail"):
                    # Master panel: List of clients
                    with VerticalScroll(id="master_panel"):
                        for instr in self.migration_instructions:
                            # Check if client is already configured
                            already_configured = self._is_client_already_configured(instr.client_type)
                            yield ClientListItem(
                                client_type=instr.client_type,
                                is_already_configured=already_configured is not None
                            )

                    # Detail panel: Instructions for selected client (starts empty, populated by _rebuild_detail_panel)
                    yield VerticalScroll(id="detail_panel")
            else:
                # Empty state: No clients selected
                with Container(classes="empty-state"):
                    yield SelectableStatic("No MCP clients selected", classes="empty-state-title")
                    yield SelectableStatic(
                        "Your Gatekit configuration is ready to use.\n"
                        "Configure MCP clients manually to use Gatekit.",
                        classes="empty-state-message"
                    )

            # Bottom action buttons
            with Horizontal(classes="bottom-actions"):
                yield Button("Back", id="back_button", variant="default")
                yield Static("", classes="button-spacer")
                yield Button("Cancel", id="cancel_button", variant="default")
                yield Button("Next", id="next_button", variant="primary")

        yield Footer()

    def _is_client_already_configured(self, client_type: ClientType) -> Optional[DetectedClient]:
        """Check if client is already configured to use Gatekit.

        Args:
            client_type: Type of MCP client to check

        Returns:
            DetectedClient if found in already_configured_clients, None otherwise
        """
        for client in self.already_configured_clients:
            if client.client_type == client_type:
                return client
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        button_id = event.button.id

        # Bottom action buttons
        if button_id == "back_button":
            if self.state is not None:
                self.dismiss(ScreenResult(
                    action=NavigationAction.BACK,
                    state=self.state
                ))
            else:
                # Old flow: return None
                self.dismiss(None)

        elif button_id == "cancel_button":
            if self.state is not None:
                self.dismiss(ScreenResult(
                    action=NavigationAction.CANCEL,
                    state=None
                ))
            else:
                # Old flow: return None
                self.dismiss(None)

        elif button_id == "next_button":
            if self.state is not None:
                # New flow: CONTINUE proceeds to SetupCompleteScreen (summary)
                self.dismiss(ScreenResult(
                    action=NavigationAction.CONTINUE,
                    state=self.state
                ))
            else:
                # Old flow: return string
                self.dismiss("done")

        # Legacy button support
        elif button_id == "test_connections":
            if self.state is not None:
                # New flow: return ScreenResult
                self.dismiss(
                    ScreenResult(action=NavigationAction.CONTINUE, state=self.state)
                )
            else:
                # Old flow: return string
                self.dismiss("test_connections")
        elif button_id == "done":
            if self.state is not None:
                # New flow: CONTINUE indicates user has acknowledged completion
                self.dismiss(
                    ScreenResult(action=NavigationAction.CONTINUE, state=self.state)
                )
            else:
                # Old flow: return string
                self.dismiss("done")

        # Client-specific buttons
        elif button_id.startswith("copy_snippet_"):
            index = int(button_id.split("_")[-1])
            snippet = self.migration_instructions[index].migration_snippet
            self._copy_to_clipboard(snippet)
        elif button_id.startswith("copy_client_path_"):
            index = int(button_id.split("_")[-1])
            path = str(self.migration_instructions[index].config_path)
            self._copy_to_clipboard(path)
        elif button_id.startswith("open_editor_"):
            index = int(button_id.split("_")[-1])
            config_path = self.migration_instructions[index].config_path
            self._open_in_editor(config_path)
        elif button_id.startswith("open_restore_"):
            index = int(button_id.split("_")[-1])
            client_type = self.migration_instructions[index].client_type
            # Use restore_script_paths from state (which includes timestamps)
            if self.state and client_type in self.state.restore_script_paths:
                restore_path = self.state.restore_script_paths[client_type]
                self._open_in_editor(restore_path)
            else:
                # This should not happen - restore scripts should always be generated
                self.notify(
                    f"Restore script path not found for {client_type.value}. "
                    "Please restart the guided setup.",
                    severity="error"
                )

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to clipboard and show notification.

        Args:
            text: Text to copy
        """
        from ...clipboard import copy_to_clipboard, is_ssh_session, SSH_CLIPBOARD_HINT, SSH_CLIPBOARD_TOAST_TIMEOUT
        from ...debug import get_debug_logger

        try:
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "guided_setup_copy_invoked",
                    screen=self,
                    widget=None,
                    context={
                        "text_preview": text[:60],
                        "length": len(text),
                    },
                )
        except Exception:
            pass

        success, error = copy_to_clipboard(self.app, text)

        if success:
            # Show a short preview of what was copied (not for SSH - too cluttered with hint)
            preview = text[:40] + "..." if len(text) > 40 else text
            preview = preview.replace("\n", " ")

            try:
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "guided_setup_copy_success",
                        screen=self,
                        context={"preview": preview, "is_ssh": is_ssh_session()},
                    )
            except Exception:
                pass

            if is_ssh_session():
                self.notify(
                    f"✅ Copied. Not working? {SSH_CLIPBOARD_HINT}",
                    timeout=SSH_CLIPBOARD_TOAST_TIMEOUT
                )
            else:
                self.notify(f"📋 Copied: {preview}")
        else:
            try:
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "guided_setup_copy_failed",
                        screen=self,
                        context={"error": error},
                    )
            except Exception:
                pass
            self.notify(f"Copy failed: {error}", severity="error")

    def _open_in_editor(self, file_path: Path) -> None:
        """Open file in user's default editor.

        Uses centralized EditorOpener for consistent behavior across the app.

        Args:
            file_path: Path to file to open
        """
        opener = EditorOpener()
        success, error = opener.open_file(file_path)

        if success:
            self.notify(f"Opened {file_path.name} in editor")
        else:
            self.notify(error or "Failed to open editor", severity="error")

    def _open_folder(self, folder_path: Path) -> None:
        """Open folder in file manager.

        Args:
            folder_path: Path to folder to open
        """
        try:
            system = platform.system()

            if system == "Darwin":  # macOS
                subprocess.Popen(["open", str(folder_path)])
                self.notify(f"Opened {folder_path.name} in Finder")
            elif system == "Linux":
                subprocess.Popen(["xdg-open", str(folder_path)])
                self.notify(f"Opened {folder_path.name} in file manager")
            elif system == "Windows":
                subprocess.Popen(["explorer", str(folder_path)])
                self.notify(f"Opened {folder_path.name} in Explorer")
            else:
                self.notify(
                    "Open folder not supported on this platform",
                    severity="warning",
                )

        except Exception as e:
            self.notify(
                f"Failed to open folder: {str(e)}",
                severity="error",
            )

    def on_mount(self) -> None:
        """Called when screen is mounted.

        Triggers initial selection to populate detail panel with first client's instructions.
        """
        # Diagnostic logging using TUI debug logger
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            # Build context info
            client_types = [instr.client_type.display_name() for instr in self.migration_instructions]
            already_configured = [str(client.client_type) for client in self.already_configured_clients]

            logger.log_event(
                "setup_complete_mount",
                screen=self,
                context={
                    "migration_instructions_count": len(self.migration_instructions),
                    "client_types": client_types,
                    "already_configured_count": len(self.already_configured_clients),
                    "already_configured_clients": already_configured,
                    "selected_client_index": self.selected_client_index,
                }
            )

        if self.selected_client_index is not None:
            # Trigger initial selection to populate detail panel and focus first client
            self._select_client(0)

    @on(ClientListItem.ClientSelected)
    def handle_client_selected(self, event: ClientListItem.ClientSelected) -> None:
        """Handle client selection from ClientListItem click or Enter key.

        Args:
            event: ClientSelected message containing the selected client type
        """
        # Find the index of the selected client type in migration_instructions
        for i, instr in enumerate(self.migration_instructions):
            if instr.client_type == event.client_type:
                self._select_client(i)
                break

    def _select_client(self, index: int, force_focus: bool = False) -> None:
        """Select a client and update UI.

        Args:
            index: Index into migration_instructions list
            force_focus: If True, always focus the selected item (used when navigating from buttons to master panel)
        """
        if index < 0 or index >= len(self.migration_instructions):
            return

        self.selected_client_index = index

        # Determine if we should move focus to the selected item
        # Only focus the item when:
        # 1. No widget currently has focus (initial mount), OR
        # 2. Focus is already in the master panel (user navigating list), OR
        # 3. force_focus is True (explicit navigation from buttons to master panel)
        # This allows navigating clients while keeping button focus (per NFR-1)
        focused = self.focused
        should_focus_item = focused is None or force_focus

        if not should_focus_item and focused is not None:
            # Check if focus is in master panel
            if isinstance(focused, ClientListItem):
                should_focus_item = True
            else:
                # Walk up parent tree to check if inside master panel
                try:
                    master_panel = self.query_one("#master_panel", VerticalScroll)
                    parent = focused.parent
                    while parent is not None:
                        if parent is master_panel:
                            should_focus_item = True
                            break
                        parent = parent.parent
                except Exception:
                    pass

        # Update master panel selection visual (and optionally focus)
        try:
            master_panel = self.query_one("#master_panel", VerticalScroll)
            items = list(master_panel.query(ClientListItem))
            for i, item in enumerate(items):
                if i == index:
                    item.add_class("selected")
                    # Only focus if appropriate (see logic above)
                    if should_focus_item:
                        item.focus()
                else:
                    item.remove_class("selected")
        except Exception:
            # Master panel not yet mounted, that's OK
            pass

        # Rebuild detail panel with selected client's instructions
        self.call_later(self._rebuild_detail_panel)

    def _rebuild_detail_panel(self) -> None:
        """Rebuild detail panel with selected client's instructions.

        Clears detail panel and remounts content for currently selected client.
        Note: This method uses synchronous mounting - Textual queues the widgets internally.
        """
        if self.selected_client_index is None:
            return

        # Skip rebuild if we're already displaying this client
        # This prevents duplicate ID errors when remove_children() hasn't completed yet
        if self.displayed_client_index == self.selected_client_index:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "rebuild_detail_panel_skipped",
                    screen=self,
                    context={
                        "selected_index": self.selected_client_index,
                        "reason": "already_displayed",
                    }
                )
            return

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()

            instr = self.migration_instructions[self.selected_client_index]
            detail_panel = self.query_one("#detail_panel", VerticalScroll)

            if logger:
                logger.log_event(
                    "rebuild_detail_panel_start",
                    screen=self,
                    context={
                        "selected_index": self.selected_client_index,
                        "client_type": str(instr.client_type),
                        "focused_widget": str(type(self.focused).__name__) if self.focused else None,
                        "focused_id": getattr(self.focused, "id", None) if self.focused else None,
                        "previously_displayed": self.displayed_client_index,
                    }
                )

            # Clear existing content
            detail_panel.remove_children()

            # Check if client is already configured
            already_configured = self._is_client_already_configured(instr.client_type)

            # Build list of widgets to mount
            widgets_to_mount = []

            # Already-configured alert (if applicable)
            if already_configured and already_configured.gatekit_config_path:
                widgets_to_mount.append(
                    AlreadyConfiguredAlert(
                        client_config_path=already_configured.config_path,
                        gatekit_config_path=already_configured.gatekit_config_path,
                        id=f"already_configured_alert_{self.selected_client_index}"
                    )
                )

            # Client header
            widgets_to_mount.append(SelectableStatic(
                f"Update {instr.client_type.display_name()}",
                classes="client-header"
            ))

            # Look up migration method from client registry (used in multiple places below)
            registry_entry = client_registry.get_registry_entry(instr.client_type)
            is_manual_edit = registry_entry and registry_entry.migration_method == "manual_edit"

            # Config path and editor actions (for manual-edit clients only)
            if is_manual_edit:
                widgets_to_mount.append(SelectableStatic(
                    str(instr.config_path),
                    classes="client-config-path"
                ))

                # Create action buttons container with buttons
                open_btn = Button(
                    "Open in Editor",
                    id=f"open_editor_{self.selected_client_index}",
                    variant="default",
                    classes="path-button"
                )
                copy_btn = Button(
                    "Copy Path",
                    id=f"copy_client_path_{self.selected_client_index}",
                    variant="default",
                    classes="path-button"
                )
                action_buttons = Horizontal(open_btn, copy_btn, classes="action-buttons")
                widgets_to_mount.append(action_buttons)

            # Instruction label
            if is_manual_edit:
                instruction_label = "Replace your entire config file with:"
                syntax_language = "json"  # manual_edit clients use JSON syntax
            else:
                # CLI-based migration
                shell_name = "PowerShell or Command Prompt" if platform.system() == "Windows" else "terminal"
                instruction_label = f"Run these commands in your {shell_name}:"
                syntax_language = "powershell" if platform.system() == "Windows" else "bash"

            widgets_to_mount.append(SelectableStatic(instruction_label, classes="instruction-label"))

            # TextArea with snippet

            textarea = ClipboardShortcutTextArea(
                instr.migration_snippet,
                language=syntax_language,
                read_only=True,
                show_line_numbers=False,
                theme="monokai",
                id=f"snippet_{self.selected_client_index}",
                copy_handler=self._copy_to_clipboard,
            )
            widgets_to_mount.append(textarea)

            # Helper text with inline copy button (for manual-edit clients)
            if is_manual_edit:
                helper_text = SelectableStatic(
                    "Select all (Ctrl+A) then copy (Ctrl+C) or ",
                    classes="helper-text-inline"
                )
                copy_btn = Button(
                    "Copy Config",
                    id=f"copy_snippet_{self.selected_client_index}",
                    variant="default",
                    compact=True
                )
                helper_container = Horizontal(helper_text, copy_btn, classes="helper-with-button")
                widgets_to_mount.append(helper_container)
            else:
                # For CLI clients, keep the copy button as a primary action button
                widgets_to_mount.append(Button(
                    "Copy Commands",
                    id=f"copy_snippet_{self.selected_client_index}",
                    variant="primary"
                ))

            # Restore instructions (if available)
            if self.state and instr.client_type in self.state.restore_script_paths:
                restore_path = self.state.restore_script_paths[instr.client_type]
                restore_text = f"ⓘ  To restore later: {restore_path}"
                widgets_to_mount.append(SelectableStatic(restore_text, classes="restore-info"))

                widgets_to_mount.append(Button(
                    "Open Restore Instructions",
                    id=f"open_restore_{self.selected_client_index}",
                    variant="default",
                    classes="path-button"
                ))

            # Restart note
            client_name = instr.client_type.display_name()
            widgets_to_mount.append(SelectableStatic(
                f"After updating, restart {client_name}",
                classes="restart-note"
            ))

            # Mount all widgets at once (synchronous - Textual queues internally)
            detail_panel.mount(*widgets_to_mount)

            # Reset scroll position to top after mounting new content
            # This prevents content from being scrolled out of view when switching clients
            detail_panel.scroll_home(animate=False)

            # Mark this client as currently displayed
            self.displayed_client_index = self.selected_client_index

            if logger:
                widget_summary = [type(w).__name__ for w in widgets_to_mount]
                logger.log_event(
                    "rebuild_detail_panel_complete",
                    screen=self,
                    context={
                        "widget_count": len(widgets_to_mount),
                        "widgets": widget_summary,
                        "displayed_client_index": self.displayed_client_index,
                    }
                )
        except Exception as e:
            # Detail panel not yet mounted or other error
            self.app.log.error(f"Exception in _rebuild_detail_panel: {e}", exc_info=True)
            if logger:
                logger.log_event(
                    "rebuild_detail_panel_error",
                    screen=self,
                    context={"error": str(e)}
                )

    def on_key(self, event: events.Key) -> None:
        """Handle keyboard navigation between client list, detail panel, and buttons.

        Navigation patterns:
        - Master panel: Up/Down to navigate between clients
        - Master panel: Right -> focus detail panel
        - Master panel: Down from last client -> focus Back button
        - Detail panel: Arrow keys navigate between widgets
          - Right/Down -> next widget (like Tab)
          - Left/Up -> previous widget (like Shift+Tab)
          - TextArea boundary detection:
            - Up from first line -> previous widget
            - Down from last line -> next widget
            - Otherwise, cursor moves within TextArea
        - Back button: Up -> focus last client in master panel
        - Cancel/Next button: Up -> focus detail panel
        - Action buttons: Left/Right to navigate between buttons
        - PageUp/PageDown: Scroll detail panel content

        Args:
            event: Key event from Textual
        """
        if not self.migration_instructions:
            return

        focused = self.focused

        # Debug logging for key events
        from ...debug import get_debug_logger
        logger = get_debug_logger()
        if logger and event.key in ("up", "down", "left", "right"):
            logger.log_event(
                "client_setup_key_navigation",
                screen=self,
                context={
                    "key": event.key,
                    "focused_widget": str(type(focused).__name__) if focused else None,
                    "focused_id": getattr(focused, "id", None) if focused else None,
                    "selected_client_index": self.selected_client_index,
                }
            )

        # Check if focus is in master panel (client list navigation context)
        is_in_master_panel = False
        is_in_detail_panel = False

        if isinstance(focused, ClientListItem):
            is_in_master_panel = True
        elif focused is not None:
            # Check if focused widget is a child of master_panel or detail_panel
            try:
                master_panel = self.query_one("#master_panel", VerticalScroll)
                detail_panel = self.query_one("#detail_panel", VerticalScroll)

                # Check if focus is the detail panel itself
                if focused is detail_panel:
                    is_in_detail_panel = True
                else:
                    # Walk up the widget tree to see if we're inside master or detail panel
                    parent = focused.parent
                    while parent is not None:
                        if parent is master_panel:
                            is_in_master_panel = True
                            break
                        elif parent is detail_panel:
                            is_in_detail_panel = True
                            break
                        parent = parent.parent
            except Exception:
                pass

        # Handle up arrow - only for master panel, detail panel, or button navigation
        if event.key == "up":
            if is_in_detail_panel:
                # In detail panel: up arrow acts like Shift+Tab
                # Special handling for TextArea: only navigate away if cursor is on first line
                if isinstance(focused, ClipboardShortcutTextArea):
                    # Check if cursor is on the first line
                    cursor_row, _ = focused.cursor_location
                    if cursor_row == 0:
                        # At top of TextArea, move to previous widget
                        self.focus_previous()
                        event.prevent_default()
                        event.stop()
                    # Otherwise, let TextArea handle the up arrow naturally
                else:
                    # Not a TextArea, navigate to previous widget
                    self.focus_previous()
                    event.prevent_default()
                    event.stop()
            elif is_in_master_panel:
                # In master panel - navigate to previous client
                if self.selected_client_index is not None and self.selected_client_index > 0:
                    self._select_client(self.selected_client_index - 1)
                    event.prevent_default()
                    event.stop()
            elif isinstance(focused, Button):
                if focused.id == "back_button":
                    # From Back button - move focus to last client in master pane
                    if self.selected_client_index is not None:
                        from ...debug import get_debug_logger
                        logger = get_debug_logger()
                        if logger:
                            logger.log_event(
                                "up_from_back_button",
                                screen=self,
                                context={
                                    "current_index": self.selected_client_index,
                                    "target_index": len(self.migration_instructions) - 1,
                                }
                            )
                        last_index = len(self.migration_instructions) - 1
                        self._select_client(last_index, force_focus=True)
                        event.prevent_default()
                        event.stop()
                elif focused.id in ("cancel_button", "next_button"):
                    # From Cancel or Next button - move focus to detail pane
                    try:
                        detail_panel = self.query_one("#detail_panel", VerticalScroll)
                        detail_panel.focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

        # Handle down arrow - only for master panel, detail panel, or button navigation
        elif event.key == "down":
            if is_in_detail_panel:
                # In detail panel: down arrow acts like Tab
                # Special handling for TextArea: only navigate away if cursor is on last line
                if isinstance(focused, ClipboardShortcutTextArea):
                    # Check if cursor is on the last line
                    cursor_row, _ = focused.cursor_location
                    line_count = focused.document.line_count
                    if cursor_row >= line_count - 1:
                        # At bottom of TextArea, move to next widget
                        self.focus_next()
                        event.prevent_default()
                        event.stop()
                    # Otherwise, let TextArea handle the down arrow naturally
                else:
                    # Not a TextArea, navigate to next widget
                    self.focus_next()
                    event.prevent_default()
                    event.stop()
            elif is_in_master_panel:
                # In master panel - navigate to next client or transition to buttons
                if self.selected_client_index is not None:
                    if self.selected_client_index < len(self.migration_instructions) - 1:
                        # Move to next client
                        self._select_client(self.selected_client_index + 1)
                        event.prevent_default()
                        event.stop()
                    else:
                        # On last client - move focus to Back button
                        try:
                            back_btn = self.query_one("#back_button", Button)
                            back_btn.focus()
                            event.prevent_default()
                            event.stop()
                        except Exception:
                            pass
            elif is_in_detail_panel:
                # From detail panel - move focus to Next button
                try:
                    next_btn = self.query_one("#next_button", Button)
                    next_btn.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            elif isinstance(focused, Button):
                if focused.id in ("back_button", "cancel_button", "next_button"):
                    # On buttons - either navigate clients or block wrap-around
                    if self.selected_client_index is not None and self.selected_client_index < len(self.migration_instructions) - 1:
                        # Allow navigating clients even from button focus
                        self._select_client(self.selected_client_index + 1)
                    # Always prevent default to block wrap-around
                    event.prevent_default()
                    event.stop()

        # Handle left arrow navigation
        elif event.key == "left":
            if is_in_detail_panel:
                # Temporary: In detail panel (but not TextArea), left arrow acts like Shift+Tab
                # TextArea needs arrow keys for cursor movement, so exclude it
                if not isinstance(focused, ClipboardShortcutTextArea):
                    self.focus_previous()
                    event.prevent_default()
                    event.stop()
            elif isinstance(focused, Button):
                if focused.id == "next_button":
                    # Left from Finish -> Cancel
                    try:
                        self.query_one("#cancel_button", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "cancel_button":
                    # Left from Cancel -> Back
                    try:
                        self.query_one("#back_button", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
        elif event.key == "right":
            if is_in_detail_panel:
                # Temporary: In detail panel (but not TextArea), right arrow acts like Tab
                # TextArea needs arrow keys for cursor movement, so exclude it
                if not isinstance(focused, ClipboardShortcutTextArea):
                    self.focus_next()
                    event.prevent_default()
                    event.stop()
            elif is_in_master_panel:
                # Right from master panel item - move focus to detail pane
                try:
                    detail_panel = self.query_one("#detail_panel", VerticalScroll)
                    detail_panel.focus()
                    event.prevent_default()
                    event.stop()
                except Exception:
                    pass
            elif isinstance(focused, Button):
                if focused.id == "back_button":
                    # Right from Back -> Cancel
                    try:
                        self.query_one("#cancel_button", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass
                elif focused.id == "cancel_button":
                    # Right from Cancel -> Finish
                    try:
                        self.query_one("#next_button", Button).focus()
                        event.prevent_default()
                        event.stop()
                    except Exception:
                        pass

        # Handle PageUp/PageDown for scrolling content (detail panel)
        elif event.key == "pageup":
            try:
                detail_scroll = self.query_one("#detail_panel", VerticalScroll)
                detail_scroll.scroll_page_up()
                event.prevent_default()
                event.stop()
            except Exception:
                pass
        elif event.key == "pagedown":
            try:
                detail_scroll = self.query_one("#detail_panel", VerticalScroll)
                detail_scroll.scroll_page_down()
                event.prevent_default()
                event.stop()
            except Exception:
                pass

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

    def action_cancel(self) -> None:
        """Handle cancel action (Escape key)."""
        if self.state is not None:
            # New flow: CANCEL exits wizard
            self.dismiss(
                ScreenResult(action=NavigationAction.CANCEL, state=None)
            )
        else:
            # Old flow: return None
            self.dismiss(None)
