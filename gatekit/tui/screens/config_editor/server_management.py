"""Server management functionality for Config Editor screen.

This module provides the ServerManagementMixin which combines several specialized
mixins for server management:
- ServerValidationMixin: Name validation and sanitization
- ServerConnectionMixin: Connection testing and identity status
- ServerPersistenceMixin: Input handling and config persistence
- ServerDetailsMixin: Details panel rendering and placeholders
"""

from typing import List, Optional

from textual.widgets import Button, Static, Input

from gatekit.config.models import UpstreamConfig
from ..simple_modals import MessageModal, ConfirmModal
from ...widgets.server_list import (
    ServerListWidget,
    ServerEnabledToggle,
    ServerSelected,
    DynamicColumnDefinition,
    ColumnCellActivated,
    ColumnActionRequested,
    ColumnContextMenu,
)
from ...utils.output_schema import (
    OutputSchemaDiscovery,
    ServerColumnReader,
)

# Import sub-mixins
from .server_validation import ServerValidationMixin
from .server_connection import ServerConnectionMixin
from .server_persistence import ServerPersistenceMixin
from .server_details import ServerDetailsMixin


class ServerManagementMixin(
    ServerValidationMixin,
    ServerConnectionMixin,
    ServerPersistenceMixin,
    ServerDetailsMixin,
):
    """Mixin providing server management functionality for the Config Editor.

    Combines validation, connection testing, persistence, and UI rendering
    into a single mixin that can be used by the ConfigEditorScreen.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_focus_timer = None
        # Dynamic column polling state
        self._column_timer = None
        self._column_reader: Optional[ServerColumnReader] = None
        self._dynamic_columns: List[DynamicColumnDefinition] = []

    def _cancel_pending_focus_timer(self) -> None:
        """Cancel any pending focus timer."""
        if self._pending_focus_timer:
            try:
                self._pending_focus_timer.stop()
            except Exception:
                pass
            self._pending_focus_timer = None

    def _setup_dynamic_columns(self) -> None:
        """Discover and setup dynamic columns from plugins with output schemas."""
        try:
            from ...debug import get_debug_logger
            logger = get_debug_logger()
        except Exception:
            logger = None

        try:
            # Get config directory for path resolution
            config_dir = self.config_file_path.parent if self.config_file_path else None

            # Discover plugins with output schemas
            columns = OutputSchemaDiscovery.discover_server_columns()

            if not columns:
                if logger:
                    logger.log_event(
                        "dynamic_columns_none_discovered",
                        screen=self,
                        context={"message": "No plugins with server columns found"},
                    )
                return

            # Convert to DynamicColumnDefinition (one per ServerColumnDefinition)
            self._dynamic_columns = []
            for col in columns:
                col_def = DynamicColumnDefinition(
                    column_id=col.column_id,
                    header=col.label or col.key,
                    width=col.width,
                    formatter=col.format_value,
                    tooltip=col.tooltip,
                    context_menu=col.context_menu,
                    label=col.label,
                    key=col.key,
                    handler_name=col.handler_name,
                )
                self._dynamic_columns.append(col_def)

            # Create reader for polling values
            if columns and config_dir:
                self._column_reader = ServerColumnReader(
                    columns=columns,
                    config=self.config,
                    config_directory=config_dir,
                )

            if logger:
                logger.log_event(
                    "dynamic_columns_setup",
                    screen=self,
                    context={
                        "column_count": len(self._dynamic_columns),
                        "columns": [c.column_id for c in self._dynamic_columns],
                    },
                )

        except Exception as e:
            if logger:
                logger.log_event(
                    "dynamic_columns_setup_error",
                    screen=self,
                    context={"error": str(e)},
                )

    def _start_column_polling(self) -> None:
        """Start periodic polling for column updates."""
        if not self._dynamic_columns or not self._column_reader:
            return

        try:
            from ...debug import get_debug_logger
            _dbg = get_debug_logger()
        except Exception:
            _dbg = None

        if _dbg:
            _dbg.log_event(
                "COLUMN_POLLING_START",
                screen=self,
                context={
                    "interval_seconds": 2.0,
                    "column_count": len(self._dynamic_columns),
                    "columns": [c.column_id for c in self._dynamic_columns],
                },
            )

        # Initial update
        self._update_column_values()

        # Set up polling timer (every 2 seconds)
        if self._column_timer is None:
            self._column_timer = self.set_interval(2.0, self._update_column_values)

    def _stop_column_polling(self) -> None:
        """Stop the column polling timer."""
        if self._column_timer:
            try:
                self._column_timer.stop()
            except Exception:
                pass
            self._column_timer = None

    def on_unmount(self) -> None:
        """Clean up when the screen is unmounted."""
        self._stop_column_polling()
        # Call parent unmount if it exists
        if hasattr(super(), "on_unmount"):
            super().on_unmount()

    def _update_column_values(self) -> None:
        """Read values from plugins and update server list columns."""
        if not self._column_reader:
            return

        try:
            servers_list = self.query_one("#servers_list", ServerListWidget)
        except Exception:
            return

        try:
            from ...debug import get_debug_logger
            _dbg = get_debug_logger()
        except Exception:
            _dbg = None

        try:
            # Group columns by handler, read state file once per handler
            for handler_name, handler_cols in self._column_reader._columns_by_handler.items():
                server_values = self._column_reader.read_column_values(handler_name)

                if _dbg:
                    # Log a summary of what read_column_values returned
                    summary = {}
                    for sn, sv in server_values.items():
                        if sv is None:
                            summary[sn] = "None"
                        elif not sv:
                            summary[sn] = "{}"
                        else:
                            summary[sn] = sv
                    _dbg.log_event(
                        "UPDATE_COLUMN_VALUES_READ",
                        screen=self,
                        context={
                            "handler_name": handler_name,
                            "server_values_summary": summary,
                        },
                    )

                for col in handler_cols:
                    for server_name, values in server_values.items():
                        if values is None:
                            continue  # Plugin not configured — leave as dash
                        # values may be {} (configured but no data) — treat as 0
                        value = values.get(col.key, 0)
                        servers_list.update_column_value(
                            server_name, col.column_id, value
                        )
        except Exception as exc:
            # Gracefully handle read errors but log them
            if _dbg:
                _dbg.log_event(
                    "UPDATE_COLUMN_VALUES_ERROR",
                    screen=self,
                    context={
                        "error": str(exc),
                        "type": type(exc).__name__,
                    },
                )

    async def _populate_servers_list(self) -> None:
        """Populate the servers list with current configuration."""
        logger = None
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "populate_servers_list_start",
                    screen=self,
                    context={
                        "selected_server": self.selected_server,
                        "upstream_count": len(self.config.upstreams),
                    },
                )
        except Exception:
            pass

        servers_list = self.query_one("#servers_list", ServerListWidget)
        await servers_list.clear()

        # Setup dynamic columns if not already done (first-time discovery)
        if not self._dynamic_columns:
            self._setup_dynamic_columns()

        # Configure dynamic columns before adding servers
        if self._dynamic_columns:
            servers_list.set_dynamic_columns(self._dynamic_columns)

        # Update the title with count
        try:
            title = self.query_one("#servers_title", Static)
            enabled_count = sum(1 for u in self.config.upstreams if u.enabled)
            total_count = len(self.config.upstreams)
            title.update(f"  MCP Servers ({enabled_count}/{total_count})")
        except Exception:
            pass

        for upstream in self.config.upstreams:
            servers_list.add_server(upstream.name, enabled=upstream.enabled)

        # Start column polling after servers are added
        self._start_column_polling()

        # Set initial selection if needed
        if self.selected_server is None and self.config.upstreams:
            self.selected_server = self.config.upstreams[0].name

        try:
            if logger:
                logger.log_event(
                    "populate_servers_list_items_appended",
                    screen=self,
                    context={
                        "item_count": len(self.config.upstreams),
                        "selected_server": self.selected_server,
                    },
                )
        except Exception:
            pass

        # Update selection indicator and focus after widgets are mounted
        def _apply_initial_selection() -> None:
            if self.selected_server:
                servers_list.set_selected_server(self.selected_server)
                servers_list.focus_server_name(self.selected_server)

        self.call_after_refresh(_apply_initial_selection)

    def _ensure_initial_server_highlight(self) -> None:
        """Re-assert initial highlight after mount/refresh if needed."""
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "ensure_highlight_start",
                    screen=self,
                    context={"selected_server": self.selected_server},
                )
        except Exception:
            pass

        if not self.config.upstreams:
            return

        # Ensure we have a selected server
        if not self.selected_server:
            self.selected_server = self.config.upstreams[0].name

        # Focus the selected server's name widget
        try:
            servers_list = self.query_one("#servers_list", ServerListWidget)
            servers_list.focus_server_name(self.selected_server)
        except Exception:
            pass

    async def _activate_server_by_name(self, server_name: Optional[str]) -> None:
        """Activate (select) a server by name and update the detail pane."""
        logger = None
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
        except Exception:
            pass

        if not server_name:
            try:
                if logger:
                    logger.log_event(
                        "server_activation_failed",
                        screen=self,
                        context={"reason": "no_server_name"},
                    )
            except Exception:
                pass
            return

        try:
            if logger:
                logger.log_event(
                    "server_activated",
                    screen=self,
                    context={"server_name": server_name},
                )
        except Exception:
            pass

        # Avoid redundant processing if same server is already selected
        if server_name == self.selected_server:
            try:
                if logger:
                    logger.log_event(
                        "server_already_selected",
                        screen=self,
                        context={"server": server_name},
                    )
            except Exception:
                pass
            return

        self.selected_server = server_name

        try:
            if logger:
                logger.log_event(
                    "server_selection_changed",
                    screen=self,
                    context={"selected_server": server_name},
                )
        except Exception:
            pass

        await self._populate_server_details()

    def _update_selection_indicators(self) -> None:
        """Update the selection indicators in the servers list.

        Note: With ServerListWidget, visual selection is handled by focus.
        This method is kept for compatibility but does nothing.
        """
        pass

    def _get_selected_upstream(self) -> Optional[UpstreamConfig]:
        """Return the currently selected upstream configuration, if any."""
        if not self.selected_server:
            return None

        return next(
            (u for u in self.config.upstreams if u.name == self.selected_server),
            None,
        )

    async def on_server_selected(self, event: ServerSelected) -> None:
        """Handle server name selection (Enter/Space on server name)."""
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "SERVER_SELECTED",
                    screen=self,
                    context={
                        "server_name": event.server_name,
                        "previous_selected": self.selected_server,
                    },
                )
        except Exception:
            pass

        # For explicit selection, always populate details (even if "already selected")
        self.selected_server = event.server_name

        # Update the selection indicator in the server list
        try:
            servers_list = self.query_one("#servers_list", ServerListWidget)
            servers_list.set_selected_server(event.server_name)
        except Exception:
            pass

        await self._populate_server_details()

    async def on_server_enabled_toggle(self, event: ServerEnabledToggle) -> None:
        """Handle server enabled checkbox toggle."""
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "SERVER_ENABLED_TOGGLE",
                    screen=self,
                    context={
                        "event_type": "ServerEnabledToggle",
                        "server_name": event.server_name,
                        "enabled": event.enabled,
                    },
                )
        except Exception:
            pass

        # Update the config
        upstream = next(
            (u for u in self.config.upstreams if u.name == event.server_name), None
        )
        if upstream:
            upstream.enabled = event.enabled
            self._mark_dirty()

            # Update the title with new enabled count
            try:
                title = self.query_one("#servers_title", Static)
                enabled_count = sum(1 for u in self.config.upstreams if u.enabled)
                total_count = len(self.config.upstreams)
                title.update(f"  MCP Servers ({enabled_count}/{total_count})")
            except Exception:
                pass

    def on_column_cell_activated(self, event: ColumnCellActivated) -> None:
        """Handle column cell activation - show context menu."""
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "COLUMN_CELL_ACTIVATED",
                    screen=self,
                    context={
                        "server_name": event.server_name,
                        "column_id": event.column_id,
                        "handler_name": event.handler_name,
                        "cell_x": event.cell_x,
                        "cell_y": event.cell_y,
                    },
                )
        except Exception:
            pass

        # Look up the DynamicColumnDefinition to get context_menu and handler_name
        col_def = None
        for c in self._dynamic_columns:
            if c.column_id == event.column_id:
                col_def = c
                break

        if not col_def or not col_def.context_menu:
            return

        # Remove any existing context menus
        try:
            for existing in self.query(ColumnContextMenu):
                existing._dismissed = True
                existing.remove()
        except Exception:
            pass

        # Dismiss any tooltip so it doesn't obscure the context menu.
        # _clear_tooltip() hides already-visible tooltips but ignores pending timers,
        # so we also stop the timer directly to cover the not-yet-fired case.
        self.screen._clear_tooltip()
        tooltip_timer = getattr(self.screen, '_tooltip_timer', None)
        if tooltip_timer is not None:
            tooltip_timer.stop()
        self.screen._tooltip_widget = None

        # Create and mount context menu with positioning
        menu = ColumnContextMenu(
            server_name=event.server_name,
            column_id=event.column_id,
            handler_name=event.handler_name,
            context_menu=col_def.context_menu,
        )
        # Position the menu near the cell using CSS offset
        menu.styles.offset = (event.cell_x, event.cell_y)
        self.mount(menu)

    def on_column_action_requested(self, event: ColumnActionRequested) -> None:
        """Handle column action request from context menu."""
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "COLUMN_ACTION_REQUESTED",
                    screen=self,
                    context={
                        "column_id": event.column_id,
                        "handler_name": event.handler_name,
                        "method_name": event.method_name,
                        "server_name": event.server_name,
                        "scope": getattr(event, "scope", "MISSING"),
                        "confirm_title": event.confirm_title,
                        "has_confirm": bool(event.confirm_title),
                    },
                )
        except Exception:
            pass

        if event.confirm_title:
            # Plugin requested a confirmation dialog
            captured_event = event

            def _on_confirm(confirmed: bool) -> None:
                try:
                    from ...debug import get_debug_logger
                    _dbg = get_debug_logger()
                except Exception:
                    _dbg = None

                if _dbg:
                    _dbg.log_event(
                        "CONFIRM_MODAL_CALLBACK",
                        screen=self,
                        context={"confirmed": confirmed, "method_name": captured_event.method_name},
                    )
                if not confirmed:
                    return
                try:
                    self._perform_column_action(captured_event)
                except Exception as exc:
                    if _dbg:
                        _dbg.log_event(
                            "CONFIRM_MODAL_CALLBACK_ERROR",
                            screen=self,
                            context={"error": str(exc), "type": type(exc).__name__},
                        )
                    self.app.notify(f"Action failed: {exc}", severity="error")

            self.app.push_screen(
                ConfirmModal(event.confirm_title, event.confirm_message or ""),
                _on_confirm,
            )
        else:
            # No confirmation requested — execute immediately
            self._perform_column_action(event)

    def _perform_column_action(self, event: ColumnActionRequested) -> None:
        """Execute a plugin action after confirmation."""
        try:
            from ...debug import get_debug_logger
            _dbg = get_debug_logger()
        except Exception:
            _dbg = None

        if not self._column_reader:
            if _dbg:
                _dbg.log_event("PERFORM_COLUMN_ACTION_NO_READER", screen=self, context={})
            return

        handler_name = event.handler_name
        method_name = event.method_name
        server_name = event.server_name
        scope = getattr(event, "scope", "server")

        if _dbg:
            _dbg.log_event(
                "PERFORM_COLUMN_ACTION_START",
                screen=self,
                context={
                    "handler_name": handler_name,
                    "method_name": method_name,
                    "server_name": server_name,
                    "scope": scope,
                },
            )

        # Validate method_name: must be a valid identifier and not start with _
        if not method_name or not method_name.isidentifier() or method_name.startswith("_"):
            if _dbg:
                _dbg.log_event("PERFORM_COLUMN_ACTION_INVALID_METHOD", screen=self, context={"method_name": method_name})
            self.app.notify(
                f"Invalid method name '{method_name}'.", severity="warning"
            )
            return

        # Look up plugin class
        handler_cols = self._column_reader._columns_by_handler.get(handler_name)
        if not handler_cols:
            if _dbg:
                _dbg.log_event("PERFORM_COLUMN_ACTION_NO_HANDLER_COLS", screen=self, context={"handler_name": handler_name})
            self.app.notify(
                f"No columns found for handler '{handler_name}'.", severity="warning"
            )
            return

        plugin_class = handler_cols[0].plugin_class

        # Look up the method early so we fail fast
        method = getattr(plugin_class, method_name, None)
        if method is None:
            if _dbg:
                _dbg.log_event(
                    "PERFORM_COLUMN_ACTION_METHOD_NOT_FOUND",
                    screen=self,
                    context={"method_name": method_name, "plugin_class": str(plugin_class)},
                )
            self.app.notify(
                f"Method '{method_name}' not found on plugin.", severity="warning"
            )
            return

        if scope == "all_servers":
            # Fan-out action: call method on every unique state file so
            # per-server overrides with different files are also covered
            state_file_paths = self._column_reader.resolve_all_state_file_paths(
                handler_name
            )
            if _dbg:
                _dbg.log_event(
                    "PERFORM_COLUMN_ACTION_ALL_SERVERS",
                    screen=self,
                    context={"state_file_paths": [str(p) for p in state_file_paths]},
                )
            if not state_file_paths:
                self.app.notify(
                    f"Plugin '{handler_name}' is not configured.", severity="warning"
                )
                return

            errors = []
            last_message = ""
            for path in state_file_paths:
                try:
                    last_message = method(path, None)
                except Exception as e:
                    errors.append(str(e))

            if errors:
                self.app.notify(
                    f"Action failed on {len(errors)} state file(s): {'; '.join(errors)}",
                    severity="error",
                )
            elif last_message:
                self.app.notify(last_message, severity="information")
        else:
            # Per-server action: resolve a single state file
            plugin_config = self._column_reader._get_plugin_config(handler_name, server_name)
            if _dbg:
                _dbg.log_event(
                    "PERFORM_COLUMN_ACTION_PER_SERVER",
                    screen=self,
                    context={
                        "handler_name": handler_name,
                        "server_name": server_name,
                        "plugin_config": str(plugin_config),
                    },
                )
            if plugin_config is None:
                self.app.notify(
                    f"Plugin '{handler_name}' is not configured for '{server_name}'.",
                    severity="warning",
                )
                return
            state_file_path = self._column_reader._resolve_state_file_path(
                handler_cols[0], plugin_config
            )
            if _dbg:
                _dbg.log_event(
                    "PERFORM_COLUMN_ACTION_STATE_FILE",
                    screen=self,
                    context={"state_file_path": str(state_file_path)},
                )
            if not state_file_path:
                self.app.notify(
                    "Could not resolve state file path.", severity="error"
                )
                return
            try:
                message = method(state_file_path, server_name)
                if _dbg:
                    _dbg.log_event(
                        "PERFORM_COLUMN_ACTION_SUCCESS",
                        screen=self,
                        context={"message": message},
                    )
                self.app.notify(message, severity="information")
            except Exception as e:
                if _dbg:
                    _dbg.log_event(
                        "PERFORM_COLUMN_ACTION_ERROR",
                        screen=self,
                        context={"error": str(e)},
                    )
                self.app.notify(f"Action failed: {e}", severity="error")

    async def on_server_name_blurred(self, event: Input.Blurred) -> None:
        """Commit server name on blur."""
        await self._commit_server_name(event.input.value)

    async def on_server_name_submitted(self, event: Input.Submitted) -> None:
        """Commit server name when the user submits the input."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "SERVER_NAME_SUBMITTED",
                screen=self,
                context={
                    "event_type": type(event).__name__,
                    "event_input_id": getattr(event.input, "id", None),
                    "event_value": event.value,
                },
            )

        await self._commit_server_name(event.value)

        # Focus the command input next
        try:
            command_input = self.query_one("#server_command_input", Input)
            if getattr(command_input, "can_focus", False):
                command_input.focus()
        except Exception:
            pass

    async def on_add_server_button(self, event: Button.Pressed) -> None:
        """Handle add server button press."""
        await self._handle_add_server()

    def on_remove_server_button(self, event: Button.Pressed) -> None:
        """Handle remove server button press."""
        self._run_worker(self._handle_remove_server())

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

            # Default new servers to sandbox enabled when backend is available
            sandbox_default = None
            try:
                from gatekit.sandbox.detection import _detect_backend
                from gatekit.config.models import SandboxConfig

                backend = _detect_backend()
                if backend is not None and backend.is_available():
                    sandbox_default = SandboxConfig(enabled=True)
            except Exception:
                pass

            new_upstream = UpstreamConfig.create_draft(
                name=new_name,
                sandbox=sandbox_default,
            )

            self.config.upstreams.append(new_upstream)
            self.selected_server = new_name

            # Mark dirty after successful mutation
            self._mark_dirty()

            if hasattr(self, "_pending_connection_cache"):
                self._pending_connection_cache[new_name] = ""

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

                if removed_alias and hasattr(self, "_pending_connection_cache"):
                    self._pending_connection_cache.pop(removed_alias, None)

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
