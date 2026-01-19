"""Configuration error modal for displaying config errors with recovery options."""

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import Button, Static
from textual.screen import ModalScreen
from textual.binding import Binding

from gatekit.config.errors import ConfigError
from gatekit.tui.widgets.selectable_static import SelectableStatic


class ConfigErrorModal(ModalScreen[str]):
    """Minimal modal for config errors with basic recovery."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        # Note: Ctrl+Q quit is built into Textual App class
        Binding("left", "focus_previous", "Previous Button"),
        Binding("right", "focus_next", "Next Button"),
    ]

    CSS = """
    ConfigErrorModal {
        align: center middle;
    }

    ConfigErrorModal > .dialog {
        align: center middle;
    }

    .dialog {
        width: 70;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: $error;
        border: heavy $error-darken-1;
        padding: 1;
    }

    .error-title {
        text-align: center;
        margin-bottom: 1;
        color: $text;
        text-style: bold;
        height: auto;
    }

    .error-content-scroll {
        height: auto;
        margin-bottom: 1;
        border: none;
        background: transparent;
    }

    .error-location {
        text-align: center;
        color: $text;
        margin-bottom: 1;
        height: auto;
    }

    .error-problem {
        color: $text;
        margin-bottom: 1;
        height: auto;
    }

    .error-line {
        color: $text-muted;
        margin-bottom: 1;
        text-style: italic;
        height: auto;
    }

    .error-suggestions {
        color: $text;
        margin-bottom: 1;
        height: auto;
    }

    .suggestion-item {
        color: $text-muted;
        height: auto;
    }

    .button-row {
        align: center middle;
        height: 3;
    }

    Button {
        margin: 0 1;
    }
    """

    def __init__(self, config_error: ConfigError):
        super().__init__()
        self.config_error = config_error

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            # Fixed title at top (outside scroll area)
            yield Static("❌ Configuration Error", classes="error-title")

            # Scrollable content area for error details
            with VerticalScroll(classes="error-content-scroll", can_focus=False):
                # Location info (if available)
                if self.config_error.file_path:
                    location = f"📍 {self.config_error.file_path.name}"
                    if self.config_error.line_number:
                        location += f", line {self.config_error.line_number}"
                    if self.config_error.field_path:
                        location += f" ({self.config_error.field_path})"
                    yield SelectableStatic(location, classes="error-location")

                # Problem (selectable for copying to support)
                yield SelectableStatic(
                    f"Problem: {self.config_error.message}", classes="error-problem"
                )

                # Line snippet for YAML errors (proper field, no hasattr needed)
                if (
                    self.config_error.error_type == "yaml_syntax"
                    and self.config_error.line_snippet
                ):
                    yield SelectableStatic(
                        f"Line: {self.config_error.line_snippet}", classes="error-line"
                    )

                # Suggestions (max 3)
                if self.config_error.suggestions:
                    yield Static("Suggestions:", classes="error-suggestions")
                    for suggestion in self.config_error.suggestions:
                        yield Static(f"• {suggestion}", classes="suggestion-item")

            # Fixed buttons at bottom (outside scroll area)
            with Horizontal(classes="button-row"):
                yield Button("Copy Error", id="copy_error")
                yield Button("Cancel", id="cancel")
                yield Button("Quit", id="quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "copy_error":
            self._copy_error_to_clipboard()
            return  # Don't dismiss the modal
        self.dismiss(event.button.id)

    def _copy_error_to_clipboard(self) -> None:
        """Copy the full error message to clipboard."""
        from .clipboard import copy_to_clipboard, is_ssh_session, SSH_CLIPBOARD_HINT, SSH_CLIPBOARD_TOAST_TIMEOUT

        # Build a complete error message for support
        error_parts = ["Configuration Error"]

        if self.config_error.file_path:
            location = f"File: {self.config_error.file_path}"
            if self.config_error.line_number:
                location += f", line {self.config_error.line_number}"
            if self.config_error.field_path:
                location += f" ({self.config_error.field_path})"
            error_parts.append(location)

        error_parts.append(f"Problem: {self.config_error.message}")

        if (
            self.config_error.error_type == "yaml_syntax"
            and self.config_error.line_snippet
        ):
            error_parts.append(f"Line: {self.config_error.line_snippet}")

        if self.config_error.suggestions:
            error_parts.append("Suggestions:")
            for suggestion in self.config_error.suggestions:
                error_parts.append(f"  • {suggestion}")

        full_error = "\n".join(error_parts)

        # Copy to clipboard using shared utility
        success, error = copy_to_clipboard(self.app, full_error)

        if success:
            if is_ssh_session():
                self.notify(
                    f"✅ Error copied. Not working? {SSH_CLIPBOARD_HINT}",
                    timeout=SSH_CLIPBOARD_TOAST_TIMEOUT
                )
            else:
                self.notify("📋 Error message copied to clipboard")
        else:
            self.notify(f"❌ Copy failed: {error or 'Clipboard not available'}", severity="error")

    def action_cancel(self) -> None:
        """Handle Cancel action (Escape key)."""
        self.dismiss("cancel")

    def action_quit(self) -> None:
        """Handle Quit action (Ctrl+Q from Textual's built-in binding)."""
        self.dismiss("quit")

    def action_focus_previous(self) -> None:
        """Focus previous button (Left arrow)."""
        self.focus_previous()

    def action_focus_next(self) -> None:
        """Focus next button (Right arrow)."""
        self.focus_next()
