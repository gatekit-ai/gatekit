"""Setup Complete screen - final configuration summary for Guided Setup."""

import platform
import subprocess
from pathlib import Path
from typing import Optional, Union

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key
from textual.widgets import Button, Static, Header, Footer
from textual.screen import Screen
from textual.binding import Binding

from gatekit.tui.guided_setup.models import GuidedSetupState, NavigationAction, ScreenResult
from gatekit.tui.guided_setup.error_handling import EditorOpener
from gatekit.tui.widgets.selectable_static import SelectableStatic


# Read shared wizard styles
with open(Path(__file__).parent.parent / "styles" / "wizard.tcss") as f:
    SHARED_WIZARD_CSS = f.read()


class FileLocationsSummary(Container):
    """Summary of created file locations displayed in summary screen.

    Shows gatekit config and restore scripts paths with action buttons.

    Attributes:
        config_path: Path to created gatekit.yaml
        restore_dir: Optional path to restore scripts directory
    """

    DEFAULT_CSS = """
    FileLocationsSummary {
        height: auto;
        background: $panel;
        border: solid $primary;
        padding: 1 2;
        margin-top: 1;
        margin-bottom: 1;
    }

    FileLocationsSummary .success-title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
        height: auto;
    }

    FileLocationsSummary .file-row {
        height: auto;
        align: left middle;
        margin-bottom: 0;
    }

    FileLocationsSummary .file-label {
        color: $text;
        text-style: bold;
        width: 20;
        height: auto;
        content-align: right middle;
    }

    FileLocationsSummary .path-display {
        color: $text-muted;
        width: auto;
        height: auto;
        content-align: left middle;
        margin-left: 1;
    }

    FileLocationsSummary .inline-button {
        width: auto;
        min-width: 0;
        height: 1;
        padding: 0 1;
        margin-left: 2;
    }
    """

    def __init__(
        self,
        config_path: Path,
        restore_dir: Optional[Path] = None,
        **kwargs
    ):
        """Initialize file locations summary.

        Args:
            config_path: Path to created gatekit.yaml
            restore_dir: Optional path to restore scripts directory
            **kwargs: Additional arguments passed to Container
        """
        super().__init__(**kwargs)
        self.config_path = config_path
        self.restore_dir = restore_dir

    def compose(self) -> ComposeResult:
        """Build file locations summary content."""
        yield SelectableStatic("✅ Configuration created successfully", classes="success-title")

        # Gatekit config row - label, path, and button all inline
        with Horizontal(classes="file-row"):
            yield SelectableStatic("Gatekit Config:", classes="file-label")
            yield SelectableStatic(str(self.config_path), classes="path-display")
            yield Button(
                "Open",
                id="open_config_file",
                variant="default",
                compact=True,
                classes="inline-button",
            )

        # Restore scripts row (if generated) - label, path, and button all inline
        if self.restore_dir:
            with Horizontal(classes="file-row"):
                yield SelectableStatic("Restore Scripts:", classes="file-label")
                yield SelectableStatic(str(self.restore_dir), classes="path-display")
                yield Button(
                    "Open",
                    id="open_restore_folder",
                    variant="default",
                    compact=True,
                    classes="inline-button",
                )


