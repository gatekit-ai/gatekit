"""Main Gatekit TUI application."""

from pathlib import Path
from typing import Optional
import signal

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Button
from textual.binding import Binding
from textual.events import Key

from gatekit.config.errors import ConfigError
from .screens.config_editor.base import PluginModalTarget
from .utils.terminal_compat import (
    has_limited_unicode_support,
    has_mac_terminal_block_gap_issue,
    configure_terminal_compatibility,
)

# Configure terminal compatibility before any widgets are created
# This sets up ASCII-compatible scrollbars for Windows cmd/PowerShell
configure_terminal_compatibility()


class GatekitConfigApp(App):
    """Main Gatekit configuration TUI application."""

    CSS = """
    /* Toast notification styling - make severities visually distinct */
    Toast.-success {
        border-left: outer $success;
    }
    Toast.-information {
        border-left: outer $primary;
    }
    Toast.-warning {
        border-left: outer $warning;
    }
    Toast.-error {
        border-left: outer $error;
    }

    /* Thin scrollbars globally */
    * {
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }

    .button-row {
        align: center middle;
        height: auto;
        margin-top: 2;
    }

    Button {
        margin: 0 1;
    }

    Button:hover {
        background: $primary;
        color: $background;
    }

    /* ASCII-compatible borders for terminals with limited Unicode support */
    /* (Windows cmd.exe and PowerShell with default fonts) */
    /* Uses !important to override screen-specific CSS rules */
    .-limited-unicode Button {
        border: none !important;
        border-top: solid $surface-lighten-1 !important;
        border-bottom: solid $surface-darken-1 !important;
    }

    .-limited-unicode Button:hover {
        border-top: solid $surface !important;
    }

    .-limited-unicode Button.-active {
        border-bottom: solid $surface-lighten-1 !important;
        border-top: solid $surface-darken-1 !important;
    }

    .-limited-unicode Button.-primary {
        border-top: solid $primary-lighten-3 !important;
        border-bottom: solid $primary-darken-3 !important;
    }

    .-limited-unicode Button.-primary:hover {
        border-top: solid $primary !important;
    }

    .-limited-unicode Button.-primary.-active {
        border-bottom: solid $primary-lighten-3 !important;
        border-top: solid $primary-darken-3 !important;
    }

    /* Restore no borders for compact buttons, pane header buttons, and link-styled buttons */
    .-limited-unicode Button.-textual-compact,
    .-limited-unicode Button.pane-header-button,
    .-limited-unicode Button.clear-link {
        border: none !important;
    }

    /* Use solid borders for file picker dialogs on terminals with block char issues */
    /* Windows legacy terminals can't render them; macOS Terminal.app shows gaps */
    .-limited-unicode FileSystemPickerScreen Input,
    .-mac-terminal FileSystemPickerScreen Input {
        border: solid $surface-lighten-3 !important;
    }

    .-limited-unicode FileSystemPickerScreen Input:focus,
    .-mac-terminal FileSystemPickerScreen Input:focus {
        border: solid $primary !important;
    }

    /* Use solid borders for TextArea - tall borders use fractional block elements that don't render */
    /* Windows legacy terminals can't render them; macOS Terminal.app shows gaps */
    .-limited-unicode TextArea,
    .-mac-terminal TextArea {
        border: solid $surface-lighten-3 !important;
    }

    .-limited-unicode TextArea:focus,
    .-mac-terminal TextArea:focus {
        border: solid $primary !important;
    }

    /* Use heavy borders instead of thick - box-drawing chars render better */
    /* across all terminals (thick uses full blocks █ which can have gaps) */

    /* Wizard screen containers (guided setup, client setup, etc.) */
    .wizard-screen .container {
        border: heavy $primary !important;
    }

    /* Welcome screen main container */
    WelcomeScreen .welcome-container {
        border: heavy $primary !important;
    }

    /* Modal dialogs */
    SimpleModal > Container,
    ConfirmModal > Container,
    TextInputModal > Container {
        border: heavy $primary !important;
    }

    ConfirmModal.-warning > Container {
        border: heavy $warning !important;
    }

    /* Plugin config modal */
    PluginConfigModal > Container {
        border: heavy $primary !important;
    }

    PluginConfigModal .validation-error-container {
        border: heavy $error !important;
    }

    /* Directory browser modal */
    DirectoryBrowserModal > Container {
        border: heavy $primary !important;
    }

    /* Config error modal */
    ConfigErrorModal > Container {
        border: heavy $error-darken-1 !important;
    }

    /* Client setup specific container */
    ClientSetupScreen .instructions-container {
        border: heavy $primary !important;
    }

    /* Welcome screen Open File button - use heavy instead of tall */
    WelcomeScreen #open_file {
        border: heavy $secondary !important;
    }

    WelcomeScreen #open_file:hover {
        border: heavy $secondary-lighten-1 !important;
    }

    WelcomeScreen #open_file:focus {
        border: heavy $accent !important;
    }
    """

    TITLE = "Gatekit Configuration Editor"
    SUB_TITLE = ""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),  # Override built-in to show in footer
        Binding("ctrl+c", "smart_copy", "Copy", show=True, priority=True),
        Binding("ctrl+o", "open_config", "Open Config", priority=True),
        Binding("ctrl+shift+d", "debug_state_dump", "Debug State Dump", priority=True, show=False),
        ("?", "help", "Help"),
    ]

    def __init__(
        self,
        config_path: Optional[Path] = None,
        tui_debug: bool = False,
        config_error: Optional[Exception] = None,
        initial_plugin_modal: Optional[PluginModalTarget] = None,
    ):
        """Initialize the TUI application.

        Args:
            config_path: Optional path to configuration file
            tui_debug: Whether TUI debug logging is enabled
            config_error: Optional config error to show immediately
            initial_plugin_modal: Optional plugin modal target to open on startup
        """
        super().__init__()
        self.tui_debug = tui_debug

        # Detect terminal with limited Unicode support and add CSS class
        # This enables ASCII-compatible border fallbacks for Windows cmd/PowerShell
        if has_limited_unicode_support():
            self.set_class(True, "-limited-unicode")

        # Detect macOS Terminal.app which has issues with fractional block characters
        # This switches 'tall' borders to 'solid' borders in file picker dialogs
        if has_mac_terminal_block_gap_issue():
            self.set_class(True, "-mac-terminal")

        self.config_error = config_error
        self.initial_plugin_modal = initial_plugin_modal
        self._help_panel_visible = False

        # If there's a config error, show config picker with error modal
        if config_error:
            self.should_show_config_picker = True
            self.should_show_config_editor = False
        else:
            self.should_show_config_picker = config_path is None
            self.should_show_config_editor = False

        # Override Ctrl+C signal handling to prevent accidental quit
        # CRITICAL: Never quit on SIGINT - only handle Ctrl+C through Textual's key events
        signal.signal(signal.SIGINT, self._handle_interrupt)

        # Resolve config path if provided
        if config_path:
            resolved_path = self._resolve_config_path(config_path)
            if resolved_path:
                self.config_path = resolved_path
                self.config_exists = True
                self.should_show_config_editor = True
                self.should_show_config_picker = False
            else:
                self.config_path = config_path
                self.config_exists = False
                self.config_error = f"Configuration file not found: {config_path}"
                self.should_show_config_picker = True
        else:
            self.config_path = None
            self.config_exists = False

    def compose(self) -> ComposeResult:
        """Compose the main application layout."""
        # Minimal layout - just header and footer since we navigate directly to other screens
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Handle app mounting - immediately show appropriate screen."""
        # Re-register signal handler after Textual initialization
        signal.signal(signal.SIGINT, self._handle_interrupt)

        if self.should_show_config_picker:
            # Show welcome screen with recent files
            self._show_welcome_screen()

            # If there's a config error, show error modal after welcome screen is loaded
            if self.config_error:
                # Schedule error modal to show after welcome screen is rendered
                self.call_later(self._show_initial_config_error)
        elif self.should_show_config_editor:
            # Show config editor immediately
            self._show_config_editor()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "exit":
            self.exit()

    def action_help(self) -> None:
        """Toggle the keys and help panel."""
        if self._help_panel_visible:
            self.action_hide_help_panel()
            self._help_panel_visible = False
        else:
            self.action_show_help_panel()
            self._help_panel_visible = True

    def on_key(self, event: Key) -> None:
        """Handle key events at app level."""
        # Debug logging for key events
        if self.tui_debug:
            from .debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_user_input(
                    input_type="keypress",
                    key=event.key,
                    screen=self.screen,
                    widget=self.focused,
                    screen_name=type(self.screen).__name__,
                    focused_widget=(
                        type(self.focused).__name__ if self.focused else None
                    ),
                )


    def _handle_smart_copy(self) -> bool:
        """Handle smart copy operation and return True if text was copied, False otherwise."""

        logger = None
        try:
            from .debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "smart_copy_attempt",
                    screen=self.screen,
                    widget=self.focused,
                    context={
                        "focused_widget": type(self.focused).__name__ if self.focused else None,
                    },
                )
        except Exception:
            logger = None

        # Check if focused widget is an Input with selected text
        from textual.widgets import Input

        focused = self.focused
        if isinstance(focused, Input) and focused.selected_text:
            from gatekit.tui.clipboard import (
                copy_to_clipboard,
                is_ssh_session,
                SSH_CLIPBOARD_HINT,
                SSH_CLIPBOARD_TOAST_TIMEOUT,
            )

            selected_text = focused.selected_text
            success, error = copy_to_clipboard(self, selected_text)

            if success:
                if logger:
                    logger.log_event(
                        "smart_copy_handled_input_widget",
                        screen=self.screen,
                        widget=focused,
                        context={"text_length": len(selected_text)},
                    )
                if is_ssh_session():
                    self.notify(
                        f"Copied. Not working? {SSH_CLIPBOARD_HINT}",
                        timeout=SSH_CLIPBOARD_TOAST_TIMEOUT,
                    )
                else:
                    preview = f'"{selected_text[:30]}{"..." if len(selected_text) > 30 else ""}"'
                    self.notify(f"Copied: {preview}")
                return True
            else:
                self.notify(
                    f"Copy failed: {error or 'Clipboard not available'}",
                    severity="error",
                )
                return False

        # Try the focused widget's handle_smart_copy method (SelectableStatic, etc.)
        if focused and hasattr(focused, "handle_smart_copy"):
            result = focused.handle_smart_copy()
            if result:
                if logger:
                    logger.log_event(
                        "smart_copy_handled_focused_widget",
                        screen=self.screen,
                        widget=focused,
                        context={"widget": type(focused).__name__},
                    )
                return True

        # If focused widget didn't work, search more thoroughly for SelectableStatic widgets
        from gatekit.tui.widgets.selectable_static import SelectableStatic

        # First, try searching from the focused widget if it exists (to find nested widgets)
        if focused:
            focused_selectables = focused.query(SelectableStatic)

            for _i, widget in enumerate(focused_selectables):
                if hasattr(widget, "handle_smart_copy"):
                    result = widget.handle_smart_copy()
                    if result:
                        if logger:
                            logger.log_event(
                                "smart_copy_handled_focused_descendant",
                                screen=self.screen,
                                widget=widget,
                                context={"widget": type(widget).__name__},
                            )
                        return True

        # Finally, search the entire screen tree for SelectableStatic widgets
        selectable_widgets = self.screen.query(SelectableStatic)

        for _i, widget in enumerate(selectable_widgets):
            if hasattr(widget, "handle_smart_copy"):
                result = widget.handle_smart_copy()
                if result:
                    if logger:
                        logger.log_event(
                            "smart_copy_handled_screen_widget",
                            screen=self.screen,
                            widget=widget,
                            context={"widget": type(widget).__name__},
                        )
                    return True
        if logger:
            logger.log_event(
                "smart_copy_not_handled",
                screen=self.screen,
                widget=self.focused,
            )
        return False

    def action_quit(self) -> None:
        """Handle quit action (Ctrl+Q).

        Checks for unsaved changes in ConfigEditorScreen if active.
        """
        # Run in a worker to allow push_screen_wait to work
        self.run_worker(self._quit_with_confirmation())

    async def _quit_with_confirmation(self) -> None:
        """Helper to quit with confirmation if needed.

        Checks for unsaved changes in ConfigEditorScreen and prompts user.
        """
        from .screens.config_editor import ConfigEditorScreen

        if isinstance(self.screen, ConfigEditorScreen):
            # Call the screen's async confirmation logic directly
            await self.screen._quit_with_confirmation()
        else:
            # No active config editor - quit normally
            self.exit()

    def action_smart_copy(self) -> None:
        """Smart copy action for Ctrl+C - copy selected text if available."""
        logger = None
        try:
            from .debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "app_ctrl_c_action",
                    screen=self.screen,
                    widget=self.focused,
                    context={
                        "focused_widget": type(self.focused).__name__ if self.focused else None,
                    },
                )
        except Exception:
            logger = None

        handled = self._handle_smart_copy()
        if not handled:
            if logger:
                logger.log_event(
                    "smart_copy_not_handled_action",
                    screen=self.screen,
                    widget=self.focused,
                )
            self.notify("Trying to quit? Use Ctrl+Q")

    def action_open_config(self) -> None:
        """Show config picker screen."""
        self._show_config_selector()

    def action_debug_state_dump(self) -> None:
        """Trigger a debug state dump."""
        if not self.tui_debug:
            return

        from .debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            # Get the current screen if available
            current_screen = None
            if hasattr(self, "screen") and self.screen:
                current_screen = self.screen
            elif hasattr(self, "screen_stack") and self.screen_stack:
                current_screen = self.screen_stack[-1] if self.screen_stack else None

            logger.dump_state(current_screen)

    def _resolve_config_path(self, config_path: Path) -> Optional[Path]:
        """Resolve configuration file path using exact path only.

        Args:
            config_path: The config path provided by the user

        Returns:
            The resolved absolute path if found, None otherwise
        """
        # Use exact path only for predictable behavior
        if config_path.exists():
            return config_path.resolve()

        # File not found
        return None

        # Smart resolution disabled for predictable behavior
        # Uncomment below to enable automatic checking of:
        # - configs/ subdirectory
        # - adding .yaml/.yml extensions
        #
        # # If not found and it's relative, try common locations
        # if not config_path.is_absolute():
        #     # Try in configs/ subdirectory
        #     configs_path = Path.cwd() / "configs" / config_path
        #     if configs_path.exists():
        #         return configs_path.resolve()
        #
        #     # Try with different extensions if no extension provided
        #     if not config_path.suffix:
        #         for ext in ['.yaml', '.yml']:
        #             # Try with extension in current directory
        #             path_with_ext = config_path.with_suffix(ext)
        #             if path_with_ext.exists():
        #                 return path_with_ext.resolve()
        #
        #             # Try with extension in configs/ directory
        #             configs_path_with_ext = Path.cwd() / "configs" / path_with_ext
        #             if configs_path_with_ext.exists():
        #                 return configs_path_with_ext.resolve()

    async def _open_config_file_async(self) -> None:
        """Show FileOpen modal and load selected config."""
        from textual_fspicker import FileOpen, Filters

        # Context-aware starting directory:
        # 1. If config already loaded, start where it is (better UX for switching configs)
        # 2. Otherwise, fall back to configs/ directory or cwd
        if self.config_path and self.config_path.parent.exists():
            start_dir = self.config_path.parent
        else:
            configs_dir = Path.cwd() / "configs"
            start_dir = configs_dir if configs_dir.exists() else Path.cwd()

        # Show FileOpen modal with YAML filters
        selected_path = await self.push_screen_wait(
            FileOpen(
                location=start_dir,
                title="Open Configuration File",
                filters=Filters(
                    ("YAML", lambda p: p.suffix.lower() in ['.yaml', '.yml']),
                    ("All", lambda _: True)
                )
            )
        )

        if selected_path:
            self._load_config(selected_path)
        else:
            # User cancelled
            from .screens.config_editor import ConfigEditorScreen

            # If we're in the config editor (including new documents), stay there
            if isinstance(self.screen, ConfigEditorScreen):
                return  # Just dismiss picker, keep editor open

            if not self.config_exists:
                # No config loaded and not in editor - return to welcome screen
                self._show_welcome_screen()
            # else: Config already loaded, just dismiss the picker (no action needed)

    def _show_welcome_screen(self) -> None:
        """Show welcome screen with recent files."""
        from .screens import WelcomeScreen

        def handle_welcome_result(result: Optional[str]) -> None:
            """Handle result from welcome screen."""
            if result is None:
                # User wants to quit
                self.exit()
            elif result == "open_file":
                # User wants to open a file
                self.run_worker(self._open_config_file_async())
            elif result == "create_new":
                # User wants to create new config
                self._create_new_config()
            else:
                # Result is a file path - user clicked a recent file
                self._load_config(Path(result))

        welcome_screen = WelcomeScreen()
        self.push_screen(welcome_screen, handle_welcome_result)

    def _create_new_config(self) -> None:
        """Create new configuration in editor (no file yet)."""
        from gatekit.config.models import ProxyConfig
        from .screens.config_editor import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()

        # NOTE: App-level state (self.config_path, self.config_exists) stays as-is
        # until first save. This is intentional - no file exists yet.
        # After first save, the editor updates these via callback (see config_persistence.py).

        editor_screen = ConfigEditorScreen(
            config_file_path=None,  # New document, no path yet
            loaded_config=empty_config,
            initial_plugin_modal=None,
        )
        self.push_screen(editor_screen)

    def _show_config_selector(self) -> None:
        """Show file picker modal to open a config."""
        if self.tui_debug:
            from .debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "show_config_selector",
                    screen=self.screen,
                    context={
                        "config_error": str(self.config_error) if self.config_error else None,
                        "config_path": str(self.config_path) if self.config_path else None,
                    },
                )
        self.run_worker(self._open_config_file_async())

    def _show_config_editor(self) -> None:
        """Show config editor screen directly with the specified config."""
        if self.tui_debug:
            from .debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "show_config_editor_start",
                    screen=self.screen,
                    context={
                        "config_path": str(self.config_path) if self.config_path else None,
                        "config_exists": self.config_exists,
                    },
                )

        if not self.config_path or not self.config_exists:
            # Fallback to config selector if something's wrong
            if self.tui_debug:
                from .debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "show_config_editor_fallback_to_selector",
                        screen=self.screen,
                        context={
                            "reason": "no config_path or config_exists is False",
                            "config_path": str(self.config_path) if self.config_path else None,
                            "config_exists": self.config_exists,
                        },
                    )
            self._show_config_selector()
            return

        try:
            from gatekit.config.loader import ConfigLoader
            from .screens.config_editor import ConfigEditorScreen

            # Load the configuration
            loader = ConfigLoader()
            loaded_config = loader.load_from_file(self.config_path)

            if self.tui_debug:
                from .debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "show_config_editor_loaded",
                        screen=self.screen,
                        context={
                            "config_path": str(self.config_path),
                        },
                    )

            # Open the config editor directly
            editor_screen = ConfigEditorScreen(
                self.config_path,
                loaded_config,
                initial_plugin_modal=self.initial_plugin_modal,
            )
            self.push_screen(editor_screen)

        except ConfigError as e:
            # Show the detailed error modal for config errors
            if self.tui_debug:
                from .debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "show_config_editor_config_error",
                        screen=self.screen,
                        context={
                            "error_type": "ConfigError",
                            "error": str(e),
                            "config_path": str(self.config_path),
                        },
                    )
            self._show_config_error_modal(e)

        except Exception as e:
            # If loading fails with other errors, show config selector with error context
            if self.tui_debug:
                from .debug import get_debug_logger
                import traceback
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "show_config_editor_exception",
                        screen=self.screen,
                        context={
                            "error_type": type(e).__name__,
                            "error": str(e),
                            "traceback": traceback.format_exc(),
                            "config_path": str(self.config_path),
                        },
                    )
            self.config_error = f"Error loading configuration: {e}"
            self.should_show_config_picker = True
            self.should_show_config_editor = False
            self._show_config_selector()

    def _handle_interrupt(self, signum, frame):
        """Handle SIGINT (Ctrl+C) - DO NOT EXIT.

        CRITICAL: We intercept SIGINT to prevent accidental quit when user wants to copy.
        All Ctrl+C handling is done through Textual's key event system in on_key().
        This handler exists only to prevent the default behavior (kill app).

        To quit, users must use: Ctrl+Q, Escape, or explicit quit buttons.
        """
        # Do nothing - let Textual handle Ctrl+C as a key event
        pass

    def _on_config_selected(self, selected_config: Optional[Path]) -> None:
        """Handle config selection from the config selector screen.

        Args:
            selected_config: The selected configuration file path, or None if cancelled
        """
        if selected_config:
            self._load_config(selected_config)
        else:
            # User cancelled - exit the app since there's nothing meaningful to show
            self.exit()

    def _on_config_picked(self, picked_config: Optional[Path | str]) -> None:
        """Handle config selection from the config picker modal.

        Args:
            picked_config: The selected configuration file path, special action string, or None
        """
        if picked_config is None:
            # User cancelled - exit the app since there's nothing meaningful to show
            self.exit()
            return

        if isinstance(picked_config, str):
            # Handle special actions - for now, just exit since these features aren't implemented
            self.exit()
        else:
            # Normal config file path
            self._load_config(picked_config)

    def _load_config(self, config_path: Path) -> None:
        """Load a configuration file and open the editor.

        Args:
            config_path: Path to the configuration file to load
        """
        if self.tui_debug:
            from .debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "load_config_start",
                    screen=self.screen,
                    context={
                        "config_path": str(config_path),
                    },
                )

        try:
            from gatekit.config.loader import ConfigLoader
            from .screens.config_editor import ConfigEditorScreen

            # Load the configuration
            loader = ConfigLoader()
            loaded_config = loader.load_from_file(config_path)

            if self.tui_debug:
                from .debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "load_config_success",
                        screen=self.screen,
                        context={
                            "config_path": str(config_path),
                        },
                    )

            # Update app state
            self.config_path = config_path
            self.config_exists = True
            self.config_error = None

            # Add to recent files
            from .recent_files import RecentFiles
            recent_files = RecentFiles()
            recent_files.add(config_path)

            # Open the config editor directly
            editor_screen = ConfigEditorScreen(
                config_path,
                loaded_config,
                initial_plugin_modal=self.initial_plugin_modal,
            )
            self.push_screen(editor_screen)

        except ConfigError as e:
            # Show the detailed error modal for config errors
            if self.tui_debug:
                from .debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "load_config_config_error",
                        screen=self.screen,
                        context={
                            "error_type": "ConfigError",
                            "error": str(e),
                            "config_path": str(config_path),
                        },
                    )
            self._show_config_error_modal(e)

        except Exception as e:
            # If loading fails with other errors, show config selector with error context
            if self.tui_debug:
                from .debug import get_debug_logger
                import traceback
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "load_config_exception",
                        screen=self.screen,
                        context={
                            "error_type": type(e).__name__,
                            "error": str(e),
                            "traceback": traceback.format_exc(),
                            "config_path": str(config_path),
                        },
                    )
            self.config_error = f"Error loading configuration: {e}"
            self._show_config_selector()

    def _show_initial_config_error(self) -> None:
        """Show the initial config error modal if there was one."""
        from gatekit.config.errors import ConfigError

        if self.config_error:
            # Convert Exception to ConfigError if needed
            if isinstance(self.config_error, ConfigError):
                self._show_config_error_modal(self.config_error)
            else:
                # Convert generic exception to ConfigError
                config_error = ConfigError(
                    message=str(self.config_error),
                    error_type="generic_error",
                    suggestions=["Check the configuration file for syntax errors"],
                )
                self._show_config_error_modal(config_error)

    def _show_config_error_modal(self, config_error: ConfigError) -> None:
        """Show the configuration error modal.

        Args:
            config_error: The configuration error to display
        """
        from .screens.config_error_modal import ConfigErrorModal

        def handle_modal_result(result: Optional[str]) -> None:
            """Handle the result from the config error modal."""
            self._handle_config_error_result(result, config_error)

        modal = ConfigErrorModal(config_error)
        self.push_screen(modal, handle_modal_result)

    def _handle_config_error_result(
        self, result: Optional[str], config_error: ConfigError
    ) -> None:
        """Handle the result from the config error modal.

        Args:
            result: The button that was pressed ("cancel" or "quit")
            config_error: The original configuration error
        """
        if result == "quit":
            # User wants to quit the app
            self.exit()
        else:
            # Cancel - show config picker so user can select a different config
            self._show_config_selector()

