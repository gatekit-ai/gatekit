"""Server input handling and configuration persistence."""

import shlex

from textual import on
from textual.widgets import Button, Input

from gatekit.config.models import UpstreamConfig


class ServerPersistenceMixin:
    """Mixin providing input handlers and configuration persistence."""

    @on(Input.Changed, "#server_command_input")
    def on_server_command_changed(self, event: Input.Changed) -> None:
        """Refresh identity widgets as the command text changes."""
        try:
            self._update_identity_widgets(self.selected_server)
        except Exception:
            pass

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                current_upstream = self._get_selected_upstream()
                logger.log_event(
                    "server_command_changed",
                    screen=self,
                    widget=event.input,
                    context={
                        "server_alias": self.selected_server,
                        "value": event.value,
                        "strip_value": event.value.strip() if event.value else "",
                        "has_persisted_command": bool(
                            getattr(current_upstream, "command", None)
                        ),
                    },
                )
        except Exception:
            pass

    async def on_server_command_blurred(self, event: Input.Blurred) -> None:
        """Persist command changes when input loses focus."""
        # Reset cursor before commit (widget is still valid here)
        try:
            event.input.cursor_position = 0
            if hasattr(event.input, "selection"):
                event.input.selection = None
        except Exception:
            pass

        # Use connection input handler for URL auto-detection
        self._commit_connection_input(event.input.value)

    async def on_server_command_submitted(self, event: Input.Submitted) -> None:
        """Persist command changes when the user submits the input."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "SERVER_COMMAND_SUBMITTED",
                screen=self,
                context={
                    "event_type": type(event).__name__,
                    "event_input_id": getattr(event.input, "id", None),
                    "event_value": event.value,
                    "focused_widget": self.focused,
                    "focused_widget_id": getattr(self.focused, "id", None) if self.focused else None,
                    "focused_widget_type": type(self.focused).__name__ if self.focused else None,
                },
            )

        # Use connection input handler for URL auto-detection
        # Pass focus_test_button=True to advance focus after commit
        self._commit_connection_input(event.value, focus_test_button=True)

    def _reset_input_scroll(self, input_widget) -> None:
        """Reset any input widget to show the beginning of the text."""
        try:
            if not isinstance(input_widget, Input):
                return

            input_widget.cursor_position = 0
            # Force a refresh to update the display
            input_widget.refresh()

            # Debug logging
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "input_scroll_reset",
                    screen=self,
                    context={
                        "widget_id": getattr(input_widget, "id", None),
                        "cursor_position": input_widget.cursor_position,
                        "text_length": len(input_widget.value),
                    },
                )
        except Exception as e:
            # Silently handle any issues
            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "input_scroll_reset_error",
                        screen=self,
                        context={"error": str(e)},
                    )
            except Exception:
                pass

    def _commit_connection_input(self, raw_value: str, focus_test_button: bool = False) -> None:
        """Persist connection input with auto-detection of transport type.

        If the input starts with http:// or https://, it's treated as an HTTP URL.
        Otherwise, it's parsed as a stdio command.

        Args:
            raw_value: The connection string (URL or command).
            focus_test_button: If True, focus the test button after commit completes.
        """
        upstream = self._get_selected_upstream()
        if not upstream:
            return

        normalized_value = raw_value.strip()

        if not normalized_value:
            # Empty input - mark as draft
            changed = False
            if upstream.command is not None:
                upstream.command = None
                changed = True
            if upstream.url is not None:
                upstream.url = None
                changed = True
            upstream.is_draft = True

            if changed:
                self._mark_dirty()

            if hasattr(self, "_pending_connection_cache"):
                self._pending_connection_cache.pop(upstream.name, None)
            try:
                self.app.notify(
                    f"Connection info required for '{upstream.name}'.", severity="warning"
                )
            except Exception:
                pass
            try:
                self._update_identity_widgets(upstream.name)
            except Exception:
                pass
            return

        # Auto-detect transport type based on input
        if self._looks_like_url(normalized_value):
            # It's a URL - set HTTP transport
            self._set_http_transport(upstream, normalized_value, focus_test_button)
        else:
            # It's a command - set stdio transport
            self._set_stdio_transport(upstream, normalized_value, focus_test_button)

    def _set_http_transport(
        self, upstream: UpstreamConfig, url: str, focus_test_button: bool = False
    ) -> None:
        """Set upstream to HTTP transport with the given URL."""
        old_transport = upstream.transport
        old_url = upstream.url

        # Clear command if switching from stdio
        if upstream.command is not None:
            upstream.command = None

        # Normalize URL: add https:// if no scheme present
        normalized_url = url
        if not url.lower().startswith(("http://", "https://")):
            normalized_url = f"https://{url}"

        upstream.transport = "http"
        upstream.url = normalized_url
        upstream.is_draft = False

        # Mark dirty if anything changed
        if old_transport != "http" or old_url != normalized_url:
            self._mark_dirty()

        # Update pending cache
        if hasattr(self, "_pending_connection_cache"):
            self._pending_connection_cache[upstream.name] = normalized_url

        # Initialize server_tool_map entry
        if hasattr(self, "server_tool_map") and upstream.name not in self.server_tool_map:
            self.server_tool_map[upstream.name] = {
                "tools": [],
                "last_refreshed": None,
                "status": "pending",
                "message": "Server configuration complete. Click 'Connect' to discover tools.",
            }

        try:
            self._update_identity_widgets(upstream.name)
        except Exception:
            pass

        # Re-render the server details panel if transport changed (to show/hide TLS fields)
        if old_transport != "http":
            self._schedule_panel_refresh(focus_test_button=focus_test_button)
        elif focus_test_button:
            # No panel refresh needed, but still need to focus the button
            self._schedule_focus_test_button()

    def _set_stdio_transport(
        self, upstream: UpstreamConfig, command_str: str, focus_test_button: bool = False
    ) -> None:
        """Set upstream to stdio transport with the given command."""
        try:
            parsed_command = shlex.split(command_str)
        except ValueError as exc:
            try:
                self.app.notify(f"Unable to parse command: {exc}", severity="error")
            except Exception:
                pass
            return

        old_transport = upstream.transport
        old_command = " ".join(upstream.command) if upstream.command else ""
        new_command = " ".join(parsed_command)

        # Clear URL if switching from http
        if upstream.url is not None:
            upstream.url = None

        upstream.transport = "stdio"
        upstream.command = parsed_command
        upstream.is_draft = False

        # Mark dirty if anything changed
        if old_transport != "stdio" or old_command != new_command:
            self._mark_dirty()

        # Update pending cache
        if hasattr(self, "_pending_connection_cache"):
            self._pending_connection_cache[upstream.name] = command_str

        # Initialize server_tool_map entry
        if hasattr(self, "server_tool_map") and upstream.name not in self.server_tool_map:
            self.server_tool_map[upstream.name] = {
                "tools": [],
                "last_refreshed": None,
                "status": "pending",
                "message": "Server configuration complete. Click 'Connect' to discover tools.",
            }

        try:
            self._update_identity_widgets(upstream.name)
        except Exception:
            pass

        # Re-render the server details panel if transport changed (to hide TLS fields)
        if old_transport != "stdio":
            self._schedule_panel_refresh(focus_test_button=focus_test_button)
        elif focus_test_button:
            # No panel refresh needed, but still need to focus the button
            self._schedule_focus_test_button()

    def _schedule_focus_test_button(self) -> None:
        """Schedule focusing the test connection button."""
        self._cancel_pending_focus_timer()

        def _focus_button() -> None:
            try:
                test_button = self.query_one("#test_connection_button", Button)
                if getattr(test_button, "can_focus", False):
                    test_button.focus()
            except Exception:
                pass
            self._pending_focus_timer = None

        self._pending_focus_timer = self.set_timer(0.01, _focus_button)

    def _schedule_panel_refresh(self, focus_test_button: bool = False) -> None:
        """Schedule a refresh of the server details panel after transport change.

        Args:
            focus_test_button: If True, focus the test connection button after refresh.
        """
        def _refresh():
            try:
                self._run_worker(self._populate_server_details())
                if focus_test_button:
                    # Schedule focus after the panel is rebuilt
                    def _focus_button():
                        try:
                            test_button = self.query_one("#test_connection_button", Button)
                            if getattr(test_button, "can_focus", False):
                                test_button.focus()
                        except Exception:
                            pass
                    self.set_timer(0.05, _focus_button)
            except Exception:
                pass
        self.call_after_refresh(_refresh)

    # Known command starters for MCP servers
    _KNOWN_COMMANDS = frozenset({
        "npx", "uvx", "python", "python3", "node", "deno", "bun",
        "docker", "podman", "ruby", "java", "go", "cargo",
    })

    def _looks_like_url(self, value: str) -> bool:
        """Heuristic to detect if input looks like a URL vs a command.

        Uses Firefox-style heuristic plus additional checks:
        1. Explicit http:// or https:// → URL
        2. Starts with / or ./ → command (file path)
        3. First word is known command (npx, uvx, python, etc.) → command
        4. Space before first . or : → command (Firefox rule)
        5. Has a . → URL (domain-like)
        6. Starts with localhost → URL
        7. Default → command
        """
        value = value.strip()
        if not value:
            return False

        lower = value.lower()

        # 1. Explicit protocol → URL
        if lower.startswith(("http://", "https://")):
            return True

        # 2. File path → command
        if value.startswith("/") or value.startswith("./"):
            return False

        # 3. Known command starter → command
        first_word = value.split()[0].lower() if value.split() else ""
        if first_word in self._KNOWN_COMMANDS:
            return False

        # 4. Firefox rule: space before first . or : → command
        first_dot = value.find(".")
        first_colon = value.find(":")
        first_space = value.find(" ")

        if first_space != -1:
            # There's a space - check if it comes before . or :
            dot_or_colon = -1
            if first_dot != -1 and first_colon != -1:
                dot_or_colon = min(first_dot, first_colon)
            elif first_dot != -1:
                dot_or_colon = first_dot
            elif first_colon != -1:
                dot_or_colon = first_colon

            if dot_or_colon == -1 or first_space < dot_or_colon:
                # Space comes before any . or : (or there is no . or :)
                return False

        # 5. Has a dot → URL (domain-like pattern)
        if first_dot != -1:
            return True

        # 6. Starts with localhost → URL
        if lower.startswith("localhost"):
            return True

        # 7. Default → command
        return False

    def _format_tls_verify(self, tls_verify: bool) -> str:
        """Format tls_verify value for display in the input field."""
        return "true" if tls_verify else "false"

    def _parse_tls_verify(self, value: str) -> bool:
        """Parse tls_verify input value to bool."""
        value = value.strip().lower()
        if value == "false":
            return False
        # Default to True for empty, "true", or any other value
        return True

    def _commit_tls_verify_input(self, raw_value: str) -> None:
        """Persist the TLS verify setting for the selected HTTP server."""
        upstream = self._get_selected_upstream()
        if not upstream or upstream.transport != "http":
            return

        new_value = self._parse_tls_verify(raw_value)
        if upstream.tls_verify != new_value:
            upstream.tls_verify = new_value
            self._mark_dirty()

    async def _commit_server_name(self, raw_value: str) -> None:
        """Apply a server name change after validation."""
        upstream = self._get_selected_upstream()
        if not upstream:
            return

        new_name = raw_value.strip()
        error = self._validate_server_name(new_name, current_name=upstream.name)
        if error:
            try:
                self.app.notify(error, severity="error")
            except Exception:
                pass
            await self._populate_server_details()
            return

        if new_name == upstream.name:
            return

        old_name = upstream.name
        upstream.name = new_name
        self._rename_server_references(old_name, new_name)
        self.selected_server = new_name

        # Mark dirty after successful mutation
        self._mark_dirty()

        await self._populate_servers_list()
        await self._populate_server_details()

        # Note: Configuration changes are not auto-saved. User must click Save.
        try:
            self.app.notify(
                f"Renamed server to '{new_name}'.", severity="information"
            )
        except Exception:
            pass