class SetupCompleteScreen(Screen[Union[ScreenResult, Optional[str]]]):
    """Final summary screen showing configuration results.

    Contract:
    - Requires GuidedSetupState from ClientSetupScreen
    - Returns ScreenResult with BACK/CONTINUE actions
    - BACK returns to ClientSetupScreen
    - CONTINUE (Finish button) indicates wizard completion
    """

    # Disable auto-focus to prevent scroll to first focusable widget
    AUTO_FOCUS = ""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("up", "focus_up", "Up", show=False),
        Binding("down", "focus_down", "Down", show=False),
        Binding("left", "focus_left", "Left", show=False),
        Binding("right", "focus_right", "Right", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]

    CSS = SHARED_WIZARD_CSS + """
    /* SetupCompleteScreen-specific styles for unified summary */

    SetupCompleteScreen .summary-section-title {
        text-style: bold;
        color: $text;
        margin-top: 1;
        margin-bottom: 0;
        height: auto;
    }

    SetupCompleteScreen .summary-section-description {
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }

    SetupCompleteScreen .plugin-description {
        color: $text;
        margin-top: 1;
        margin-bottom: 1;
        height: auto;
    }

    SetupCompleteScreen #summary_content {
        height: auto;
    }

    SetupCompleteScreen #config_details {
        margin-top: 1;
    }

    SetupCompleteScreen .file-row {
        height: auto;
        align: left middle;
        margin-bottom: 0;
    }

    SetupCompleteScreen .file-label {
        color: $text;
        text-style: bold;
        width: 20;
        height: auto;
        content-align: right middle;
    }

    SetupCompleteScreen .file-path {
        color: $text-muted;
        width: auto;
        height: auto;
        content-align: left middle;
        margin-left: 1;
    }

    SetupCompleteScreen .inline-button {
        width: auto;
        min-width: 0;
        height: 1;
        padding: 0 1;
        margin-left: 2;
    }
    """

    def __init__(
        self,
        state: Optional[GuidedSetupState] = None,
        gatekit_config_path: Optional[Path] = None,
        restore_script_dir: Optional[Path] = None,
        migration_instructions: Optional[list] = None,
    ):
        """Initialize Setup Complete screen.

        Supports both new state-based flow and legacy direct-attribute flow.

        Args:
            state: Wizard state from previous screen (new flow)
            gatekit_config_path: Path to created config (legacy flow)
            restore_script_dir: Path to restore scripts directory (legacy flow)
            migration_instructions: Legacy parameter (ignored, kept for backward compatibility)
        """
        super().__init__()
        self.state = state
        # migration_instructions parameter is accepted but ignored for backward compatibility
        # The new SetupCompleteScreen (summary) doesn't use migration instructions

        # Support both new state-based flow and legacy direct-attribute flow
        self.gatekit_config_path = state.config_path if state else gatekit_config_path
        self.restore_script_dir = state.restore_dir if state else restore_script_dir

    def compose(self) -> ComposeResult:
        """Create setup complete screen layout."""
        yield Header()

        with Container(classes="wizard-screen"):
            with Container(classes="container"):
                with VerticalScroll(id="content_scroll", can_focus=False):
                    # Screen title
                    yield SelectableStatic("Configuration Summary", classes="screen-title")

                    # Description
                    yield SelectableStatic(
                        "Your Gatekit configuration is ready. Review the details below.",
                        classes="screen-description"
                    )

                    # Success header
                    yield SelectableStatic("✅ Configuration Complete", classes="info-box-title")

                    # Default plugins info box (emphasized because automatic)
                    with Container(classes="info-box"):
                        yield SelectableStatic("Default Plugins Enabled", classes="info-box-title")
                        with Container(classes="info-box-content"):
                            yield SelectableStatic(
                                "These plugins help you understand what your MCP servers and clients are doing:",
                                classes="summary-section-description"
                            )
                            yield SelectableStatic(
                                "• Call Trace - Appends diagnostic info to tool responses showing which server handled the call, timing, and parameters. After a tool call, ask your LLM to list the Gatekit call trace",
                                classes="plugin-description"
                            )
                            yield SelectableStatic(
                                "• JSONL Auditing - Logs all MCP messages and plugin actions to logs/gatekit_audit.jsonl for auditing and debugging",
                                classes="plugin-description"
                            )

                    # Files created section (plain text - user already knows about these)
                    yield SelectableStatic("Files Created:", classes="summary-section-title")
                    with Container(id="summary_content"):
                        # Gatekit config row
                        with Horizontal(classes="file-row"):
                            yield SelectableStatic("Gatekit Config:", classes="file-label")
                            yield SelectableStatic(str(self.gatekit_config_path), classes="file-path")

                        # Restore scripts row (if generated)
                        if self.restore_script_dir:
                            with Horizontal(classes="file-row"):
                                yield SelectableStatic("Restore Scripts:", classes="file-label")
                                yield SelectableStatic(str(self.restore_script_dir), classes="file-path")
                                yield Button("Open", id="open_restore_folder", variant="default", compact=True, classes="inline-button")

                       
                    # Configuration summary (servers and clients - plain text)
                    yield SelectableStatic(self._build_summary_text(), id="config_details")

                # Action buttons (wizard pattern: Back ... Cancel ... Finish)
                with Horizontal(classes="buttons"):
                    yield Button("Back", id="back_button", variant="default")
                    yield Static("", classes="button-spacer")
                    yield Button("Cancel", id="cancel_button", variant="default")
                    yield Button("Finish", id="finish_button", variant="primary")

        yield Footer()

    def on_mount(self) -> None:
        """Set default focus to Finish button."""
        self.query_one("#finish_button", Button).focus()

    def on_key(self, event: Key) -> None:
        """Handle keyboard navigation between open buttons and action buttons."""
        focused = self.focused

        # Helper to get last open button (if any exist)
        def get_last_open_button() -> Optional[Button]:
            """Get the last available open button (restore folder only now)."""
            try:
                if self.restore_script_dir:
                    return self.query_one("#open_restore_folder", Button)
            except Exception:
                pass
            return None

        # UP arrow navigation
        if event.key == "up":
            if isinstance(focused, Button):
                button_id = focused.id

                # From action buttons -> last open button (if exists)
                if button_id in ("back_button", "cancel_button", "finish_button"):
                    last_open_btn = get_last_open_button()
                    if last_open_btn:
                        last_open_btn.focus()
                        event.prevent_default()
                        event.stop()
                    else:
                        # No open buttons - block
                        event.prevent_default()
                        event.stop()

                # From open_restore_folder -> block (already at top)
                elif button_id == "open_restore_folder":
                    event.prevent_default()
                    event.stop()

        # DOWN arrow navigation
        elif event.key == "down":
            if isinstance(focused, Button):
                button_id = focused.id

                # From open_restore_folder -> finish_button
                if button_id == "open_restore_folder":
                    self.query_one("#finish_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From action buttons -> block (no wrap-around)
                elif button_id in ("back_button", "cancel_button", "finish_button"):
                    event.prevent_default()
                    event.stop()

        # LEFT arrow navigation
        elif event.key == "left":
            if isinstance(focused, Button):
                button_id = focused.id

                # From open button -> back_button
                if button_id == "open_restore_folder":
                    self.query_one("#back_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From finish_button -> cancel_button
                elif button_id == "finish_button":
                    self.query_one("#cancel_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From cancel_button -> back_button
                elif button_id == "cancel_button":
                    self.query_one("#back_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From back_button -> block (already leftmost)
                elif button_id == "back_button":
                    event.prevent_default()
                    event.stop()

        # RIGHT arrow navigation
        elif event.key == "right":
            if isinstance(focused, Button):
                button_id = focused.id

                # From open button -> finish_button
                if button_id == "open_restore_folder":
                    self.query_one("#finish_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From back_button -> cancel_button
                elif button_id == "back_button":
                    self.query_one("#cancel_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From cancel_button -> finish_button
                elif button_id == "cancel_button":
                    self.query_one("#finish_button", Button).focus()
                    event.prevent_default()
                    event.stop()

                # From finish_button -> block (already rightmost)
                elif button_id == "finish_button":
                    event.prevent_default()
                    event.stop()

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

    def action_focus_up(self) -> None:
        """Move focus up (no-op, handled in on_key)."""
        pass

    def action_focus_down(self) -> None:
        """Move focus down (no-op, handled in on_key)."""
        pass

    def action_focus_left(self) -> None:
        """Move focus left (no-op, handled in on_key)."""
        pass

    def action_focus_right(self) -> None:
        """Move focus right (no-op, handled in on_key)."""
        pass

    def action_page_up(self) -> None:
        """Scroll page up (no-op, handled in on_key)."""
        pass

    def action_page_down(self) -> None:
        """Scroll page down (no-op, handled in on_key)."""
        pass

    def _build_summary_text(self) -> Text:
        """Build a copy-friendly Rich Text summary of configured servers and clients."""

        summary = Text()

        # Guard for legacy flow where state might be None
        if not self.state:
            return summary

        def append_line(content: str = "", *, style: str | None = None) -> None:
            if style:
                summary.append(content, style=style)
            else:
                summary.append(content)
            summary.append("\n")

        # Servers
        selected_servers = self.state.get_selected_servers()
        if selected_servers:
            append_line("Servers Configured:", style="bold")
            for dedupe in selected_servers:
                append_line(f"  • {dedupe.server.name}")
            summary.append("\n")

        # Clients
        selected_clients = self.state.get_selected_clients()
        if selected_clients:
            append_line("Clients Configured:", style="bold")
            for client in selected_clients:
                append_line(f"  • {client.client_type.display_name()}")

        return summary

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses.

        Args:
            event: Button pressed event
        """
        button_id = event.button.id

        if button_id == "back_button":
            # Return to ClientSetupScreen
            if self.state is not None:
                self.dismiss(ScreenResult(
                    action=NavigationAction.BACK,
                    state=self.state
                ))
            else:
                # Legacy flow: return None
                self.dismiss(None)

        elif button_id == "cancel_button":
            # Cancel wizard
            self.dismiss(ScreenResult(
                action=NavigationAction.CANCEL,
                state=None
            ))

        elif button_id == "finish_button":
            # Wizard completion
            if self.state is not None:
                self.dismiss(ScreenResult(
                    action=NavigationAction.CONTINUE,
                    state=self.state
                ))
            else:
                # Legacy flow: return string
                self.dismiss("done")

        # FileLocationsSummary buttons
        elif button_id == "open_restore_folder":
            restore_dir = self.state.restore_dir if self.state else self.restore_script_dir
            if restore_dir:
                self._open_folder(restore_dir)

    def action_cancel(self) -> None:
        """Handle escape key - cancel wizard."""
        self.dismiss(ScreenResult(
            action=NavigationAction.CANCEL,
            state=None
        ))

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
