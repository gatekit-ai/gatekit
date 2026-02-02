"""Server connection testing and identity status management."""

from typing import Dict, Optional

from textual.widgets import Button, Input

from gatekit.config.models import UpstreamConfig


class ServerConnectionMixin:
    """Mixin providing connection testing and identity status management."""

    def _get_identity_status(self, alias: Optional[str]) -> Dict[str, Optional[str]]:
        """Fetch the current identity test status for a server alias."""
        default = {"state": "idle", "message": None}
        if not alias:
            return default

        status_map = getattr(self, "_identity_test_status", None)
        if not status_map:
            return default

        return status_map.get(alias, default)

    def _set_identity_status(
        self, alias: Optional[str], state: str, message: Optional[str] = None
    ) -> None:
        """Update identity test status and refresh widgets if present."""
        if not alias:
            return

        if not hasattr(self, "_identity_test_status"):
            self._identity_test_status = {}

        self._identity_test_status[alias] = {"state": state, "message": message}

        # Debug: Log status being set
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "set_identity_status",
                    screen=self,
                    context={
                        "alias": alias,
                        "state": state,
                        "message": message,
                        "selected_server": getattr(self, "selected_server", None),
                    },
                )
        except Exception:
            pass

        try:
            self._update_identity_widgets(alias)
        except Exception:
            pass

        try:
            self.call_after_refresh(
                lambda alias=alias: self._update_identity_widgets(alias)
            )
        except Exception:
            pass

    def _on_connection_value_watch(
        self, alias: str, old_value: Optional[str], new_value: Optional[str]
    ) -> None:
        """Track live connection input edits to drive Test Connection enablement."""
        try:
            if not hasattr(self, "_pending_connection_cache"):
                self._pending_connection_cache = {}

            self._pending_connection_cache[alias] = (new_value or "")

            self._update_identity_widgets(alias)

            # Handle placeholder rotation state based on input value
            try:
                inp = self.query_one("#server_command_input", Input)
                if new_value:
                    # User typed something - ensure text is visible and stop rotation
                    inp.styles.text_opacity = 1.0
                    if hasattr(self, "_placeholder_timer") and self._placeholder_timer:
                        try:
                            self._placeholder_timer.stop()
                        except Exception:
                            pass
                        self._placeholder_timer = None
                elif not new_value and old_value:
                    # User cleared the field - restart placeholder rotation
                    if hasattr(self, "_restart_placeholder_rotation"):
                        self._restart_placeholder_rotation()
            except Exception:
                pass
        except Exception:
            pass

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "connection_value_watch",
                    screen=self,
                    context={
                        "server_alias": alias,
                        "old_value": old_value,
                        "new_value": new_value,
                    },
                )
        except Exception:
            pass

    def _describe_identity_display(
        self, upstream: UpstreamConfig, status: Dict[str, Optional[str]]
    ) -> tuple[str, str, Optional[str]]:
        """Compute the value, placeholder, and tooltip for the identity field."""
        # Use different placeholder for draft servers vs configured servers
        if getattr(upstream, "is_draft", False):
            placeholder = "Enter command or URL, then press Connect"
        else:
            placeholder = "Press Connect to discover server"
        tooltip: Optional[str] = None
        identity_value = upstream.server_identity or ""

        state = (status or {}).get("state") or "idle"
        message = (status or {}).get("message")

        if state == "testing":
            identity_value = "Testing connection..."
        elif not identity_value:
            if state == "tls_error":
                identity_value = "TLS verification failed"
                tooltip = message
            elif state == "error":
                identity_value = "Connection failed"
                tooltip = message
            else:
                identity_value = ""
        else:
            if state in ("error", "tls_error") and message:
                tooltip = message

        return identity_value, placeholder, tooltip

    def _get_test_connection_block_reason(
        self,
        upstream: Optional[UpstreamConfig],
        *,
        pending_command: Optional[str] = None,
        pending_url: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> Optional[str]:
        """Return a human-readable reason why test connection is unavailable."""
        if upstream is None:
            return "Select a server before testing the connection."

        # Get pending connection value from cache or widget
        connection_text = pending_command or pending_url or ""
        if not connection_text and alias and hasattr(self, "_pending_connection_cache"):
            connection_text = self._pending_connection_cache.get(alias, "")

        if not connection_text.strip():
            # Attempt to read directly from the mounted widget if available
            try:
                connection_input = self.query_one("#server_command_input", Input)
                connection_text = connection_input.value or ""
            except Exception:
                connection_text = ""

        # Handle HTTP transport
        if upstream.transport == "http":
            if upstream.url or connection_text.strip():
                return None
            return "Enter a URL before testing this server."

        # Handle stdio transport
        if upstream.transport != "stdio":
            return f"Connection testing is not available for {upstream.transport} transport."

        if upstream.command or connection_text.strip():
            return None

        return "Enter a launch command before testing this server."

    def _update_identity_widgets(self, alias: Optional[str]) -> None:
        """Refresh the identity input and test button for the active server."""
        # Debug: Log entry with all relevant state
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "update_identity_widgets_entry",
                    screen=self,
                    context={
                        "alias": alias,
                        "selected_server": self.selected_server,
                        "identity_test_status": getattr(self, "_identity_test_status", {}),
                    },
                )
        except Exception:
            pass

        if not alias or alias != self.selected_server:
            return

        upstream = self._get_selected_upstream()
        if not upstream:
            return

        status = self._get_identity_status(alias)

        # Debug: Log status retrieved
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "update_identity_widgets_status",
                    screen=self,
                    context={
                        "alias": alias,
                        "status": status,
                        "upstream_server_identity": getattr(upstream, "server_identity", None),
                    },
                )
        except Exception:
            pass
        (
            identity_value,
            identity_placeholder,
            identity_tooltip,
        ) = self._describe_identity_display(upstream, status)

        try:
            identity_input = self.query_one("#server_identity_input", Input)
        except Exception:
            identity_input = None

        try:
            test_button = self.query_one("#test_connection_button", Button)
        except Exception:
            test_button = None

        # Debug: Log widget discovery
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "update_identity_widgets_buttons",
                    screen=self,
                    context={
                        "alias": alias,
                        "test_button_found": test_button is not None,
                        "identity_input_found": identity_input is not None,
                        "current_button_label": str(getattr(test_button, "label", None)) if test_button else None,
                    },
                )
        except Exception:
            pass

        if identity_input:
            identity_input.value = identity_value
            identity_input.placeholder = identity_placeholder
            identity_input.disabled = True
            identity_input.tooltip = identity_tooltip
            identity_input.refresh()

        if test_button:
            is_testing = (status or {}).get("state") == "testing"

            pending_command = ""
            try:
                command_input = self.query_one("#server_command_input", Input)
                pending_command = command_input.value or ""
            except Exception:
                pending_command = ""

            block_reason = self._get_test_connection_block_reason(
                upstream,
                pending_command=pending_command,
                alias=alias,
            )
            state = (status or {}).get("state")
            if is_testing:
                label = "Connecting..."
            elif state == "success":
                label = "Refresh"
            elif state == "tls_error":
                label = "Connect anyway (insecure)"
            else:
                label = "Connect"

            updated_label = False
            try:
                # Use update() which forces a visual refresh, not just label assignment
                test_button.update(label)
                updated_label = True
            except Exception:
                # Fallback to direct label assignment
                try:
                    test_button.label = label
                    updated_label = True
                except Exception:
                    pass

            # Debug: Log label update result
            try:
                from ...debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "update_identity_widgets_label_set",
                        screen=self,
                        context={
                            "alias": alias,
                            "intended_label": label,
                            "state": state,
                            "updated_label": updated_label,
                            "actual_button_label": str(getattr(test_button, "label", None)),
                        },
                    )
            except Exception:
                pass

            test_button.disabled = bool(is_testing or block_reason)

            if block_reason:
                tooltip_text = block_reason
            elif is_testing:
                tooltip_text = "Connecting..."
            elif (status or {}).get("state") == "error" and (status or {}).get(
                "message"
            ):
                tooltip_text = status.get("message")
            else:
                tooltip_text = None

            test_button.tooltip = tooltip_text
            try:
                test_button.refresh()
            except Exception:
                pass

            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "test_connection_widget_state",
                        screen=self,
                        widget=test_button,
                        context={
                            "server_alias": getattr(upstream, "name", None),
                            "button_disabled": test_button.disabled,
                            "button_label": getattr(test_button, "label", None),
                            "block_reason": block_reason,
                            "pending_command": pending_command,
                            "status_state": (status or {}).get("state"),
                        },
                    )
            except Exception:
                pass

    def _is_server_connected(self, server_name: str) -> bool:
        """Check if a server is currently connected."""
        # See issue #104: Implement actual server connection status check
        return False  # Placeholder

    async def _handle_test_connection(self) -> None:
        """Core logic for triggering a manual connection test."""
        upstream = self._get_selected_upstream()
        alias = getattr(upstream, "name", None)

        if not upstream or not alias:
            return

        status = self._get_identity_status(alias)
        if status.get("state") == "testing":
            return

        pending_command = ""
        try:
            command_input = self.query_one("#server_command_input", Input)
            pending_command = command_input.value or ""
        except Exception:
            pending_command = ""

        block_reason = self._get_test_connection_block_reason(
            upstream, pending_command=pending_command, alias=alias
        )
        if block_reason:
            try:
                self.app.notify(block_reason, severity="warning")
            except Exception:
                pass
            return

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "test_connection_start",
                    screen=self,
                    context={
                        "server_alias": alias,
                        "pending_connection": pending_command,
                        "transport": upstream.transport,
                        "has_persisted_command": bool(upstream.command),
                        "has_persisted_url": bool(upstream.url),
                    },
                )
        except Exception:
            pass

        # Always sync pending connection to upstream before testing
        # This handles both URL (http) and command (stdio) via auto-detection
        if pending_command.strip():
            if upstream.transport == "http":
                current_url = upstream.url or ""
                if pending_command.strip() != current_url.strip():
                    self._commit_connection_input(pending_command)
                    upstream = self._get_selected_upstream()
            else:
                current_command = " ".join(upstream.command) if upstream.command else ""
                if pending_command.strip() != current_command.strip():
                    self._commit_connection_input(pending_command)
                    upstream = self._get_selected_upstream()

        # Validate connection info based on transport
        if upstream.transport == "http":
            if not upstream.url:
                try:
                    self.app.notify(
                        "Enter a URL before testing this server.",
                        severity="warning",
                    )
                except Exception:
                    pass
                return
        else:
            if not upstream.command:
                try:
                    self.app.notify(
                        "Enter a launch command before testing this server.",
                        severity="warning",
                    )
                except Exception:
                    pass
                return

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "test_connection_after_commit",
                    screen=self,
                    context={
                        "server_alias": alias,
                        "persisted_command": upstream.command,
                        "pending_cache": getattr(
                            self, "_pending_connection_cache", {}
                        ).get(alias),
                    },
                )
        except Exception:
            pass

        # Check if we're retrying after TLS error - if so, disable verification
        retrying_without_tls = status.get("state") == "tls_error"
        if retrying_without_tls and upstream.transport == "http":
            upstream.tls_verify = False
            self._mark_dirty()
            # Keep TLS warning visible as reminder that connection is insecure

        self._set_identity_status(alias, "testing")

        async def _run_test() -> None:
            # Helper to restore focus after test completes (success or error)
            def _restore_focus():
                try:
                    test_button = self.query_one("#test_connection_button", Button)
                    if getattr(test_button, "can_focus", False):
                        test_button.focus()
                except Exception:
                    pass

            message: Optional[str] = None
            # Clear existing identity so we can detect if the new connection succeeds
            upstream.server_identity = None

            try:
                await self._discover_identity_for_upstream(upstream)
            except Exception as exc:
                message = str(exc) or "Connection test failed."

            identity = getattr(upstream, "server_identity", None)
            if identity:
                # DEBUG: Log state before setting success
                try:
                    from ...debug import get_debug_logger
                    logger = get_debug_logger()
                    if logger:
                        logger.log_event(
                            "CONNECTION_SUCCESS_PRE_STATE",
                            screen=self,
                            context={
                                "alias": alias,
                                "selected_server": self.selected_server,
                                "alias_matches_selected": alias == self.selected_server,
                                "tls_verify": getattr(upstream, "tls_verify", True),
                                "transport": upstream.transport,
                                "identity": identity,
                            },
                        )
                except Exception:
                    pass

                self._set_identity_status(alias, "success")

                # DEBUG: Log state after setting success
                try:
                    from ...debug import get_debug_logger
                    logger = get_debug_logger()
                    if logger:
                        status_after = self._get_identity_status(alias)
                        logger.log_event(
                            "CONNECTION_SUCCESS_POST_STATE",
                            screen=self,
                            context={
                                "alias": alias,
                                "status_after": status_after,
                                "selected_server": self.selected_server,
                            },
                        )
                except Exception:
                    pass

                # Hide TLS warning only if connection is secure (tls_verify=true)
                # Show/keep it if user connected insecurely (tls_verify=false)
                tls_verify_value = getattr(upstream, "tls_verify", True)
                should_show_warning = upstream.transport == "http" and tls_verify_value is False

                # DEBUG: Log TLS warning decision
                try:
                    from ...debug import get_debug_logger
                    logger = get_debug_logger()
                    if logger:
                        logger.log_event(
                            "TLS_WARNING_DECISION",
                            screen=self,
                            context={
                                "transport": upstream.transport,
                                "tls_verify_value": tls_verify_value,
                                "tls_verify_is_false": tls_verify_value is False,
                                "should_show_warning": should_show_warning,
                            },
                        )
                except Exception:
                    pass

                if should_show_warning:
                    # Show warning as reminder of insecure connection
                    self._show_tls_warning(True)
                else:
                    self._show_tls_warning(False)

                # Show success notification
                try:
                    self.app.notify(
                        f"Connection to {identity} successful",
                        severity="success",
                        timeout=5
                    )
                except Exception:
                    pass

                # Auto-apply identity as alias if still using placeholder name
                if self._is_placeholder_name(alias):
                    try:
                        suggested_name = self._sanitize_identity_for_alias(identity)
                        # _commit_server_name() handles all validation including uniqueness
                        # If the name is invalid/duplicate, it will show error and revert
                        await self._commit_server_name(suggested_name)
                    except Exception:
                        pass  # Don't fail the test if renaming fails

                # Restore focus after test completes (after any auto-rename)
                # TODO: Replace with proper Textual event-based focus management instead of guessing timer delay
                self.set_timer(0.01, _restore_focus)
                return

            if not message:
                # Check for actual error messages from tool discovery, not placeholder messages
                tool_state = getattr(self, "server_tool_map", {}).get(alias) or {}
                tool_status = tool_state.get("status")
                # Only use the message if it's from an actual error, not a placeholder
                if tool_status == "error":
                    message = tool_state.get("message")

            if not message:
                message = "Server did not report an identity."

            # Check if this is a TLS error and show the warning widget
            is_tls_error = upstream.transport == "http" and self._is_tls_error(message)
            if is_tls_error:
                # Use tls_error state so button shows "Connect anyway (insecure)"
                self._set_identity_status(alias, "tls_error", message)
                self._show_tls_warning(True)
            else:
                self._set_identity_status(alias, "error", message)
                self._show_tls_warning(False)

            try:
                if is_tls_error:
                    # TLS errors are warnings with guidance on how to proceed
                    tls_message = f"{message}. To connect insecurely, click 'Connect anyway'."
                    self.app.notify(tls_message, severity="warning", timeout=10)
                else:
                    self.app.notify(message, severity="error", timeout=5)
            except Exception:
                pass

            # Restore focus after error
            # TODO: Replace with proper Textual event-based focus management instead of guessing timer delay
            self.set_timer(0.01, _restore_focus)

        try:
            self._run_worker(_run_test())
        except Exception:
            await _run_test()
