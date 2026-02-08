"""Server details panel rendering and placeholder rotation."""

import random
from functools import partial

from textual.widgets import Label, Button, Input
from textual.containers import Container, Horizontal

from gatekit.tui.widgets.selectable_static import SelectableStatic

from .server_widgets import AsyncCallbackButton


# Popular MCP servers for placeholder examples (stdio and HTTP interleaved)
PLACEHOLDER_EXAMPLES = [
    # stdio: everything server
    "npx -y @modelcontextprotocol/server-everything",
    # http: DeepWiki (open)
    "https://mcp.deepwiki.com/mcp",
    # stdio: filesystem server
    "npx -y @modelcontextprotocol/server-filesystem ~/my_dir",
    # http: Exa search (open)
    "https://mcp.exa.ai/mcp",
    # stdio: fetch server (uvx)
    "uvx mcp-server-fetch",
    # http: Hugging Face (open)
    "https://hf.co/mcp",
    # stdio: memory/knowledge graph
    "npx -y @modelcontextprotocol/server-memory",
    # http: AWS Knowledge (open)
    "https://knowledge-mcp.global.api.aws",
    # stdio: sequential thinking
    "npx -y @modelcontextprotocol/server-sequential-thinking",
]


class ServerDetailsMixin:
    """Mixin providing server details panel rendering."""

    async def _populate_server_details(self) -> None:
        """Populate the combined server details panel."""
        logger = None
        # Debug log entry
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "populate_server_details_start",
                    screen=self,
                    context={"selected_server": self.selected_server},
                )
        except Exception:
            pass

        # Reset any stale focus memory for server_details and server_plugins panels.
        # After switching servers, previously remembered widgets may be detached;
        # clearing here prevents navigation from targeting invalid widgets.
        try:
            if hasattr(self, "container_focus_memory"):
                self.container_focus_memory.pop("server_details", None)
            if hasattr(self, "panel_focus_memory"):
                self.panel_focus_memory.pop("server_plugins", None)
        except Exception:
            pass

        # Cancel any pending focus timers when server details change
        self._cancel_pending_focus_timer()

        if not self.selected_server:
            await self._clear_server_details()
            return

        # Find upstream config
        upstream = next(
            (u for u in self.config.upstreams if u.name == self.selected_server), None
        )

        if not upstream:
            await self._clear_server_details()
            return

        # Update server info section
        info_container = self.query_one("#server_info", Container)
        info_container.remove_children()

        # Build info lines (keep exactly one label per line)
        info_lines = []

        # Create horizontal container for "Server Alias:" label + input
        name_input = Input(value=upstream.name, id="server_name_input")
        name_input.add_class("-textual-compact")
        name_row = Horizontal(Label("Server Alias:", classes="server-label"), name_input)
        info_lines.append(name_row)

        alias = upstream.name

        # Single connection input that auto-detects transport (URL vs command)
        if upstream.transport == "http":
            connection_value = upstream.url or ""
        else:
            connection_value = " ".join(upstream.command) if upstream.command else ""

        connection_input = Input(value=connection_value, id="server_command_input")

        # Start at a random position in the list
        placeholder_start_idx = random.randint(0, len(PLACEHOLDER_EXAMPLES) - 1)

        # Set up rotating placeholder with fade animation
        fade_duration = 0.5  # seconds for fade out/in
        display_duration = 8.0  # seconds to show each placeholder
        initial_delay = 1.0  # seconds before first placeholder appears

        # Start with blank placeholder and faded out (only if empty)
        connection_input.placeholder = ""
        if connection_value:
            # Input already has content - ensure it's visible
            connection_input.styles.text_opacity = 1.0
        else:
            # Empty input - start faded out for placeholder animation
            connection_input.styles.text_opacity = 0.0

        def _fade_in_placeholder() -> None:
            """Fade the placeholder in."""
            try:
                inp = self.query_one("#server_command_input", Input)
                inp.styles.animate("text_opacity", value=1.0, duration=fade_duration)
                # Schedule next rotation
                self._placeholder_timer = self.set_timer(display_duration, _start_fade_out)
            except Exception:
                pass

        def _change_placeholder_text() -> None:
            """Change placeholder text while faded out, then fade in."""
            try:
                inp = self.query_one("#server_command_input", Input)
                if inp.value:  # Stop rotating if user entered something
                    inp.styles.text_opacity = 1.0  # Reset opacity
                    return
                # Get current index and rotate
                current = inp.placeholder
                try:
                    idx = PLACEHOLDER_EXAMPLES.index(current)
                    next_idx = (idx + 1) % len(PLACEHOLDER_EXAMPLES)
                except ValueError:
                    next_idx = 0
                inp.placeholder = PLACEHOLDER_EXAMPLES[next_idx]
                # Fade back in
                _fade_in_placeholder()
            except Exception:
                pass

        def _start_fade_out() -> None:
            """Start the fade out, then change text."""
            try:
                inp = self.query_one("#server_command_input", Input)
                if inp.value:  # Stop rotating if user entered something
                    return
                inp.styles.animate("text_opacity", value=0.0, duration=fade_duration)
                # After fade out completes, change text
                self.set_timer(fade_duration, _change_placeholder_text)
            except Exception:
                pass

        def _initial_fade_in(start_idx: int = 0) -> None:
            """Set first placeholder and fade in."""
            try:
                inp = self.query_one("#server_command_input", Input)
                if inp.value:  # User already typed something
                    inp.styles.text_opacity = 1.0
                    return
                inp.placeholder = PLACEHOLDER_EXAMPLES[start_idx]
                _fade_in_placeholder()
            except Exception:
                pass

        def _restart_rotation() -> None:
            """Restart placeholder rotation from a new random position."""
            try:
                inp = self.query_one("#server_command_input", Input)
                inp.placeholder = ""
                inp.styles.text_opacity = 0.0
                new_start = random.randint(0, len(PLACEHOLDER_EXAMPLES) - 1)
                self._placeholder_timer = self.set_timer(
                    initial_delay, lambda: _initial_fade_in(new_start)
                )
            except Exception:
                pass

        # Store restart function so _on_connection_value_watch can call it
        self._restart_placeholder_rotation = _restart_rotation

        # Cancel any existing placeholder timer before starting new one
        if hasattr(self, "_placeholder_timer") and self._placeholder_timer:
            try:
                self._placeholder_timer.stop()
            except Exception:
                pass

        # Start with initial delay, then fade in first placeholder (only for empty inputs)
        if not connection_value:
            self._placeholder_timer = self.set_timer(
                initial_delay, lambda: _initial_fade_in(placeholder_start_idx)
            )
        connection_input.add_class("-textual-compact")
        try:
            self.watch(
                connection_input,
                "value",
                partial(self._on_connection_value_watch, alias),
                init=False,
            )
        except Exception:
            pass
        connection_row = Horizontal(
            Label("Command or URL:", classes="server-label"),
            connection_input,
        )
        info_lines.append(connection_row)

        identity_status = self._get_identity_status(alias)
        (
            identity_value,
            identity_placeholder,
            identity_tooltip,
        ) = self._describe_identity_display(upstream, identity_status)

        identity_input = Input(value=identity_value, id="server_identity_input")
        identity_input.placeholder = identity_placeholder
        identity_input.disabled = True
        identity_input.add_class("-textual-compact")
        if identity_tooltip:
            identity_input.tooltip = identity_tooltip

        # Create button with placeholder - _update_identity_widgets sets the real state
        test_button = AsyncCallbackButton(
            "Connect",
            id="test_connection_button",
            callback=self._handle_test_connection,
        )
        test_button.add_class("-textual-compact")

        identity_row = Horizontal(
            Label("Server Identity:", classes="server-label"),
            identity_input,
            test_button,
        )
        info_lines.append(identity_row)

        # Transport indicator (read-only, auto-detected from connection input)
        # Show blank for drafts with no connection input yet
        has_connection = upstream.command or upstream.url
        transport_display = upstream.transport if has_connection else ""
        transport_input = Input(value=transport_display, id="server_transport_input")
        transport_input.add_class("-textual-compact")
        transport_input.disabled = True  # Read-only, auto-detected from connection input
        # Give transport input a fixed narrow width since it only shows "http" or "stdio"
        transport_input.styles.width = 10

        # Transport row - TLS warning widgets will be mounted dynamically if needed
        transport_row = Horizontal(
            Label("Transport:", classes="server-label"),
            transport_input,
            classes="transport-row",
        )
        info_lines.append(transport_row)

        # Sandbox row (stdio transport only)
        if upstream.transport == "stdio":
            from gatekit.tui.widgets.ascii_checkbox import ASCIICheckbox

            sandbox_enabled = (
                upstream.sandbox is not None and upstream.sandbox.enabled
            )

            # Check if a sandbox backend is available on this platform
            sandbox_available = False
            sandbox_unavailable_reason = ""
            try:
                from gatekit.sandbox.detection import _detect_backend

                backend = _detect_backend()
                if backend is None:
                    import sys as _sys
                    sandbox_unavailable_reason = f"Not available on {_sys.platform}"
                elif not backend.is_available():
                    sandbox_unavailable_reason = backend.availability_diagnostic()
                else:
                    sandbox_available = True
            except Exception:
                sandbox_unavailable_reason = "Detection failed"

            sandbox_checkbox = ASCIICheckbox(
                value=sandbox_enabled,
                id="sandbox_enabled_checkbox",
            )
            sandbox_checkbox.disabled = not sandbox_available

            configure_button = AsyncCallbackButton(
                "Configure",
                id="sandbox_configure_button",
                callback=self._handle_sandbox_configure,
            )
            configure_button.add_class("-textual-compact")

            sandbox_row_widgets = [
                Label("Sandbox:", classes="server-label"),
                sandbox_checkbox,
            ]
            if sandbox_available:
                sandbox_row_widgets.append(configure_button)
            else:
                unavailable_label = SelectableStatic(
                    "(Not available)",
                    id="sandbox_unavailable_label",
                )
                unavailable_label.styles.width = "auto"
                unavailable_label.styles.margin = (0, 0, 0, 1)
                unavailable_label.styles.text_style = "underline"
                unavailable_label.styles.color = "gray"
                unavailable_label.tooltip = sandbox_unavailable_reason
                sandbox_row_widgets.append(unavailable_label)

            sandbox_row = Horizontal(
                *sandbox_row_widgets,
                classes="sandbox-row",
            )
            info_lines.append(sandbox_row)

        # Mount the lines
        for line in info_lines:
            info_container.mount(line)

        # Show TLS warning if connected without verification (tls_verify=False)
        # NOTE: We use call_after_refresh because Textual's query tree isn't updated
        # immediately after remove_children()/mount(), so _show_tls_warning() would
        # find the old row if called synchronously.
        if upstream.transport == "http" and getattr(upstream, "tls_verify", True) is False:
            self.call_after_refresh(lambda: self._show_tls_warning(True))

        try:
            alias = upstream.name
            if alias:
                self._update_identity_widgets(alias)
                self.call_after_refresh(
                    lambda alias=alias: self._update_identity_widgets(alias)
                )
        except Exception:
            pass

        # Dynamically clamp height to content lines (reduced padding)
        try:
            # Each Label is height 1; reduced padding for tighter spacing
            computed_height = max(1, len(info_lines))  # content lines
            # Let the panel size to content but never exceed content
            info_container.styles.height = "auto"
            info_container.styles.max_height = computed_height
            info_container.styles.min_height = computed_height
        except Exception:
            # Non-fatal if style update fails
            pass

        # Log before calling render
        try:
            if logger:
                logger.log_event(
                    "before_render_plugins",
                    screen=self,
                    context={"selected_server": self.selected_server},
                )
        except Exception:
            pass

        # Update plugins section
        await self._render_server_plugin_groups()

        # Log after render
        try:
            if logger:
                logger.log_event(
                    "after_render_plugins",
                    screen=self,
                    context={"selected_server": self.selected_server},
                )
        except Exception:
            pass

        # Reveal the remove button now that a server is selected
        try:
            remove_container = self.query_one("#remove_server_container")
            remove_container.remove_class("hidden")
            remove_container.display = True
            remove_btn = remove_container.query_one("#remove_server", Button)
            remove_btn.disabled = False
        except Exception:
            pass

    async def _clear_server_details(self) -> None:
        """Clear server details panel and show placeholder."""
        # Clear server info
        info_container = self.query_one("#server_info", Container)
        info_container.remove_children()
        info_container.mount(Label("Select a server to view details"))
        # Reset sizing to a tight placeholder (1 line message + padding)
        try:
            info_container.styles.height = "auto"
            info_container.styles.max_height = 2
            info_container.styles.min_height = 1
        except Exception:
            pass

        # Clear plugins display
        plugins_container = self.query_one("#server_plugins_display")
        plugins_container.remove_children()

        # Hide the remove button when no server is selected
        try:
            remove_container = self.query_one("#remove_server_container")
            remove_container.add_class("hidden")
            remove_container.display = False
            remove_btn = remove_container.query_one("#remove_server", Button)
            remove_btn.disabled = True
        except Exception:
            pass

    def _is_tls_error(self, error_message: str) -> bool:
        """Check if an error message indicates a TLS/SSL verification failure."""
        if not error_message:
            return False
        error_lower = error_message.lower()
        tls_indicators = [
            "tls",
            "ssl",
            "certificate",
            "cert",
            "verify",
            "handshake",
        ]
        return any(indicator in error_lower for indicator in tls_indicators)

    def _show_tls_warning(self, show: bool = True) -> None:
        """Show or hide the TLS warning as a separate underlined widget."""
        # DEBUG: Log entry
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "SHOW_TLS_WARNING_ENTRY",
                    screen=self,
                    context={"show": show},
                )
        except Exception:
            pass

        try:
            transport_row = self.query_one(".transport-row", Horizontal)
            transport_input = self.query_one("#server_transport_input", Input)
            existing_warning = self.query("#tls_warning_label")

            # DEBUG: Log widget discovery with detailed info
            try:
                from ...debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    # Check if warnings are actually in the transport_row
                    warnings_in_row = transport_row.query("#tls_warning_label") if transport_row else []
                    warning_details = []
                    for w in existing_warning:
                        warning_details.append({
                            "id": getattr(w, "id", None),
                            "is_mounted": getattr(w, "_is_mounted", None),
                            "parent": type(getattr(w, "parent", None)).__name__ if getattr(w, "parent", None) else None,
                            "display": str(getattr(w.styles, "display", None)) if hasattr(w, "styles") else None,
                            "size": str(w.size) if hasattr(w, "size") else None,
                            "region": str(w.region) if hasattr(w, "region") else None,
                            "content_size": str(w.content_size) if hasattr(w, "content_size") else None,
                            "renderable": str(w.renderable)[:50] if hasattr(w, "renderable") else None,
                        })
                    logger.log_event(
                        "SHOW_TLS_WARNING_WIDGETS",
                        screen=self,
                        context={
                            "transport_row_found": transport_row is not None,
                            "transport_row_id": getattr(transport_row, "id", None),
                            "transport_row_object_id": id(transport_row) if transport_row else None,
                            "transport_row_is_mounted": getattr(transport_row, "_is_mounted", None) if transport_row else None,
                            "transport_row_children_count": len(list(transport_row.children)) if transport_row else 0,
                            "transport_input_found": transport_input is not None,
                            "existing_warning_count": len(existing_warning) if existing_warning else 0,
                            "warnings_in_row_count": len(warnings_in_row) if warnings_in_row else 0,
                            "warning_details": warning_details,
                        },
                    )
            except Exception:
                pass

            if show:
                # Shrink the transport input to fit content
                transport_input.styles.width = "auto"

                if not existing_warning:
                    # Use SelectableStatic so the warning text can be selected/copied
                    tls_warning = SelectableStatic(
                        "(⚠️  TLS error)",
                        id="tls_warning_label",
                    )
                    tls_warning.styles.margin = (0, 0, 0, 1)  # Left margin for spacing
                    tls_warning.styles.width = "auto"
                    tls_warning.styles.text_style = "underline"
                    tls_warning.styles.color = "gray"
                    tls_warning.tooltip = (
                        "TLS/SSL certificate verification failed. This server may have a "
                        "self-signed certificate, an expired certificate, or there may be "
                        "a man-in-the-middle attack."
                        "\n\nRemove this server if you're unsure about it."
                    )
                    transport_row.mount(tls_warning)

                    # DEBUG: Log warning mounted
                    try:
                        from ...debug import get_debug_logger
                        logger = get_debug_logger()
                        if logger:
                            logger.log_event(
                                "TLS_WARNING_MOUNTED",
                                screen=self,
                                context={"show": show},
                            )
                    except Exception:
                        pass
            else:
                # Restore transport input width
                transport_input.styles.width = 10
                for widget in existing_warning:
                    widget.remove()
        except Exception as exc:
            # DEBUG: Log any exception
            try:
                from ...debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "SHOW_TLS_WARNING_ERROR",
                        screen=self,
                        context={
                            "show": show,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
            except Exception:
                pass

