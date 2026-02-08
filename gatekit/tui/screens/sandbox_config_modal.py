"""Sandbox configuration modal for per-server sandbox settings."""

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from gatekit.config.models import SandboxConfig
from gatekit.tui.widgets.ascii_checkbox import ASCIICheckbox
from gatekit.tui.widgets.selectable_static import SelectableStatic
from gatekit.tui.utils.terminal_compat import get_info_icon

_SANDBOX_INFO_TEXT = """\
The sandbox restricts an MCP server process using OS-native \
isolation (Seatbelt on macOS, bubblewrap on Linux). It controls \
what the server can read, write, and access on the network.

[bold]Filesystem Policy[/bold]

The home directory is denied by default. The server can only \
access specific directories:

  [bold]Accessible by default:[/bold]
    • System paths (/usr, /bin, /lib, /etc, /opt, etc.)
    • /tmp (fresh tmpfs on Linux, allowed on macOS)
    • ~/.npm, ~/.cache, ~/.local (package manager caches,
      if they exist)

  Add paths below for directories the server needs.

[bold]Sensitive Paths[/bold]

These directories are hidden from the sandboxed server \
(excluded from the allowlist on macOS, actively overlaid \
with empty directories on Linux):

    [dim]•[/dim] ~/.ssh              [dim]SSH keys and config[/dim]
    [dim]•[/dim] ~/.gnupg            [dim]GPG keys[/dim]
    [dim]•[/dim] ~/.aws              [dim]AWS credentials[/dim]
    [dim]•[/dim] ~/.azure            [dim]Azure credentials[/dim]
    [dim]•[/dim] ~/.config/gcloud    [dim]Google Cloud credentials[/dim]
    [dim]•[/dim] ~/.kube             [dim]Kubernetes credentials[/dim]
    [dim]•[/dim] ~/.docker           [dim]Docker registry credentials[/dim]
    [dim]•[/dim] ~/.git-credentials  [dim]Git credential store[/dim]
    [dim]•[/dim] ~/.vault-token      [dim]HashiCorp Vault token[/dim]
    [dim]•[/dim] ~/.terraform.d      [dim]Terraform credentials[/dim]

[italic]Note: On macOS, if you allow a parent path (e.g., "~"), \
sensitive subdirectories become accessible because Seatbelt's \
allow-wins semantics prevent carving out exceptions. Use \
specific paths to keep sensitive directories protected.[/italic]

[bold]Network[/bold]

Network access is allowed by default because most MCP servers \
need to call external APIs. You can disable it to block \
outbound network connections.

[bold]Fail-Closed Behavior[/bold]

If sandboxing is enabled but no sandbox engine is available \
(e.g., bubblewrap not installed on Linux), Gatekit refuses to \
start the server rather than running it unsandboxed.\
"""


class _FocusableInfoIcon(Static, can_focus=True):
    """Focusable info icon that opens the sandbox overview on click or Enter.

    This is a Static subclass with can_focus=True, verified by headless tests
    to participate in Tab/Shift+Tab focus cycling and respond to Enter key.
    """

    DEFAULT_CSS = """
    _FocusableInfoIcon {
        color: $primary;
        width: auto;
        height: 1;
        margin-bottom: 1;
        background: transparent;
    }
    _FocusableInfoIcon:hover {
        text-style: bold;
        background: $boost;
    }
    _FocusableInfoIcon:focus {
        text-style: bold;
        background: $boost;
    }
    """

    def __init__(self, **kwargs):
        # Two spaces after the icon: the emoji with variation selector renders
        # as 2 cells but layout calculates 1, so the extra space absorbs the
        # overflow and prevents the icon from overlapping "Learn more".
        super().__init__(f"{get_info_icon()}  Learn more", **kwargs)

    def _on_click(self, event):
        self._show_info()

    def _on_key(self, event):
        if event.key == "enter":
            self._show_info()
            event.stop()
            event.prevent_default()

    def _show_info(self):
        from gatekit.tui.screens.simple_modals import MessageModal

        self.app.push_screen(MessageModal("Sandbox Overview", _SANDBOX_INFO_TEXT))


