"""Plugin action handlers for Config Editor screen."""

from typing import Dict, Optional, Any
from textual import on
from textual.widgets import Button, DataTable
from gatekit.tui.constants import (
    PLUGIN_COL_ID_NAME,
    PLUGIN_COL_ID_SCOPE,
    PLUGIN_COL_ID_PRIORITY,
    PLUGIN_COL_ID_ACTIONS,
    GLOBAL_SCOPE,
)

from gatekit.config.models import PluginConfig, PluginsConfig
from gatekit.config.framework_fields import get_framework_fields, DEFAULT_FRAMEWORK_VALUES
from ..simple_modals import MessageModal, ConfirmModal, ActionMenuModal
from ..plugin_config import PluginConfigModal
from .plugin_rendering import PluginActionContext
from gatekit.tui.widgets.plugin_table import (
    PluginActionClick,
    PluginToggle,
    HeaderClick,
)


def _get_default_plugin_config(plugin_type: str, plugin_class: type = None) -> Dict[str, Any]:
    """Get default plugin config dict based on plugin type.

    Auditing plugins don't have priority, so they get a different default config.
    If plugin_class is provided, also includes schema defaults for plugin-specific fields.
    """
    framework_fields = get_framework_fields(plugin_type)
    config = {key: DEFAULT_FRAMEWORK_VALUES.get(key, True) for key in framework_fields}

    # Add schema defaults if plugin class is available
    if plugin_class is not None and hasattr(plugin_class, "get_json_schema"):
        try:
            schema = plugin_class.get_json_schema()
            for key, prop in schema.get("properties", {}).items():
                if "default" in prop and key not in config:
                    config[key] = prop["default"]
        except Exception:
            pass  # Gracefully handle schema retrieval errors

    return config


