"""Simple modal dialogs for plugin management UI."""

from typing import Optional, List, TYPE_CHECKING
from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, VerticalScroll
from textual.widgets import Button, Static
from textual.screen import ModalScreen
from textual.binding import Binding
from textual.events import Key

from ..widgets.selectable_static import SelectableStatic

if TYPE_CHECKING:
    from ...guided_setup.models import DetectedClient


class MessageModal(ModalScreen[None]):
    """Simple informational modal with title, body, and OK button."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("enter", "dismiss", "OK", priority=True),
    ]

    CSS = """
    MessageModal {
        align: center middle;
    }

    MessageModal > .dialog {
        width: 70;
        height: auto;
        max-height: 30;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }

    .message-title {
        text-align: center;
        margin-bottom: 1;
        color: $text;
        text-style: bold;
    }

    .message-body-scroll {
        height: auto;
        max-height: 20;
        margin-bottom: 2;
        border: none;
        background: $surface;
    }

    .message-body-text {
        color: $text;
        padding: 1;
    }

    .button-container {
        align: center middle;
        height: 3;
    }
    """

    def __init__(
        self, title: str, message: str, *, button_delay: Optional[float] = None
    ) -> None:
        """Initialize message modal.

        Args:
            title: Modal title
            message: Message body
            button_delay: Optional delay in seconds before OK button becomes active.
                          If set, the button starts disabled and escape/enter are blocked
                          until the delay expires.
        """
        super().__init__()
        self.title = title
        self.message = message
        self.button_delay = button_delay
        self._can_dismiss = button_delay is None

    def compose(self) -> ComposeResult:
        """Create message modal layout."""
        with Vertical(classes="dialog"):
            yield Static(self.title, classes="message-title")
            # Use VerticalScroll with Static for scrollable, selectable text
            with VerticalScroll(classes="message-body-scroll", can_focus=False):
                yield Static(self.message, classes="message-body-text")
            with Horizontal(classes="button-container"):
                yield Button(
                    "OK",
                    id="ok_btn",
                    variant="primary",
                    disabled=self.button_delay is not None,
                )

    def on_mount(self) -> None:
        """Set up delayed button enable if configured."""
        if self.button_delay is not None:
            self.set_timer(self.button_delay, self._enable_dismiss)

    def _enable_dismiss(self) -> None:
        """Enable the OK button and allow dismissal."""
        self._can_dismiss = True
        try:
            ok_btn = self.query_one("#ok_btn", Button)
            ok_btn.disabled = False
            ok_btn.focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if self._can_dismiss:
            self.dismiss(None)

    def action_dismiss(self) -> None:
        """Dismiss the modal (only if allowed)."""
        if self._can_dismiss:
            self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Confirmation modal returning True/False."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    CSS = """
    ConfirmModal {
        align: center middle;
    }

    ConfirmModal > .dialog {
        width: 60;
        height: auto;
        max-height: 20;
        background: $surface;
        border: heavy $warning;
        padding: 1 2;
    }

    .confirm-title {
        text-align: center;
        margin-bottom: 1;
        color: $text;
        text-style: bold;
    }

    .confirm-body {
        margin-bottom: 2;
        color: $text;
    }

    .button-container {
        align: center middle;
        height: 3;
    }

    .button-container Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        confirm_variant: str = "primary",
        cancel_variant: str = "default",
    ) -> None:
        """Initialize confirmation modal.

        Args:
            title: Modal title.
            message: Confirmation message body.
            confirm_label: Label text for the confirmation action button.
            cancel_label: Label text for the cancel action button.
            confirm_variant: Button variant to apply to the confirmation action.
            cancel_variant: Button variant to apply to the cancel action.
        """
        super().__init__()
        self.title = title
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label
        self.confirm_variant = confirm_variant
        self.cancel_variant = cancel_variant

    def compose(self) -> ComposeResult:
        """Create confirmation modal layout."""
        with Vertical(classes="dialog"):
            yield Static(self.title, classes="confirm-title")
            yield Static(self.message, classes="confirm-body")
            with Horizontal(classes="button-container"):
                yield Button(
                    self.confirm_label,
                    id="confirm_btn",
                    variant=self.confirm_variant,
                )
                yield Button(
                    self.cancel_label,
                    id="cancel_btn",
                    variant=self.cancel_variant,
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        result = event.button.id == "confirm_btn"
        self.app.log.info(f"ConfirmModal button pressed: {event.button.id} -> {result}")
        self.dismiss(result)

    def action_cancel(self) -> None:
        """Cancel action (triggered by escape key)."""
        self.app.log.info("ConfirmModal action_cancel called (escape key)")
        self.dismiss(False)

    def on_key(self, event: Key) -> None:
        """Handle key events for button navigation."""
        if event.key in ("left", "right", "up", "down"):
            focusable = self._get_focusable_buttons()
            if not focusable or len(focusable) < 2:
                return

            current = self.focused
            if current in focusable:
                current_index = focusable.index(current)
                if event.key in ("right", "down"):
                    next_index = (current_index + 1) % len(focusable)
                else:  # left or up
                    next_index = (current_index - 1) % len(focusable)
                focusable[next_index].focus()
            event.stop()

    def _get_focusable_buttons(self):
        """Get all focusable buttons in order."""
        return [w for w in self.query("Button") if getattr(w, "can_focus", False)]


class ActionMenuModal(ModalScreen[Optional[str]]):
    """Modal for selecting from multiple plugin actions."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    CSS = """
    ActionMenuModal {
        align: center middle;
    }

    ActionMenuModal > .dialog {
        width: 50;
        height: auto;
        max-height: 20;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }

    .modal-title {
        text-align: center;
        margin-bottom: 1;
        color: $text;
        text-style: bold;
    }

    .action-buttons {
        margin-top: 1;
    }

    .action-buttons Button {
        width: 100%;
        margin-bottom: 1;
    }
    """

    def __init__(self, actions: List[str], plugin_name: str) -> None:
        """Initialize action menu modal.

        Args:
            actions: List of available actions
            plugin_name: Name of the plugin for context
        """
        super().__init__()
        self.actions = actions
        self.plugin_name = plugin_name

    def compose(self) -> ComposeResult:
        """Create action menu modal layout."""
        with Vertical(classes="dialog"):
            yield Static(f"Choose action for {self.plugin_name}", classes="modal-title")
            with Container(classes="action-buttons"):
                for action in self.actions:
                    btn_id = f"action_{action.lower().replace(' ', '_')}"
                    variant = "primary" if action == "Configure" else "default"
                    yield Button(action, id=btn_id, variant=variant)
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            # Return the button label as the action
            self.dismiss(event.button.label)

    def action_cancel(self) -> None:
        """Cancel action."""
        self.dismiss(None)


class NoServersFoundModal(ModalScreen[None]):
    """Modal shown when guided setup discovers zero MCP servers.

    Dynamically builds the list of supported clients from the client registry,
    making it easy to keep the message up-to-date as new clients are added.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Exit Wizard", priority=True),
        Binding("enter", "dismiss", "OK", priority=True),
    ]

    CSS = """
    NoServersFoundModal {
        align: center middle;
    }

    NoServersFoundModal > .dialog {
        width: 75;
        height: auto;
        max-height: 35;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }

    .no-servers-title {
        text-align: center;
        margin-bottom: 1;
        color: $warning;
        text-style: bold;
    }

    .no-servers-body {
        color: $text;
        padding: 0 1;
    }

    .supported-clients-list {
        color: $text;
        padding-left: 2;
        margin-top: 1;
    }

    .manual-steps {
        color: $text;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 1;
    }

    .no-servers-buttons {
        align: center middle;
        height: 3;
    }
    """

    def __init__(self, supported_clients: List[str]) -> None:
        """Initialize modal with dynamic list of supported clients.

        Args:
            supported_clients: List of client display names (e.g., ["Claude Desktop", "Claude Code"])
        """
        super().__init__()
        self.supported_clients = supported_clients

    def compose(self) -> ComposeResult:
        """Create modal layout."""
        with Vertical(classes="dialog"):
            yield Static("No MCP Servers Detected", classes="no-servers-title")

            yield Static(
                "Guided Setup requires at least one MCP server configured\n"
                "in a supported client:",
                classes="no-servers-body"
            )

            # Build client list dynamically
            client_list = "\n".join(f"• {name}" for name in self.supported_clients)
            yield Static(client_list, classes="supported-clients-list")

            yield Static(
                "To configure Gatekit manually:\n"
                "1. Exit Guided Setup\n"
                "2. Select \"create a blank configuration\" from the welcome screen\n"
                "3. Press the \"+ Add\" button on the header of the MCP Servers panel\n"
                "4. Type or paste the command to start your MCP server. For example:\n"
                "   • uvx mcp-server-time\n"
                "   • npx -y @modelcontextprotocol/server-filesystem ~/Documents",
                classes="manual-steps"
            )

            with Horizontal(classes="no-servers-buttons"):
                yield Button("Exit", id="exit_btn", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(None)

    def action_dismiss(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)


class AllServersUsingGatekitModal(ModalScreen[None]):
    """Modal shown when all detected servers are already configured to use Gatekit.

    This is different from NoServersFoundModal - here we found servers, but they're
    all already proxied through Gatekit.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Exit Wizard", priority=True),
        Binding("enter", "dismiss", "OK", priority=True),
    ]

    CSS = """
    AllServersUsingGatekitModal {
        align: center middle;
    }

    AllServersUsingGatekitModal > .dialog {
        width: 75;
        height: auto;
        max-height: 30;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }

    .all-gatekit-title {
        text-align: center;
        margin-bottom: 1;
        color: $success;
        text-style: bold;
    }

    .all-gatekit-body {
        color: $text;
        padding: 0 1;
    }

    .all-gatekit-configs {
        color: $text;
        padding-left: 2;
        margin-top: 1;
    }

    .all-gatekit-steps {
        color: $text;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 1;
    }

    .all-gatekit-buttons {
        align: center middle;
        height: 3;
    }
    """

    def __init__(self, detected_clients: List["DetectedClient"]) -> None:
        """Initialize modal.

        Args:
            detected_clients: List of detected clients already using Gatekit
        """
        super().__init__()
        self.detected_clients = detected_clients

    def compose(self) -> ComposeResult:
        """Create modal layout."""
        server_count = sum(len(c.servers) for c in self.detected_clients)
        server_word = "server" if server_count == 1 else "servers"

        with Vertical(classes="dialog"):
            yield SelectableStatic("All Servers Already Using Gatekit", classes="all-gatekit-title")

            yield SelectableStatic(
                f"Found {server_count} MCP {server_word}, but all are already configured\n"
                "to use Gatekit as their gateway.",
                classes="all-gatekit-body"
            )

            # Show which clients are using which configs
            config_lines = self._build_config_list()
            if config_lines:
                yield SelectableStatic(config_lines, classes="all-gatekit-configs")

            yield SelectableStatic(
                "To edit your Gatekit configuration:\n"
                "1. Exit Guided Setup\n"
                "2. Click \"Open File...\" and open the config for the client(s) you want to edit",
                classes="all-gatekit-steps"
            )

            with Horizontal(classes="all-gatekit-buttons"):
                yield Button("Exit", id="exit_btn", variant="primary")

    def _build_config_list(self) -> str:
        """Build a list of Gatekit configs and the clients using them."""
        # Group clients by config path
        config_to_clients: dict[str, list[str]] = {}
        for client in self.detected_clients:
            if client.gatekit_config_path:
                path = client.gatekit_config_path
                if path not in config_to_clients:
                    config_to_clients[path] = []
                config_to_clients[path].append(client.display_name())

        if not config_to_clients:
            return ""

        lines = []
        for config_path, client_names in config_to_clients.items():
            clients_str = ", ".join(client_names)
            lines.append(f"Config: {config_path}")
            lines.append(f"  Used by: {clients_str}")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        self.dismiss(None)

    def action_dismiss(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)