class SandboxConfigModal(ModalScreen[Optional[SandboxConfig]]):
    """Modal for editing sandbox configuration settings.

    Returns a SandboxConfig on OK, None on Cancel/Escape.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "save", "OK", show=True),
    ]

    CSS = """
    SandboxConfigModal {
        align: center middle;
    }

    SandboxConfigModal > .dialog {
        width: 70;
        max-width: 80;
        height: 90%;
        max-height: 90%;
        background: $surface;
        border: heavy $primary;
        padding: 1;
    }

    .sandbox-title {
        text-align: center;
        margin-bottom: 1;
        color: $primary;
        text-style: bold;
    }

    .sandbox-description {
        color: $text-muted;
        text-style: italic;
        height: auto;
    }

    .sandbox-engine-label {
        margin-bottom: 1;
        color: $text-muted;
    }

    .sandbox-field-description {
        height: auto;
        color: $text-muted;
        margin-bottom: 0;
    }

    .sandbox-network-row {
        height: 1;
        margin-bottom: 1;
    }

    .sandbox-field-label {
        margin-top: 1;
        margin-bottom: 0;
        text-style: bold;
    }

    .sandbox-form-content {
        height: 1fr;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
        margin-bottom: 1;
    }

    .sandbox-paths-area {
        height: 1fr;
        min-height: 4;
        border: solid $primary;
    }

    .button-row {
        dock: bottom;
        height: 3;
        layout: horizontal;
        align: center middle;
        padding: 0 1;
        background: $surface;
    }

    .button-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, sandbox_config: Optional[SandboxConfig] = None) -> None:
        super().__init__()
        self._config = sandbox_config or SandboxConfig(enabled=True)

    def compose(self) -> ComposeResult:
        # Detect backend
        backend_name = "unknown"
        try:
            from gatekit.sandbox.detection import _detect_backend

            backend = _detect_backend()
            if backend:
                backend_name = backend.name
        except Exception:
            pass

        with Container(classes="dialog"):
            yield SelectableStatic("Sandbox Settings", classes="sandbox-title")

            with VerticalScroll(classes="sandbox-form-content"):
                yield Static(
                    f"Engine: {backend_name} (auto-detected)",
                    classes="sandbox-engine-label",
                )
                yield SelectableStatic(
                    "Denies all filesystem access by default. Only system paths, "
                    "/tmp, and cache directories are accessible. Sensitive paths "
                    "like ~/.ssh and ~/.aws are always hidden.",
                    classes="sandbox-description",
                )
                yield _FocusableInfoIcon(id="sandbox_info_icon")

                # Network checkbox
                yield Horizontal(
                    ASCIICheckbox(
                        value=self._config.network,
                        id="sandbox_network_checkbox",
                    ),
                    Static(" Allow network access"),
                    classes="sandbox-network-row",
                )

                # Paths
                yield Static(
                    "Paths (one per line):",
                    classes="sandbox-field-label",
                )
                yield SelectableStatic(
                    "Directories the server needs read+write access to. "
                    "Everything else is denied by default (except system "
                    "paths and /tmp). Add your workspace directories here.",
                    classes="sandbox-field-description",
                )
                paths_text = "\n".join(self._config.paths) if self._config.paths else ""
                yield TextArea(
                    paths_text,
                    id="sandbox_paths",
                    classes="sandbox-paths-area",
                    placeholder="~/docs\n~/projects/my-app",
                )

            # Fixed buttons docked at bottom
            with Container(classes="button-row"):
                yield Button("OK", id="sandbox_save_btn", variant="primary")
                yield Button("Cancel", id="sandbox_cancel_btn")

    def on_mount(self) -> None:
        """Disable VerticalScroll focus and set initial focus to network checkbox."""
        for scroll in self.query(VerticalScroll):
            scroll.can_focus = False
        # Set initial focus to the network checkbox
        try:
            cb = self.query_one("#sandbox_network_checkbox", ASCIICheckbox)
            cb.focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        """Handle arrow key navigation between form controls.

        Focus order for arrow keys: info_icon <-> checkbox <-> textarea <-> buttons
        TextArea only lets arrow events bubble when the cursor is at the
        first/last line, so this naturally transitions at the boundaries.
        """
        if event.key == "down":
            focused = self.focused
            if isinstance(focused, _FocusableInfoIcon):
                try:
                    cb = self.query_one("#sandbox_network_checkbox", ASCIICheckbox)
                    cb.focus()
                    event.stop()
                except Exception:
                    pass
            elif isinstance(focused, ASCIICheckbox) and getattr(focused, "id", "") == "sandbox_network_checkbox":
                try:
                    area = self.query_one("#sandbox_paths", TextArea)
                    area.focus()
                    event.stop()
                except Exception:
                    pass
            elif isinstance(focused, TextArea) and getattr(focused, "id", "") == "sandbox_paths":
                try:
                    btn = self.query_one("#sandbox_save_btn", Button)
                    btn.focus()
                    event.stop()
                except Exception:
                    pass
        elif event.key == "up":
            focused = self.focused
            if isinstance(focused, Button):
                try:
                    area = self.query_one("#sandbox_paths", TextArea)
                    area.focus()
                    event.stop()
                except Exception:
                    pass
            elif isinstance(focused, TextArea) and getattr(focused, "id", "") == "sandbox_paths":
                try:
                    cb = self.query_one("#sandbox_network_checkbox", ASCIICheckbox)
                    cb.focus()
                    event.stop()
                except Exception:
                    pass
            elif isinstance(focused, ASCIICheckbox) and getattr(focused, "id", "") == "sandbox_network_checkbox":
                try:
                    icon = self.query_one("#sandbox_info_icon", _FocusableInfoIcon)
                    icon.focus()
                    event.stop()
                except Exception:
                    pass
        elif event.key == "right":
            focused = self.focused
            if isinstance(focused, Button) and focused.id == "sandbox_save_btn":
                try:
                    btn = self.query_one("#sandbox_cancel_btn", Button)
                    btn.focus()
                    event.stop()
                except Exception:
                    pass
        elif event.key == "left":
            focused = self.focused
            if isinstance(focused, Button) and focused.id == "sandbox_cancel_btn":
                try:
                    btn = self.query_one("#sandbox_save_btn", Button)
                    btn.focus()
                    event.stop()
                except Exception:
                    pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._do_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sandbox_cancel_btn":
            self.dismiss(None)
        elif event.button.id == "sandbox_save_btn":
            self._do_save()

    def _do_save(self) -> None:
        """Collect values and dismiss with a SandboxConfig."""
        network_cb = self.query_one("#sandbox_network_checkbox", ASCIICheckbox)
        paths_area = self.query_one("#sandbox_paths", TextArea)

        paths = [
            line.strip()
            for line in paths_area.text.splitlines()
            if line.strip()
        ]

        # Validate paths before saving — reject glob patterns
        from gatekit.config.models import _SANDBOX_GLOB_CHARS

        for p in paths:
            bad = _SANDBOX_GLOB_CHARS.intersection(p)
            if bad:
                self.app.notify(
                    f"Path {p!r} contains glob characters ({', '.join(sorted(bad))}). "
                    f"Glob patterns are not supported — use exact directory paths.",
                    severity="error",
                )
                return

        result = SandboxConfig(
            enabled=True,
            paths=paths,
            network=network_cb.value,
        )
        self.dismiss(result)