class PluginActionsMixin:
    """Mixin providing plugin action functionality for ConfigEditorScreen."""

    def _dump_plugin_config_state(self, logger, event_name: str, plugin_type: str, handler: str) -> None:
        """Dump the current plugin configuration state for debugging.

        Args:
            logger: Debug logger instance
            event_name: Name of the event triggering the dump
            plugin_type: Type of plugin
            handler: Handler name
        """
        try:
            if not self.config.plugins:
                logger.log_event(
                    f"CONFIG_STATE_DUMP_{event_name}",
                    screen=self,
                    context={
                        "plugin_type": plugin_type,
                        "handler": handler,
                        "config.plugins": None,
                    },
                )
                return

            plugin_type_dict = getattr(self.config.plugins, plugin_type, {})

            # Get global plugins
            global_plugins = plugin_type_dict.get("_global", [])
            global_plugin_states = []
            for p in global_plugins:
                global_plugin_states.append({
                    "handler": p.handler,
                    "enabled": p.enabled,
                    "priority": p.priority,
                    "has_config": bool(p.config),
                })

            # Get server-specific plugins
            server_plugins = plugin_type_dict.get(self.selected_server, [])
            server_plugin_states = []
            for p in server_plugins:
                server_plugin_states.append({
                    "handler": p.handler,
                    "enabled": p.enabled,
                    "priority": p.priority,
                    "has_config": bool(p.config),
                })

            logger.log_event(
                f"CONFIG_STATE_DUMP_{event_name}",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler,
                    "selected_server": self.selected_server,
                    "global_plugins": global_plugin_states,
                    "server_plugins": server_plugin_states,
                    "plugin_type_dict_id": id(plugin_type_dict),
                    "config.plugins_id": id(self.config.plugins),
                },
            )
        except Exception as e:
            logger.log_event(
                f"CONFIG_STATE_DUMP_{event_name}_ERROR",
                screen=self,
                context={"error": str(e)},
            )

    @on(DataTable.CellSelected)
    async def on_plugin_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle cell selection in plugin DataTables."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        # Check if this is a plugin table
        table_id = event.data_table.id
        if logger:
            logger.log_event(
                "PLUGIN_CELL_SELECTED_ENTRY",
                screen=self,
                context={
                    "table_id": table_id,
                    "is_plugin_table": "plugins_table" in table_id if table_id else False,
                    "focused_widget": self.focused,
                    "focused_widget_id": getattr(self.focused, "id", None) if self.focused else None,
                },
            )

        if not table_id or "plugins_table" not in table_id:
            return

        # Extract plugin type from ID pattern
        plugin_type = self._get_plugin_type_from_table_id(table_id)
        if not plugin_type:
            return

        # Get cell details - cell_key is a tuple of (row_key, column_key)
        row_key = event.cell_key.row_key
        column_key = event.cell_key.column_key

        # Debug logging
        if logger:
            logger.log_event(
                "PLUGIN_CELL_SELECTED_PROCESSING",
                screen=self,
                context={
                    "table_id": table_id,
                    "plugin_type": plugin_type,
                    "row_key": row_key,
                    "column_key": column_key,
                    "value": event.value,
                },
            )

        # Handle based on column (use stable IDs)
        if column_key == PLUGIN_COL_ID_NAME:
            # Toggle checkbox
            await self._toggle_plugin(plugin_type, row_key)
        elif column_key == PLUGIN_COL_ID_ACTIONS:
            # Get the actual value from the event or rebuild it
            value = event.value if event.value else ""
            if not value:
                # Try to get value from the model if not in event
                row_data = self._plugin_row_model.get((plugin_type, row_key))
                if row_data:
                    action_context = PluginActionContext(
                        handler=row_data["handler"],
                        plugin_type=plugin_type,
                        inheritance=row_data["inheritance"],
                        enabled=row_data["enabled"],
                        server=self.selected_server,
                    )
                    value = self._build_actions_text(action_context)
            # Only show menu if there are actions
            if value and value.strip():
                await self._show_action_menu(plugin_type, row_key, value)

    @on(DataTable.HeaderSelected)
    async def on_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header clicks for sorting."""
        table_id = event.data_table.id
        if not table_id or "plugins_table" not in table_id:
            return

        column = event.column_key
        if column in [PLUGIN_COL_ID_NAME, PLUGIN_COL_ID_SCOPE, PLUGIN_COL_ID_PRIORITY]:
            await self._sort_table_by_column(event.data_table, column)

    def _get_plugin_type_from_table_id(self, table_id: str) -> str:
        """Extract plugin type from table ID.

        Args:
            table_id: Table ID string

        Returns:
            Plugin type (security/middleware/auditing) or None
        """
        # security_plugins_table_server1 → "security"
        if table_id.startswith("security_"):
            return "security"
        elif table_id.startswith("middleware_"):
            return "middleware"
        elif table_id.startswith("auditing_"):
            return "auditing"
        return None

    async def _toggle_plugin(self, plugin_type: str, row_key: str) -> None:
        """Toggle plugin enabled/disabled state.

        Args:
            plugin_type: Type of plugin
            row_key: Row key from table
        """
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_event(
                "TOGGLE_PLUGIN_CALLED",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "row_key": row_key,
                    "row_model_keys": list(self._plugin_row_model.keys()),
                },
            )

        row_data = self._plugin_row_model.get((plugin_type, row_key))

        if logger:
            logger.log_event(
                "TOGGLE_PLUGIN_ROW_LOOKUP",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "row_key": row_key,
                    "row_data_found": row_data is not None,
                    "row_data": row_data if row_data else None,
                },
            )

        if not row_data:
            if logger:
                logger.log_event(
                    "TOGGLE_PLUGIN_NO_ROW_DATA",
                    screen=self,
                    context={
                        "plugin_type": plugin_type,
                        "row_key": row_key,
                        "returning_early": True,
                    },
                )
            return

        handler_name = row_data["handler"]

        # Get the current state from CONFIG, not from the UI row_data
        # row_data["enabled"] reflects the UI state AFTER the checkbox was clicked
        config_enabled = self._get_config_enabled_state(handler_name, plugin_type)

        if logger:
            logger.log_event(
                "TOGGLE_PLUGIN_CALLING_HANDLER",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler_name": handler_name,
                    "row_data_enabled": row_data["enabled"],
                    "config_enabled": config_enabled,
                    "will_call": "disable" if config_enabled else "enable",
                },
            )

        # Use existing handlers that manage stash/restore
        # Decide based on CONFIG state, not UI state
        if config_enabled:
            await self._handle_plugin_disable(handler_name, plugin_type)
        else:
            await self._handle_plugin_enable(handler_name, plugin_type)

    def _get_config_enabled_state(self, handler_name: str, plugin_type: str) -> bool:
        """Get the current enabled state from config (not UI).

        Args:
            handler_name: Plugin handler name
            plugin_type: Plugin type

        Returns:
            True if currently enabled in config, False otherwise
        """
        if not self.config.plugins:
            return False

        plugin_type_dict = getattr(self.config.plugins, plugin_type, {})

        # Check server-specific first
        if self.selected_server:
            for plugin in plugin_type_dict.get(self.selected_server, []):
                if plugin.handler == handler_name:
                    return plugin.enabled

        # Check global
        for plugin in plugin_type_dict.get("_global", []):
            if plugin.handler == handler_name:
                return plugin.enabled

        return False

    @on(PluginActionClick)
    async def on_plugin_action_click(self, event: PluginActionClick) -> None:
        """Handle action button clicks for both global and server scopes.

        Args:
            event: Event containing handler, plugin_type, action, and scope
        """
        # Cancel any pending focus timers when user interacts with plugins
        self._cancel_pending_focus_timer()

        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "PLUGIN_ACTION_CLICK_RECEIVED",
                screen=self,
                context={
                    "handler": event.handler,
                    "plugin_type": event.plugin_type,
                    "action": event.action,
                    "scope": event.scope,
                },
            )

        if event.action == "Configure":
            # Determine inheritance based on scope
            if event.scope == GLOBAL_SCOPE:
                inheritance = None  # Global plugins don't have inheritance
            else:
                # Get inheritance for server plugin
                plugin = None
                if self.plugin_manager:
                    upstream_plugins = self.plugin_manager.get_plugins_for_upstream(event.scope)
                    for p in upstream_plugins.get(event.plugin_type, []):
                        if getattr(p, "handler", p.__class__.__name__) == event.handler:
                            plugin = p
                            break

                inheritance, _, _ = self.get_plugin_inheritance(
                    event.handler, event.plugin_type, event.scope, plugin
                )

            # Open config modal
            self._run_worker(
                self._handle_plugin_config_modal(
                    handler_name=event.handler,
                    plugin_type=event.plugin_type,
                    scope=event.scope,
                    inheritance=inheritance,
                )
            )

        elif event.action == "Use Global":
            # Only valid for server scope
            if event.scope != GLOBAL_SCOPE:
                await self._handle_use_global_action(event.handler, event.plugin_type)

        event.stop()

    @on(PluginToggle)
    async def on_plugin_toggle(self, event: PluginToggle) -> None:
        """Handle plugin checkbox toggles for both global and server scopes.

        Args:
            event: Event containing handler, plugin_type, enabled state, and scope
        """
        # Cancel any pending focus timers when user interacts with plugins
        self._cancel_pending_focus_timer()

        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_event(
                "PLUGIN_TOGGLE_EVENT_RECEIVED",
                screen=self,
                context={
                    "handler": event.handler,
                    "plugin_type": event.plugin_type,
                    "scope": event.scope,
                    "new_enabled_state": event.enabled,
                },
            )

        if not self.config.plugins:
            self.config.plugins = PluginsConfig()

        plugin_type_dict = getattr(self.config.plugins, event.plugin_type, {})
        if not plugin_type_dict:
            plugin_type_dict = {}

        # Branch based on scope
        if event.scope == GLOBAL_SCOPE:
            # Update global plugins
            global_plugins = plugin_type_dict.get(GLOBAL_SCOPE, [])

            found = False
            for plugin in global_plugins:
                if plugin.handler == event.handler:
                    plugin.enabled = event.enabled
                    found = True
                    break

            if not found:
                # Create new global plugin config with type-appropriate defaults (including schema defaults)
                handler_class = self.available_handlers.get(event.plugin_type, {}).get(event.handler)
                default_config = _get_default_plugin_config(event.plugin_type, handler_class)
                default_config["enabled"] = event.enabled
                new_plugin = PluginConfig(
                    handler=event.handler,
                    config=default_config
                )
                global_plugins.append(new_plugin)

            plugin_type_dict[GLOBAL_SCOPE] = global_plugins

            # Clean up server-specific disabled entries if enabling globally
            if event.enabled:
                for server_name, server_plugins in list(plugin_type_dict.items()):
                    if server_name == GLOBAL_SCOPE:
                        continue
                    filtered = [p for p in server_plugins if not (p.handler == event.handler and not p.enabled)]
                    plugin_type_dict[server_name] = filtered

            # Update config
            setattr(self.config.plugins, event.plugin_type, plugin_type_dict)
            self._mark_dirty()

            # Refresh global plugins display
            await self._populate_global_plugins()
            await self._rebuild_runtime_state()
            await self._populate_server_details()

        else:
            # Update server-specific plugins (existing logic)
            server_plugins = plugin_type_dict.get(event.scope, [])

            found = False
            for plugin in server_plugins:
                if plugin.handler == event.handler:
                    plugin.enabled = event.enabled
                    found = True
                    break

            if not found:
                # Create new server plugin config with type-appropriate defaults (including schema defaults)
                handler_class = self.available_handlers.get(event.plugin_type, {}).get(event.handler)
                default_config = _get_default_plugin_config(event.plugin_type, handler_class)
                default_config["enabled"] = event.enabled
                new_plugin = PluginConfig(
                    handler=event.handler,
                    config=default_config
                )
                server_plugins.append(new_plugin)

            plugin_type_dict[event.scope] = server_plugins
            setattr(self.config.plugins, event.plugin_type, plugin_type_dict)
            self._mark_dirty()

            # Refresh server plugins display
            await self._render_server_plugin_groups()

        # Focus restoration (scope-aware)
        def _restore_focus():
            try:
                if event.scope == GLOBAL_SCOPE:
                    # Derive widget ID from plugin_type: security -> global_security_widget
                    widget_id = f"global_{event.plugin_type}_widget"
                    container = self.query_one(f"#{widget_id}")
                else:
                    # Find server widget
                    container = self.query_one("#server_plugins_display")
                checkbox = container.query_one(f"#checkbox_{event.handler}")
                checkbox.focus()
            except Exception:
                pass

        self.set_timer(0.01, _restore_focus)
        event.stop()

    @on(HeaderClick)
    async def on_header_click(self, event: HeaderClick) -> None:
        """Handle header clicks for sorting from plugin table widgets.

        Args:
            event: Event containing column name
        """
        # The PluginTableWidget handles sorting internally,
        # so we just need to stop the event from bubbling
        event.stop()

    async def _show_action_menu(
        self, plugin_type: str, row_key: str, actions_text: str
    ) -> None:
        """Show action menu for plugin actions.

        Args:
            plugin_type: Type of plugin
            row_key: Row key from table
            actions_text: Styled actions text with markup
        """
        # Parse the button text - looking for Configure and Use Global
        actions = []
        if "Configure" in actions_text:
            actions.append("Configure")
        if "Use Global" in actions_text:
            actions.append("Use Global")

        if not actions:
            return

        row_data = self._plugin_row_model.get((plugin_type, row_key))
        if not row_data:
            return

        handler_name = row_data["handler"]
        display_name = row_data["display_name"]
        inheritance = row_data["inheritance"]

        if len(actions) > 1:
            # Show action menu modal for user to choose using callback (no worker required)
            def _on_action_menu_choice(choice: Optional[str]) -> None:
                if choice == "Configure":
                    self._run_worker(
                        self._handle_plugin_configure(
                            handler_name, plugin_type, inheritance
                        )
                    )
                elif choice == "Use Global":
                    self._run_worker(
                        self._handle_use_global_action(handler_name, plugin_type)
                    )

            self.app.push_screen(
                ActionMenuModal(actions, display_name), _on_action_menu_choice
            )
        elif actions:
            # Single action - execute directly
            if actions[0] == "Configure":
                self._run_worker(
                    self._handle_plugin_configure(
                        handler_name, plugin_type, inheritance
                    )
                )
            else:
                await self._handle_use_global_action(handler_name, plugin_type)

    async def _handle_use_global_action(self, handler_name: str, plugin_type: str) -> None:
        """Remove server override to use global configuration.

        Args:
            handler_name: Plugin handler name
            plugin_type: Type of plugin
        """
        # Get display name for the confirmation message
        display_name = self._format_handler_name(handler_name)

        # Show confirmation dialog
        def _on_confirm(confirmed: Optional[bool]) -> None:
            if confirmed:
                # Use existing reset handler to remove override
                self._run_worker(self._handle_plugin_reset(handler_name, plugin_type))

        self.app.push_screen(
            ConfirmModal(
                title="Use Global Configuration?",
                message=(
                    f"This will remove the server-specific configuration for "
                    f"'{display_name}' and use the global settings instead.\n\n"
                    f"Your custom server configuration will be lost."
                ),
            ),
            _on_confirm,
        )

    async def _sort_table_by_column(self, table: DataTable, column: str) -> None:
        """Sort table by specified column with toggle.

        Args:
            table: DataTable to sort
            column: Column name to sort by
        """
        plugin_type = self._get_plugin_type_from_table_id(table.id)
        if not plugin_type:
            return

        table_id = table.id

        # Get current sort state
        current_col, is_desc = self._table_sort_state.get(table_id, (None, False))

        # Toggle direction if clicking same column, else start ascending
        if current_col == column:
            is_desc = not is_desc
        else:
            # All columns start ascending on first click
            is_desc = False

        # Update sort state
        self._table_sort_state[table_id] = (column, is_desc)

        # Build sorted list from model
        rows_data = []
        for (p_type, row_key), data in self._plugin_row_model.items():
            if p_type == plugin_type:
                rows_data.append((row_key, data))

        # Sort based on column
        if column == PLUGIN_COL_ID_PRIORITY:
            # Numeric sort - lower numbers = higher priority = run first
            rows_data.sort(key=lambda x: int(x[1].get("priority", 50)), reverse=is_desc)
        elif column == PLUGIN_COL_ID_NAME:
            rows_data.sort(key=lambda x: x[1].get("display_name", ""), reverse=is_desc)
        elif column == PLUGIN_COL_ID_SCOPE:
            rows_data.sort(key=lambda x: x[1].get("inheritance", ""), reverse=is_desc)

        # Clear and repopulate table
        table.clear()
        for row_key, data in rows_data:
            checkbox = "☑" if data["enabled"] else "☐"
            plugin_name = f"{checkbox} {data['display_name']}"
            if data.get("is_missing"):
                plugin_name = f"{checkbox} ⚠ {data['display_name']} (not found)"

            status_text = self._get_status_text(
                data["inheritance"], self.selected_server
            )

            # Rebuild action context to get actions text with styling
            action_context = PluginActionContext(
                handler=data["handler"],
                plugin_type=plugin_type,
                inheritance=data["inheritance"],
                enabled=data["enabled"],
                server=self.selected_server,
            )
            actions_text = self._build_actions_text(action_context)

            if plugin_type == "auditing":
                table.add_row(plugin_name, status_text, actions_text, key=row_key)
            else:
                table.add_row(
                    plugin_name,
                    status_text,
                    str(data["priority"]),
                    actions_text,
                    key=row_key,
                )

    @on(Button.Pressed)
    async def on_plugin_action_button(self, event: Button.Pressed) -> None:
        """Handle plugin action button presses."""
        button_id = event.button.id
        if not button_id:
            return

        # Check if this is a plugin action button
        if not any(
            button_id.startswith(prefix)
            for prefix in ["config_", "disable_", "enable_", "reset_", "remove_"]
        ):
            return

        # Prevent duplicate handling during async operations
        if event.button.disabled:
            return  # Fast re-entry guard
        event.button.disabled = True

        # Track whether we should re-enable the button in the finally block
        try:
            # Extract action from ID (config_xxx, disable_xxx, etc.)
            action = button_id.split("_", 1)[0]

            # Get context from button
            ctx = getattr(event.button, "data_ctx", None)
            if not ctx or not isinstance(ctx, PluginActionContext):
                return

            # Structured logging for action execution
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "plugin_action_execute",
                    widget=event.button,
                    screen=self,
                    context={
                        "action": action,
                        "handler": ctx.handler,
                        "plugin_type": ctx.plugin_type,
                        "inheritance": ctx.inheritance,
                        "enabled": ctx.enabled,
                        "server": ctx.server,
                        "button_id": button_id,
                    },
                )

            if action == "config":
                worker = self._run_worker(
                    self._handle_plugin_configure(
                        ctx.handler, ctx.plugin_type, ctx.inheritance
                    )
                )
                if worker is None and logger:
                    logger.log_event(
                        "plugin_action_worker_failed",
                        widget=event.button,
                        screen=self,
                        context={
                            "action": action,
                            "handler": ctx.handler,
                            "plugin_type": ctx.plugin_type,
                            "button_id": button_id,
                        },
                    )
            elif action == "disable":
                await self._handle_plugin_disable(ctx.handler, ctx.plugin_type)
            elif action == "enable":
                await self._handle_plugin_enable(ctx.handler, ctx.plugin_type)
            elif action == "reset":
                await self._handle_plugin_reset(ctx.handler, ctx.plugin_type)
            elif action == "remove":
                await self._handle_plugin_remove(ctx.handler, ctx.plugin_type)

            # Log completion for synchronous actions
            if logger and action != "config":
                logger.log_event(
                    "plugin_action_complete",
                    widget=event.button,
                    screen=self,
                    context={
                        "action": action,
                        "handler": ctx.handler,
                        "plugin_type": ctx.plugin_type,
                        "button_id": button_id,
                    },
                )
        finally:
            try:
                event.button.disabled = (
                    False  # Button may have been replaced during refresh
                )
            except Exception:
                pass

    # Removed: add-plugin button handler (buttons no longer rendered)

    async def _handle_plugin_configure(
        self, handler_name: str, plugin_type: str, inheritance: str
    ) -> None:
        """Handle plugin configuration action."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_event(
                "user_action",
                screen=self,
                context={
                    "action": "configure_plugin",
                    "handler": handler_name,
                    "plugin_type": plugin_type,
                    "inheritance": inheritance,
                    "server": self.selected_server,
                },
            )

        # Delegate to unified modal handler
        # Use selected_server as scope if available, otherwise use "_global" as fallback
        scope = self.selected_server if self.selected_server else "_global"
        await self._handle_plugin_config_modal(
            handler_name=handler_name,
            plugin_type=plugin_type,
            scope=scope,
            inheritance=inheritance,
        )

    async def _handle_plugin_disable(self, handler_name: str, plugin_type: str) -> None:
        """Disable a plugin for this server, preserving any custom override config."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_event(
                "user_action",
                screen=self,
                context={
                    "action": "disable_plugin",
                    "handler": handler_name,
                    "plugin_type": plugin_type,
                    "server": self.selected_server,
                },
            )
            # Dump state before disable
            self._dump_plugin_config_state(logger, "BEFORE_DISABLE", plugin_type, handler_name)

        # Get plugin configuration dict
        # NOTE: config.plugins.security/auditing/middleware are dicts
        if not self.config.plugins:
            self.config.plugins = PluginsConfig()

        plugins_config = self.config.plugins
        plugin_type_dict = getattr(plugins_config, plugin_type, {})

        if logger:
            logger.log_event(
                "DISABLE_GOT_PLUGIN_TYPE_DICT",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler_name,
                    "plugin_type_dict_id": id(plugin_type_dict),
                    "plugin_type_dict_keys": list(plugin_type_dict.keys()),
                },
            )
        server_plugins = plugin_type_dict.get(self.selected_server, [])

        # Check if there's an existing override we should preserve
        existing_override = None
        for plugin in server_plugins:
            if plugin.handler == handler_name:
                existing_override = plugin
                break

        if existing_override and existing_override.enabled:
            # Store the current override config before disabling
            stash_key = (self.selected_server, plugin_type, handler_name)
            self._override_stash[stash_key] = {
                "config": (
                    existing_override.config.copy() if existing_override.config else {}
                ),
                "priority": existing_override.priority,
            }

            # Update existing override to disabled
            existing_override.enabled = False

            if logger:
                logger.log_state_change(
                    "override_disabled",
                    {
                        "handler": handler_name,
                        "had_config": bool(existing_override.config),
                    },
                    {"stashed": True},
                    screen=self,
                )
        else:
            # No existing override, create a disable override
            # Remove any existing entry to avoid duplicates
            server_plugins = [p for p in server_plugins if p.handler != handler_name]

            # Get default config for this plugin type (including schema defaults)
            handler_class = self.available_handlers.get(plugin_type, {}).get(handler_name)
            default_config = _get_default_plugin_config(plugin_type, handler_class)
            default_config["enabled"] = False

            # For non-auditing plugins, try to inherit priority from global config
            if "priority" in default_config:
                global_plugins = plugin_type_dict.get("_global", [])
                for plugin in global_plugins:
                    if plugin.handler == handler_name:
                        if plugin.priority is not None:
                            default_config["priority"] = plugin.priority
                        break

            # Create disable override
            disable_override = PluginConfig(
                handler=handler_name, config=default_config
            )
            server_plugins.append(disable_override)

        # CRITICAL: Must assign back to dict or changes are lost!
        plugin_type_dict[self.selected_server] = server_plugins

        if logger:
            logger.log_event(
                "DISABLE_UPDATED_SERVER_PLUGINS",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler_name,
                    "server": self.selected_server,
                    "server_plugins_count": len(server_plugins),
                    "plugin_type_dict_id": id(plugin_type_dict),
                },
            )

        # CRITICAL: Set the modified dict back to the Pydantic model
        # Without this, Pydantic doesn't see the changes!
        setattr(self.config.plugins, plugin_type, plugin_type_dict)

        if logger:
            logger.log_event(
                "DISABLE_SETATTR_COMPLETE",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler_name,
                },
            )
            # Dump state after disable
            self._dump_plugin_config_state(logger, "AFTER_DISABLE", plugin_type, handler_name)

        # Mark dirty after successful mutation
        self._mark_dirty()

        # Refresh UI
        await self._populate_server_plugins()
        self.app.notify(
            f"Disabled {handler_name} for {self.selected_server}",
            severity="warning",
        )

    async def _handle_plugin_enable(self, handler_name: str, plugin_type: str) -> None:
        """Re-enable a disabled plugin, restoring any stashed override config."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_event(
                "user_action",
                screen=self,
                context={
                    "action": "enable_plugin",
                    "handler": handler_name,
                    "plugin_type": plugin_type,
                    "server": self.selected_server,
                },
            )
            # Dump state before enable
            self._dump_plugin_config_state(logger, "BEFORE_ENABLE", plugin_type, handler_name)

        if not self.config.plugins:
            return

        # Get plugin configuration dict
        plugins_config = self.config.plugins
        plugin_type_dict = getattr(plugins_config, plugin_type, {})

        if logger:
            logger.log_event(
                "ENABLE_GOT_PLUGIN_TYPE_DICT",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler_name,
                    "plugin_type_dict_id": id(plugin_type_dict),
                    "plugin_type_dict_keys": list(plugin_type_dict.keys()),
                },
            )
        server_plugins = plugin_type_dict.get(self.selected_server, [])

        # Check if we have a stashed config to restore
        stash_key = (self.selected_server, plugin_type, handler_name)
        stashed_config = self._override_stash.pop(stash_key, None)

        # Find the disabled override
        for plugin in server_plugins:
            if plugin.handler == handler_name and not plugin.enabled:
                if stashed_config:
                    # Restore the stashed config
                    plugin.enabled = True
                    plugin.config = stashed_config["config"]
                    plugin.priority = stashed_config["priority"]

                    if logger:
                        logger.log_state_change(
                            "override_restored",
                            {"handler": handler_name},
                            {"config_restored": bool(stashed_config["config"])},
                            screen=self,
                        )
                else:
                    # No stashed config, just remove the disable override
                    server_plugins = [
                        p
                        for p in server_plugins
                        if not (p.handler == handler_name and not p.enabled)
                    ]
                    plugin_type_dict[self.selected_server] = server_plugins
                break

        # Update the config
        plugin_type_dict[self.selected_server] = server_plugins

        if logger:
            logger.log_event(
                "ENABLE_UPDATED_SERVER_PLUGINS",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler_name,
                    "server": self.selected_server,
                    "server_plugins_count": len(server_plugins),
                    "plugin_type_dict_id": id(plugin_type_dict),
                },
            )

        # CRITICAL: Set the modified dict back to the Pydantic model
        # Without this, Pydantic doesn't see the changes!
        setattr(self.config.plugins, plugin_type, plugin_type_dict)

        if logger:
            logger.log_event(
                "ENABLE_SETATTR_COMPLETE",
                screen=self,
                context={
                    "plugin_type": plugin_type,
                    "handler": handler_name,
                },
            )
            # Dump state after enable
            self._dump_plugin_config_state(logger, "AFTER_ENABLE", plugin_type, handler_name)

        # Mark dirty after successful mutation
        self._mark_dirty()

        # Refresh UI
        await self._populate_server_plugins()
        self.app.notify(
            f"Enabled {handler_name} for {self.selected_server}", severity="success"
        )

    async def _handle_plugin_reset(self, handler_name: str, plugin_type: str) -> None:
        """Remove server-specific override so global inheritance resumes."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_event(
                "user_action",
                screen=self,
                context={
                    "action": "reset_plugin",
                    "handler": handler_name,
                    "plugin_type": plugin_type,
                    "server": self.selected_server,
                },
            )

        if not self.config.plugins or not self.selected_server:
            return

        plugins_dict = getattr(self.config.plugins, plugin_type, {})
        server_plugins = plugins_dict.get(self.selected_server, [])

        # Remove the override
        server_plugins = [p for p in server_plugins if p.handler != handler_name]
        plugins_dict[self.selected_server] = server_plugins

        # Mark dirty after successful mutation
        self._mark_dirty()

        # Refresh UI
        await self._populate_server_plugins()

        # Notify user
        display_name = self._format_handler_name(handler_name)
        self.app.notify(
            f"Using global configuration for {display_name}",
            severity="success",
        )

    async def _handle_plugin_remove(self, handler_name: str, plugin_type: str) -> None:
        """Remove a server-only plugin entirely."""
        # Check if this is truly server-only or if it exists globally
        status, _, _ = self._compute_plugin_inheritance(
            handler_name, plugin_type, self.selected_server
        )

        if status in ["inherited", "overrides", "disabled"]:
            # This is a global plugin - shouldn't be removable, use reset instead
            self.app.notify(
                f"Cannot remove {handler_name} - it's a global plugin. Use Reset to restore inheritance.",
                severity="warning",
            )
            return

        # Remove server-only plugin
        if not self.config.plugins or not self.selected_server:
            return

        plugins_dict = getattr(self.config.plugins, plugin_type, {})
        server_plugins = plugins_dict.get(self.selected_server, [])

        # Remove the plugin
        server_plugins = [p for p in server_plugins if p.handler != handler_name]
        plugins_dict[self.selected_server] = server_plugins

        # Mark dirty after successful mutation
        self._mark_dirty()

        # Refresh UI
        await self._populate_server_plugins()
        self.app.notify(
            f"Removed {handler_name} from {self.selected_server}",
            severity="success",
        )

    async def _create_server_override(
        self,
        handler_name: str,
        plugin_type: str,
        base_config: Dict[str, Any],
    ) -> None:
        """Creates or replaces a server-level override using the base config."""
        if not self.config.plugins:
            self.config.plugins = PluginsConfig()

        plugins_dict = getattr(self.config.plugins, plugin_type, {})
        server_plugins = plugins_dict.get(self.selected_server, [])

        # Check if override already exists and replace it
        existing_index = None
        for i, plugin in enumerate(server_plugins):
            if plugin.handler == handler_name:
                existing_index = i
                break

        # Clone the base config (which already has enabled, priority, and plugin-specific fields)
        override = PluginConfig(
            handler=handler_name,
            config=base_config.copy(),
        )

        if existing_index is not None:
            server_plugins[existing_index] = override
        else:
            server_plugins.append(override)

        plugins_dict[self.selected_server] = server_plugins
        setattr(self.config.plugins, plugin_type, plugins_dict)

        self._mark_dirty()
        await self._populate_server_plugins()

    def _find_plugin(
        self,
        handler_name: str,
        plugin_type: str,
        scope: str,
    ) -> Optional[Any]:
        """Find a PluginConfig instance by handler name in the given scope.

        Args:
            handler_name: Plugin handler name
            plugin_type: Type of plugin (security/middleware/auditing)
            scope: Scope to search in (e.g., "_global" or server name)

        Returns:
            PluginConfig instance if found, None otherwise
        """
        if not self.config.plugins:
            return None

        plugins_dict = getattr(self.config.plugins, plugin_type, {})
        for plugin_config in plugins_dict.get(scope, []):
            if plugin_config.handler == handler_name:
                return plugin_config
        return None

    def _get_global_plugin_config(
        self, handler_name: str, plugin_type: str
    ) -> Dict[str, Any]:
        """Get global plugin configuration (all fields in config dict).

        Returns config dict with type-appropriate defaults when plugin not found.
        This ensures the modal shows the correct initial state.
        """
        plugin = self._find_plugin(handler_name, plugin_type, "_global")
        if not plugin:
            # Return config with type-appropriate defaults (including schema defaults)
            handler_class = self.available_handlers.get(plugin_type, {}).get(handler_name)
            return _get_default_plugin_config(plugin_type, handler_class)
        return plugin.config.copy()

    def _get_server_plugin_config(
        self, handler_name: str, plugin_type: str
    ) -> Dict[str, Any]:
        """Get server plugin configuration (all fields in config dict).

        Returns config dict with type-appropriate defaults when plugin not found.
        This ensures the modal shows the correct initial state.
        """
        handler_class = self.available_handlers.get(plugin_type, {}).get(handler_name)
        if not self.selected_server:
            return _get_default_plugin_config(plugin_type, handler_class)
        plugin = self._find_plugin(
            handler_name, plugin_type, self.selected_server
        )
        if not plugin:
            # Return config with type-appropriate defaults (including schema defaults)
            return _get_default_plugin_config(plugin_type, handler_class)
        return plugin.config.copy()


    async def _save_plugin_config_for_scope(
        self,
        handler_name: str,
        plugin_type: str,
        new_config: Dict[str, Any],
        scope: str,  # "_global" or server name
    ) -> None:
        """Save plugin configuration to specified scope (global or server-specific).

        Args:
            handler_name: Plugin handler key
            plugin_type: "security", "middleware", or "auditing"
            new_config: New configuration dict (already validated by modal)
            scope: "_global" for global config, or server name for server-specific
        """
        if not self.config.plugins:
            from gatekit.config.models import PluginsConfig
            self.config.plugins = PluginsConfig()

        plugins_dict = getattr(self.config.plugins, plugin_type, {})
        scope_plugins = plugins_dict.get(scope, [])

        # Find and update existing plugin
        found = False
        for plugin in scope_plugins:
            if plugin.handler == handler_name:
                plugin.config = new_config.copy()
                found = True
                break

        if not found:
            if scope == "_global":
                # Create new global plugin with type-appropriate defaults (including schema defaults)
                from gatekit.config.models import PluginConfig
                handler_class = self.available_handlers.get(plugin_type, {}).get(handler_name)
                default_config = _get_default_plugin_config(plugin_type, handler_class)
                default_config["enabled"] = True  # New plugins start enabled
                default_config.update(new_config)  # User config overrides defaults
                new_plugin = PluginConfig(
                    handler=handler_name,
                    config=default_config
                )
                scope_plugins.append(new_plugin)
            else:
                # Server-specific: check if should create override
                global_plugins = plugins_dict.get("_global", [])
                for plugin in global_plugins:
                    if plugin.handler == handler_name:
                        # Create server override with the new config
                        await self._create_server_override(
                            handler_name,
                            plugin_type,
                            new_config,
                        )
                        return

                # Not found globally either - create new server-specific plugin
                from gatekit.config.models import PluginConfig
                new_plugin = PluginConfig(
                    handler=handler_name,
                    config=new_config.copy()
                )
                scope_plugins.append(new_plugin)

        plugins_dict[scope] = scope_plugins
        setattr(self.config.plugins, plugin_type, plugins_dict)

        self._mark_dirty()

        # Refresh appropriate UI
        if scope == "_global":
            await self._populate_global_plugins()
        else:
            await self._populate_server_plugins()

    async def _handle_plugin_config_modal(
        self,
        handler_name: str,
        plugin_type: str,
        scope: str,  # "_global" or server name
        inheritance: Optional[str] = None,  # None for global, "inherited"/"overrides"/etc for server
    ) -> None:
        """Open plugin config modal and handle save for any scope (global or server-specific).

        Args:
            handler_name: Plugin handler key
            plugin_type: "security", "middleware", or "auditing"
            scope: "_global" for global config, or server name for server-specific
            inheritance: Inheritance state - None for global, "inherited" shows read-only with override
        """

        # Find the plugin class for this handler
        handler_class = self.available_handlers.get(plugin_type, {}).get(handler_name)
        if not handler_class:
            self.app.notify(f"Plugin {handler_name} not found", severity="error")
            return

        # Check for server-aware plugins (must be configured per-server)
        is_server_aware = getattr(handler_class, "DISPLAY_SCOPE", "") == "server_aware"
        display_name = getattr(handler_class, "DISPLAY_NAME", handler_name)

        if is_server_aware:
            if scope == "_global":
                # Global scope: server-aware plugins must be configured per server
                self.app.notify(
                    f"{display_name} is configured per server. Select a server and use Configure from that table.",
                    severity="information",
                    title="Server-Aware Plugin",
                )
                return
            elif inheritance == "inherited":
                # Server scope but inherited: Need to select server
                await self.app.push_screen(
                    MessageModal(
                        "Select a Server",
                        f"{display_name} is server-aware. Configure it from an individual server row.",
                    )
                )
                return
            elif not self.selected_server:
                # Server scope but no server selected
                await self.app.push_screen(
                    MessageModal(
                        "Select a Server",
                        f"Choose an MCP server before configuring {display_name}.",
                    )
                )
                return

        # Check if plugin has JSON schema
        if not hasattr(handler_class, "get_json_schema"):
            self.app.notify(
                f"Plugin {handler_name} does not support configuration",
                severity="warning"
            )
            return

        schema = handler_class.get_json_schema()
        if not schema:
            self.app.notify(
                "This plugin does not define a configuration schema.\nConfiguration must be done manually in the config file.",
                title="No Schema Available",
                severity="information",
            )
            return

        # Get current configuration based on inheritance
        if inheritance == "inherited":
            # Show global config with override option
            current_config = self._get_global_plugin_config(handler_name, plugin_type)

            # Get discovery context for server-scoped plugins
            discovery = self.server_tool_map.get(self.selected_server) if self.selected_server else None

            # Open modal with read-only global config
            modal = PluginConfigModal(
                handler_class,
                handler_name,
                current_config,
                read_only=True,
                show_override_button=True,
                discovery_context=discovery,
                config_file_path=self.config_file_path,
            )

            result = await self.app.push_screen_wait(modal)
            if result is not None:
                # Create server-specific override with user's modified config
                await self._create_server_override(
                    handler_name,
                    plugin_type,
                    result,  # Use the user's modified config, not original global
                )
                # Use DISPLAY_NAME for user-facing message
                display_name = getattr(handler_class, 'DISPLAY_NAME', handler_name)
                self.app.notify(
                    f"Created override for {display_name}", severity="success"
                )
        else:
            # Edit config for specified scope
            if scope == "_global":
                current_config = self._get_global_plugin_config(handler_name, plugin_type)
            else:
                current_config = self._get_server_plugin_config(handler_name, plugin_type)

            # Get discovery context for server-scoped plugins
            discovery = self.server_tool_map.get(self.selected_server) if self.selected_server else None

            modal = PluginConfigModal(
                handler_class,
                handler_name,
                current_config,
                read_only=False,
                discovery_context=discovery,
                config_file_path=self.config_file_path,
            )

            result = await self.app.push_screen_wait(modal)
            if result is not None:
                await self._save_plugin_config_for_scope(
                    handler_name, plugin_type, result, scope
                )
