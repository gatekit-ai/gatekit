"""Server management functionality for Config Editor screen."""

import asyncio
from functools import partial
from typing import Awaitable, Callable, Dict, Optional
import re
import shlex
from textual import on
from textual.widgets import ListView, ListItem, Label, Button, Static, Input
from textual.containers import Container, Horizontal

from gatekit.config.models import UpstreamConfig
from ..simple_modals import MessageModal, ConfirmModal
from ...utils.terminal_compat import get_selection_indicator


class AsyncCallbackButton(Button):
    """Button that invokes an async callback when pressed.

    Handles both mouse clicks and Enter key presses by listening to Button.Pressed,
    which is the proper Textual pattern for button activation.
    """

    def __init__(
        self,
        label: str,
        *,
        callback: Optional[Callable[[], Awaitable[None]]] = None,
        **kwargs,
    ) -> None:
        super().__init__(label, **kwargs)
        self._async_callback = callback

    def set_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._async_callback = callback

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press from both mouse and keyboard (Enter key)."""
        if self._async_callback:
            asyncio.create_task(self._async_callback())


class ServerManagementMixin:
    """Mixin providing server management functionality for ConfigEditorScreen."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Timer for pending focus advancement after command/name submission
        self._pending_focus_timer: Optional[any] = None

    def _cancel_pending_focus_timer(self) -> None:
        """Cancel any pending focus advancement timer."""
        if self._pending_focus_timer is not None:
            try:
                self._pending_focus_timer.pause()
            except Exception:
                pass
            self._pending_focus_timer = None

    async def _populate_servers_list(self) -> None:
        """Populate the MCP servers list."""
        servers_list = self.query_one("#servers_list", ListView)
        await servers_list.clear()

        # Debug: Log what we're about to populate
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "populate_servers_list_start",
                    screen=self,
                    context={
                        "config_upstreams_count": len(self.config.upstreams),
                        "config_upstreams_names": [u.name for u in self.config.upstreams],
                        "selected_server": self.selected_server,
                    }
                )
        except Exception:
            pass

        # Update the title with count instead of a header row inside the list
        try:
            title = self.query_one("#servers_title", Static)
            title.update(f"  MCP Servers ({len(self.config.upstreams)})")
        except Exception:
            pass

        # Add each server (simplified display)
        indicator = get_selection_indicator()
        for idx, upstream in enumerate(self.config.upstreams):
            # Simple display with selection indicator
            is_selected = upstream.name == self.selected_server
            prefix = f"{indicator} " if is_selected else "  "

            server_item = ListItem(Label(f"{prefix}{upstream.name}"))
            server_item.data_server_name = upstream.name
            servers_list.append(server_item)

            # Debug: Log each item added
            try:
                from ...debug import get_debug_logger
                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "servers_list_item_added",
                        screen=self,
                        context={
                            "index": idx,
                            "server_name": upstream.name,
                            "is_selected": is_selected,
                            "data_server_name": server_item.data_server_name,
                        }
                    )
            except Exception:
                pass

        # Ensure the ListView has a valid initial highlight; schedule after render
        def _apply_initial_index() -> None:
            try:
                lst = self.query_one("#servers_list", ListView)
                items = list(lst.children)

                # Debug: Log actual items in the list
                try:
                    from ...debug import get_debug_logger
                    logger = get_debug_logger()
                    if logger:
                        logger.log_event(
                            "list_apply_index_items",
                            widget=lst,
                            screen=self,
                            context={
                                "list": "servers_list",
                                "items_count": len(items),
                                "items_data": [
                                    {
                                        "idx": idx,
                                        "data_server_name": getattr(it, "data_server_name", None),
                                        "type": type(it).__name__,
                                    }
                                    for idx, it in enumerate(items)
                                ],
                                "selected_server": self.selected_server,
                            },
                        )
                except Exception:
                    pass

                if not items:
                    return
                new_index = None
                if self.selected_server:
                    for idx, it in enumerate(items):
                        if (
                            getattr(it, "data_server_name", None)
                            == self.selected_server
                        ):
                            new_index = idx
                            break
                if new_index is None:
                    new_index = 0
                # Only set if changed or invalid
                cur = getattr(lst, "index", None)
                if cur is None or cur < 0 or cur >= len(items) or cur != new_index:
                    lst.index = new_index
                # Debug
                try:
                    from ...debug import get_debug_logger

                    logger = get_debug_logger()
                    if logger:
                        logger.log_event(
                            "list_init_index",
                            widget=lst,
                            screen=self,
                            context={
                                "list": "servers_list",
                                "index": new_index,
                                "count": len(items),
                                "current_index": cur,
                            },
                        )
                except Exception:
                    pass
            except Exception:
                pass

        # Set immediately (best-effort) and then after refresh to ensure it sticks
        _apply_initial_index()
        self.call_after_refresh(_apply_initial_index)

    def _generate_new_server_name(self) -> str:
        """Generate a unique placeholder name for a new server."""
        base_name = "new-mcp-server"
        existing_names = {u.name for u in self.config.upstreams}
        suffix = 1
        while True:
            candidate = f"{base_name}-{suffix}"
            if candidate not in existing_names:
                return candidate
            suffix += 1

    def _validate_server_name(
        self, name: str, current_name: Optional[str] = None
    ) -> Optional[str]:
        """Validate a prospective server alias and return an error message if invalid."""
        trimmed = name.strip()
        if not trimmed:
            return "Server alias is required."

        if trimmed.lower() == "_global":
            return "Server alias '_global' is reserved."

        if trimmed.startswith("_"):
            return "Server aliases cannot start with an underscore."

        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$", trimmed):
            return (
                "Server alias must start with a letter or number and can only include letters, "
                "numbers, dashes, or underscores (max 48 characters)."
            )

        lower_trimmed = trimmed.lower()
        for upstream in self.config.upstreams:
            if upstream.name == current_name:
                continue
            if upstream.name.lower() == lower_trimmed:
                return f"Server '{trimmed}' already exists."

        return None

    def _rename_server_references(self, old_name: str, new_name: str) -> None:
        """Update plugin mappings and caches when a server is renamed."""
        if self.config.plugins:
            for plugin_type in ("security", "middleware", "auditing"):
                plugin_mapping = getattr(self.config.plugins, plugin_type, None)
                if isinstance(plugin_mapping, dict) and old_name in plugin_mapping:
                    plugin_mapping[new_name] = plugin_mapping.pop(old_name)

        if hasattr(self, "_override_stash"):
            updated: dict[tuple[str, str, str], dict] = {}
            for key, value in self._override_stash.items():
                server_name, plugin_type, handler_name = key
                if server_name == old_name:
                    updated[(new_name, plugin_type, handler_name)] = value
                else:
                    updated[(server_name, plugin_type, handler_name)] = value
            self._override_stash = updated

        if hasattr(self, "server_identity_map"):
            if old_name in self.server_identity_map:
                self.server_identity_map[new_name] = self.server_identity_map.pop(old_name)

        if hasattr(self, "_identity_test_status"):
            if old_name in self._identity_test_status:
                self._identity_test_status[new_name] = self._identity_test_status.pop(
                    old_name
                )

        if hasattr(self, "_pending_command_cache"):
            if old_name in self._pending_command_cache:
                self._pending_command_cache[new_name] = self._pending_command_cache.pop(
                    old_name
                )

        if hasattr(self, "server_tool_map"):
            if old_name in self.server_tool_map:
                self.server_tool_map[new_name] = self.server_tool_map.pop(old_name)

    def _is_placeholder_name(self, name: str) -> bool:
        """Check if a server name matches the auto-generated placeholder pattern."""
        return bool(re.match(r'^new-mcp-server-\d+$', name))

    def _sanitize_identity_for_alias(self, identity: str) -> str:
        """Convert server identity into a valid server alias.
        
        Handles path-like identities, removes common prefixes, replaces invalid
        characters, and ensures the result is a valid alias format.
        Note: Does NOT check for uniqueness - that's handled by _validate_server_name().
        """
        # Extract last component if path-like (@scope/package -> package)
        if '/' in identity:
            identity = identity.split('/')[-1]
        
        # Remove common prefixes
        for prefix in ['server-', 'mcp-', '@']:
            if identity.startswith(prefix):
                identity = identity[len(prefix):]
                break  # Only remove one prefix
        
        # Replace invalid chars with dash
        sanitized = re.sub(r'[^A-Za-z0-9_-]', '-', identity)
        
        # Strip leading invalid chars (must start with letter/number)
        sanitized = re.sub(r'^[^A-Za-z0-9]+', '', sanitized)
        
        # Truncate to 48 chars
        sanitized = sanitized[:48]
        
        # Ensure not empty
        return sanitized or "mcp-server"

    def _ensure_initial_server_highlight(self) -> None:
        """Re-assert initial highlight after mount/refresh if needed."""
        try:
            lst = self.query_one("#servers_list", ListView)
            items = list(lst.children)
            if not items:
                return
            if (
                getattr(lst, "index", None) is None
                or lst.index < 0
                or lst.index >= len(items)
            ):
                lst.index = 0

                try:
                    from ...debug import get_debug_logger

                    logger = get_debug_logger()
                    if logger:
                        logger.log_event(
                            "list_ensure_index",
                            widget=lst,
                            screen=self,
                            context={
                                "list": "servers_list",
                                "index": 0,
                                "count": len(items),
                                "auto_selected_server": getattr(
                                    self, "selected_server", None
                                ),
                            },
                        )
                except Exception:
                    pass
        except Exception:
            pass

    async def _activate_server_item(self, item: ListItem | None) -> None:
        """Ensure the given list item is treated as the active server."""
        # COMPREHENSIVE LOGGING for debugging triangle updates
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "ACTIVATE_SERVER_ITEM_CALLED",
                    screen=self,
                    context={
                        "item": str(item),
                        "item_has_data_server_name": (
                            hasattr(item, "data_server_name") if item else False
                        ),
                        "item_data_server_name": (
                            getattr(item, "data_server_name", None) if item else None
                        ),
                        "current_selected_server": self.selected_server,
                    },
                )
        except Exception as e:
            print(f"Debug logging failed in _activate_server_item: {e}")

        if not item or not hasattr(item, "data_server_name"):
            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "ACTIVATE_SERVER_ITEM_EARLY_RETURN",
                        screen=self,
                        context={
                            "reason": "no_item_or_no_data_server_name",
                            "item": str(item),
                            "has_data_server_name": (
                                hasattr(item, "data_server_name") if item else False
                            ),
                        },
                    )
            except Exception:
                pass
            return

        server_name = item.data_server_name
        old_selected = self.selected_server
        self.selected_server = server_name

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "SERVER_SELECTION_CHANGED",
                    screen=self,
                    context={
                        "old_selected_server": old_selected,
                        "new_selected_server": server_name,
                        "selection_actually_changed": old_selected != server_name,
                    },
                )
        except Exception:
            pass

        # Only refresh if the selection actually changed
        if old_selected != server_name:
            # Update just the triangle indicators without rebuilding the list
            self._update_selection_indicators()
            await self._populate_server_details()

    def _update_selection_indicators(self) -> None:
        """Update the triangle indicators to show the currently selected server."""
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "UPDATE_SELECTION_INDICATORS_CALLED",
                    screen=self,
                    context={"selected_server": self.selected_server},
                )
        except Exception:
            pass

        try:
            servers_list = self.query_one("#servers_list", ListView)

            updated_count = 0
            indicator = get_selection_indicator()
            # Update each list item's label to show/hide the selection indicator
            for list_item in servers_list.children:
                if hasattr(list_item, "data_server_name"):
                    server_name = list_item.data_server_name
                    is_selected = server_name == self.selected_server
                    prefix = f"{indicator} " if is_selected else "  "

                    # Find the label within the list item and update its text
                    label = list_item.query_one("Label")
                    old_text = (
                        str(label.content)
                        if hasattr(label, "content")
                        else "unknown"
                    )
                    new_text = f"{prefix}{server_name}"
                    label.update(new_text)
                    updated_count += 1

                    try:
                        from ...debug import get_debug_logger

                        logger = get_debug_logger()
                        if logger:
                            logger.log_event(
                                "TRIANGLE_UPDATED",
                                screen=self,
                                context={
                                    "server_name": server_name,
                                    "is_selected": is_selected,
                                    "old_text": str(old_text),
                                    "new_text": new_text,
                                    "prefix": prefix,
                                },
                            )
                    except Exception:
                        pass

            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "UPDATE_SELECTION_INDICATORS_COMPLETED",
                        screen=self,
                        context={
                            "updated_count": updated_count,
                            "selected_server": self.selected_server,
                        },
                    )
            except Exception:
                pass

        except Exception as e:
            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "UPDATE_SELECTION_INDICATORS_FAILED",
                        screen=self,
                        context={
                            "error": str(e),
                            "selected_server": self.selected_server,
                        },
                    )
            except Exception:
                pass
            # If we can't update indicators, fall back to full repopulation
            # This ensures the UI stays consistent even if something goes wrong
            self.call_after_refresh(self._populate_servers_list)

    def _get_selected_upstream(self) -> Optional[UpstreamConfig]:
        """Return the currently selected upstream configuration, if any."""
        if not self.selected_server:
            return None

        return next(
            (u for u in self.config.upstreams if u.name == self.selected_server),
            None,
        )

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

    def _on_command_value_watch(
        self, alias: str, old_value: Optional[str], new_value: Optional[str]
    ) -> None:
        """Track live command edits to drive Test Connection enablement."""
        try:
            if not hasattr(self, "_pending_command_cache"):
                self._pending_command_cache = {}

            self._pending_command_cache[alias] = (new_value or "")

            self._update_identity_widgets(alias)
        except Exception:
            pass

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "command_value_watch",
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
            placeholder = "Add command and press Connect"
        else:
            placeholder = "Press Connect to discover server"
        tooltip: Optional[str] = None
        identity_value = upstream.server_identity or ""

        state = (status or {}).get("state") or "idle"
        message = (status or {}).get("message")

        if state == "testing":
            identity_value = "Testing connection..."
        elif not identity_value:
            if state == "error":
                identity_value = "Connection failed"
                tooltip = message
            else:
                identity_value = ""
        else:
            if state == "error" and message:
                tooltip = message

        return identity_value, placeholder, tooltip

    def _get_test_connection_block_reason(
        self,
        upstream: Optional[UpstreamConfig],
        *,
        pending_command: Optional[str] = None,
        alias: Optional[str] = None,
    ) -> Optional[str]:
        """Return a human-readable reason why test connection is unavailable."""
        if upstream is None:
            return "Select a server before testing the connection."
        if upstream.transport != "stdio":
            return "Connection testing is only available for stdio transports."
        if upstream.command:
            return None

        command_text = pending_command or ""
        if not command_text and alias and hasattr(self, "_pending_command_cache"):
            command_text = self._pending_command_cache.get(alias, "")

        if not command_text.strip():
            # Attempt to read directly from the mounted widget if available
            try:
                command_input = self.query_one("#server_command_input", Input)
                command_text = command_input.value or ""
            except Exception:
                command_text = ""

        if command_text.strip():
            result = None
        else:
            result = "Enter a launch command before testing this server."

        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "test_connection_block_reason",
                    screen=self,
                    context={
                        "server_alias": getattr(upstream, "name", None),
                        "transport": getattr(upstream, "transport", None),
                        "has_persisted_command": bool(getattr(upstream, "command", None)),
                        "pending_cache": self._pending_command_cache.get(alias)
                        if hasattr(self, "_pending_command_cache")
                        else None,
                        "pending_command": command_text,
                        "pending_command_trimmed": command_text.strip(),
                        "result": result,
                    },
                )
        except Exception:
            pass

        return result

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
            else:
                label = "Connect"

            updated_label = False
            try:
                test_button.label = label
                updated_label = True
            except Exception:
                pass

            if not updated_label:
                try:
                    test_button.update(label)
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

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection events from the servers ListView."""
        # COMPREHENSIVE LOGGING for debugging
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "LIST_VIEW_SELECTED_EVENT",
                    widget=event.list_view,
                    screen=self,
                    context={
                        "event_type": "ListView.Selected",
                        "list_view_id": getattr(event.list_view, "id", None),
                        "item": str(event.item),
                        "item_data_server_name": getattr(
                            event.item, "data_server_name", None
                        ),
                        "current_selected_server": self.selected_server,
                        "event_source": "KEYBOARD_OR_MOUSE",
                    },
                )
        except Exception as e:
            print(f"Debug logging failed in on_list_view_selected: {e}")

        if getattr(event.list_view, "id", None) != "servers_list":
            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "LIST_VIEW_SELECTED_WRONG_ID",
                        screen=self,
                        context={
                            "expected_id": "servers_list",
                            "actual_id": getattr(event.list_view, "id", None),
                        },
                    )
            except Exception:
                pass
            return

        await self._activate_server_item(event.item)

    async def on_server_name_blurred(self, event: Input.Blurred) -> None:
        """Validate and persist server name edits when the field loses focus."""
        await self._commit_server_name(event.input.value)

    async def on_server_name_submitted(self, event: Input.Submitted) -> None:
        """Validate and persist server name edits when the user presses enter."""
        await self._commit_server_name(event.value)

        # Advance focus to next control (command input)
        # Cancel any previous pending focus timer first
        self._cancel_pending_focus_timer()

        def _advance_focus() -> None:
            try:
                command_input = self.query_one("#server_command_input", Input)
                if getattr(command_input, "can_focus", False):
                    command_input.focus()
            except Exception:
                pass
            # Clear the timer reference after it fires
            self._pending_focus_timer = None

        # Store the timer so we can cancel it if user does something else
        self._pending_focus_timer = self.set_timer(0.01, _advance_focus)

    @on(ListView.Highlighted, "#servers_list")
    async def on_server_highlighted(self, event: ListView.Highlighted) -> None:
        """Update server details when a list item becomes highlighted (keyboard or mouse)."""
        # COMPREHENSIVE LOGGING for debugging
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "LIST_VIEW_HIGHLIGHTED_EVENT",
                    widget=event.list_view,
                    screen=self,
                    context={
                        "event_type": "ListView.Highlighted",
                        "list_view_id": getattr(event.list_view, "id", None),
                        "item": str(event.item),
                        "item_data_server_name": getattr(
                            event.item, "data_server_name", None
                        ),
                        "current_selected_server": self.selected_server,
                        "event_source": "KEYBOARD_NAVIGATION_OR_MOUSE_HOVER",
                    },
                )
        except Exception as e:
            print(f"Debug logging failed in on_server_highlighted: {e}")

        name = getattr(event.item, "data_server_name", None)
        if name:
            # Debug
            try:
                from ...debug import get_debug_logger

                logger = get_debug_logger()
                if logger:
                    logger.log_event(
                        "list_highlight",
                        widget=self.query_one("#servers_list", ListView),
                        screen=self,
                        context={
                            "list": "servers_list",
                            "highlighted": name,
                            "old_server": self.selected_server,
                            "action": "HIGHLIGHT_ONLY_NO_SELECTION",
                        },
                    )
            except Exception:
                pass
            # Note: Highlighting should NOT trigger server selection/activation
            # Only ListView.Selected events should do that

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

        if upstream.transport == "stdio":
            # Always render the command input so drafts can be completed inline
            cmd_value = " ".join(upstream.command) if upstream.command else ""
            cmd_input = Input(value=cmd_value, id="server_command_input")
            cmd_input.placeholder = "npx -y @modelcontextprotocol/server-everything"
            cmd_input.add_class("-textual-compact")
            try:
                self.watch(
                    cmd_input,
                    "value",
                    partial(self._on_command_value_watch, alias),
                    init=False,
                )
            except Exception:
                pass
            cmd_row = Horizontal(Label("Command:", classes="server-label"), cmd_input)
            info_lines.append(cmd_row)

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

        if upstream.transport == "http":
            url_value = upstream.url or ""
            url_input = Input(value=url_value, id="server_url_input")
            url_input.placeholder = "https://example.com/mcp"
            url_input.add_class("-textual-compact")
            url_row = Horizontal(Label("URL:", classes="server-label"), url_input)
            info_lines.append(url_row)

        # Create horizontal container for "Transport:" label + disabled input (matching other fields)
        transport_input = Input(value=upstream.transport, id="server_transport_input")
        transport_input.add_class("-textual-compact")
        transport_input.disabled = True  # Disabled since we only support stdio
        transport_row = Horizontal(
            Label("Transport:", classes="server-label"), transport_input
        )
        info_lines.append(transport_row)

        # Mount the lines
        for line in info_lines:
            info_container.mount(line)

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

    async def _update_server_details(self) -> None:
        """Legacy method - redirect to new populate method."""
        await self._populate_server_details()

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

    @on(Button.Pressed, "#add_server")
    async def on_add_server_button(self, event: Button.Pressed) -> None:
        """Handle add server button press."""
        await self._handle_add_server()

    @on(Button.Pressed, "#remove_server")
    def on_remove_server_button(self, event: Button.Pressed) -> None:
        """Handle remove server button press."""
        self.run_worker(self._handle_remove_server())

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
                        "pending_command": pending_command,
                        "has_persisted_command": bool(upstream.command),
                    },
                )
        except Exception:
            pass

        # Always sync pending command to upstream before testing
        current_command = " ".join(upstream.command) if upstream.command else ""
        if pending_command.strip() and pending_command.strip() != current_command.strip():
            await self._commit_command_input(pending_command)
            upstream = self._get_selected_upstream()
            if not upstream or not upstream.command:
                return

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
                            self, "_pending_command_cache", {}
                        ).get(alias),
                    },
                )
        except Exception:
            pass

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
                self._set_identity_status(alias, "success")

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
                tool_state = getattr(self, "server_tool_map", {}).get(alias) or {}
                message = tool_state.get("message")

            if not message:
                message = "Server did not report an identity."

            self._set_identity_status(alias, "error", message)

            try:
                self.app.notify(message, severity="error")
            except Exception:
                pass

            # Restore focus after error
            # TODO: Replace with proper Textual event-based focus management instead of guessing timer delay
            self.set_timer(0.01, _restore_focus)

        try:
            self._run_worker(_run_test())
        except Exception:
            await _run_test()

    # Removed explicit Button.Pressed handlers; AsyncCallbackButton handles invocation.

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

        # Commit the value (may trigger panel refresh if changed)
        await self._commit_command_input(event.input.value)

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

        await self._commit_command_input(event.value)

        # Advance focus to next control (Test Connection button)
        # Cancel any previous pending focus timer first
        self._cancel_pending_focus_timer()

        def _advance_focus() -> None:
            try:
                test_button = self.query_one("#test_connection_button", Button)
                if getattr(test_button, "can_focus", False):
                    test_button.focus()
            except Exception:
                pass
            # Clear the timer reference after it fires
            self._pending_focus_timer = None

        # Store the timer so we can cancel it if user does something else
        self._pending_focus_timer = self.set_timer(0.01, _advance_focus)

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

    def _reset_command_input_scroll(self) -> None:
        """Reset the command input to show the beginning of the text."""
        try:
            command_input = self.query_one("#server_command_input", Input)
            self._reset_input_scroll(command_input)
        except Exception:
            pass

    async def _commit_command_input(self, raw_value: str) -> None:
        """Persist the command input for the selected server if valid."""
        upstream = self._get_selected_upstream()
        if not upstream:
            return

        normalized_value = raw_value.strip()

        # Get current command for comparison
        current_command = " ".join(upstream.command) if upstream.command else ""

        if not normalized_value:
            # Only mark dirty if we're actually changing the command
            if upstream.command is not None:
                upstream.command = None
                upstream.is_draft = True

                # Mark dirty after successful mutation
                self._mark_dirty()
            else:
                # Command was already None, no change
                upstream.is_draft = True

            if hasattr(self, "_pending_command_cache"):
                self._pending_command_cache.pop(upstream.name, None)
            try:
                self.app.notify(
                    f"Command is required for '{upstream.name}'.", severity="warning"
                )
            except Exception:
                pass
            # Update button state (will be disabled due to missing command)
            try:
                self._update_identity_widgets(upstream.name)
            except Exception:
                pass
            return

        try:
            parsed_command = shlex.split(normalized_value)
        except ValueError as exc:
            try:
                self.app.notify(f"Unable to parse command: {exc}", severity="error")
            except Exception:
                pass
            # Parse error - refocus the input for correction
            def _refocus_command() -> None:
                try:
                    command_input = self.query_one("#server_command_input", Input)
                    if getattr(command_input, "can_focus", False):
                        command_input.focus()
                except Exception:
                    pass

            self.call_after_refresh(_refocus_command)
            return

        # Only mark dirty if command actually changed
        new_command = " ".join(parsed_command)
        if new_command != current_command:
            upstream.command = parsed_command
            upstream.is_draft = False

            # Mark dirty after successful mutation
            self._mark_dirty()
        else:
            # Command unchanged, just ensure draft state is correct
            upstream.command = parsed_command
            upstream.is_draft = False

        if hasattr(self, "_pending_command_cache"):
            self._pending_command_cache[upstream.name] = normalized_value

        # Initialize server_tool_map entry when server transitions from draft to non-draft
        # This ensures the Tool Manager modal can display a proper "pending discovery" state
        # instead of showing "waiting for discovery" indefinitely
        if hasattr(self, "server_tool_map") and upstream.name not in self.server_tool_map:
            self.server_tool_map[upstream.name] = {
                "tools": [],
                "last_refreshed": None,
                "status": "pending",
                "message": "Server configuration complete. Click 'Connect' to discover tools.",
            }

        # Note: Configuration changes are not auto-saved. User must click Save.
        # Just update the Test Connection button state - no need to rebuild the entire panel
        try:
            self._update_identity_widgets(upstream.name)
        except Exception:
            pass

    async def _handle_add_server(self) -> None:
        """Create a new draft server and switch the detail pane into edit mode."""
        # Disable buttons during operation to prevent re-entrancy
        try:
            add_btn = self.query_one("#add_server", Button)
            add_btn.disabled = True
        except Exception:
            pass

        logger = None
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "add_server_start",
                    screen=self,
                    context={
                        "existing_servers": [u.name for u in self.config.upstreams]
                    },
                )
        except Exception:
            logger = None  # Debug logging best-effort

        try:
            new_name = self._generate_new_server_name()
            new_upstream = UpstreamConfig.create_draft(name=new_name)

            self.config.upstreams.append(new_upstream)
            self.selected_server = new_name

            # Mark dirty after successful mutation
            self._mark_dirty()

            if hasattr(self, "_pending_command_cache"):
                self._pending_command_cache[new_name] = ""

            await self._populate_servers_list()
            await self._populate_server_details()

            try:
                if logger:
                    logger.log_event(
                        "add_server_created",
                        screen=self,
                        context={
                            "new_server": new_name,
                            "total_servers": len(self.config.upstreams),
                        },
                    )
            except Exception:
                pass

            # Refresh plugin manager/navigation so the new server participates fully
            try:
                await self._rebuild_runtime_state()
            except Exception as exc:
                if logger:
                    logger.log_event(
                        "add_server_rebuild_failed",
                        screen=self,
                        context={"error": str(exc)},
                    )

            try:
                self._setup_navigation_containers()
            except Exception:
                pass

            # Focus the command input so users can start typing immediately
            def _focus_command() -> None:
                try:
                    from ...debug import get_debug_logger
                    logger = get_debug_logger()
                    if logger:
                        logger.log_event(
                            "add_server_focus_attempt",
                            screen=self,
                            context={"server": new_name},
                        )
                    command_input = self.query_one("#server_command_input", Input)
                    can_focus = getattr(command_input, "can_focus", False)
                    if logger:
                        logger.log_event(
                            "add_server_focus_widget_found",
                            screen=self,
                            context={"can_focus": can_focus, "widget_id": command_input.id},
                        )
                    if can_focus:
                        command_input.focus()
                        if logger:
                            logger.log_event(
                                "add_server_focus_success",
                                screen=self,
                                context={"server": new_name},
                            )
                except Exception as exc:
                    if logger:
                        logger.log_event(
                            "add_server_focus_failed",
                            screen=self,
                            context={"server": new_name, "error": str(exc)},
                        )

            # TODO: Replace with proper Textual event-based focus management instead of guessing timer delay
            # This needs 100ms because after test connection + add server, multiple plugin renders occur
            self.set_timer(0.1, _focus_command)

            # Provide gentle inline guidance
            try:
                self.app.notify(
                    "Add a launch command and press Connect to finish setup",
                    severity="information",
                )
            except Exception:
                pass
        finally:
            try:
                add_btn = self.query_one("#add_server", Button)
                add_btn.disabled = False
            except Exception:
                pass

    async def _handle_remove_server(self) -> None:
        """Remove the selected server."""
        if not self.selected_server:
            await self.app.push_screen(
                MessageModal("No Server Selected", "Please select a server to remove.")
            )
            return

        # Disable buttons during operation to prevent re-entrancy
        try:
            remove_btn = self.query_one("#remove_server", Button)
            remove_btn.disabled = True
        except Exception:
            pass

        try:
            # Confirm removal
            confirm = await self.app.push_screen_wait(
                ConfirmModal(
                    f"Remove server '{self.selected_server}'?",
                    "This will also remove all server-specific plugin configurations.",
                )
            )

            if confirm:
                removed_alias = self.selected_server
                # Remove from upstreams
                self.config.upstreams = [
                    u for u in self.config.upstreams if u.name != self.selected_server
                ]

                # Remove plugin configurations (ensure all categories are cleaned)
                if self.config.plugins:
                    for plugin_type in ["security", "middleware", "auditing"]:
                        # Get the plugin type dict (not a model)
                        plugin_type_dict = getattr(self.config.plugins, plugin_type, {})
                        # Only delete if it's actually a dict with this key
                        if (
                            isinstance(plugin_type_dict, dict)
                            and self.selected_server in plugin_type_dict
                        ):
                            del plugin_type_dict[self.selected_server]

                # Clear any stashed override configs for this server to prevent memory leak
                stash_keys_to_remove = [
                    key
                    for key in self._override_stash.keys()
                    if key[0] == self.selected_server
                ]
                for key in stash_keys_to_remove:
                    del self._override_stash[key]

                if removed_alias and hasattr(self, "_identity_test_status"):
                    self._identity_test_status.pop(removed_alias, None)

                if removed_alias and hasattr(self, "_pending_command_cache"):
                    self._pending_command_cache.pop(removed_alias, None)

                # Mark dirty after successful mutation
                self._mark_dirty()

                # Auto-select next/previous server for better UX
                remaining_servers = [u.name for u in self.config.upstreams]
                if remaining_servers:
                    # Try to maintain selection position
                    current_names = [u.name for u in self.config.upstreams]
                    try:
                        old_index = current_names.index(self.selected_server)
                        # Select next server if available, otherwise previous
                        if old_index < len(remaining_servers):
                            self.selected_server = remaining_servers[old_index]
                        else:
                            self.selected_server = remaining_servers[-1]
                    except Exception:
                        self.selected_server = remaining_servers[0]
                else:
                    self.selected_server = None

                # Note: Configuration changes are not auto-saved. User must click Save.
                # Refresh UI
                await self._populate_servers_list()

                if self.selected_server:
                    await self._populate_server_details()
                else:
                    await self._clear_server_details()
        finally:
            try:
                remove_btn = self.query_one("#remove_server", Button)
                remove_btn.disabled = False
            except Exception:
                pass
