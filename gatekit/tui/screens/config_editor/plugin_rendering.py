"""Plugin rendering and display functionality for Config Editor screen."""

from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass

from textual.binding import Binding
from textual.widgets import Button, DataTable

from gatekit.tui.constants import (
    PLUGIN_COL_ID_NAME,
    PLUGIN_COL_ID_SCOPE,
    PLUGIN_COL_ID_PRIORITY,
    PLUGIN_COL_ID_ACTIONS,
    GLOBAL_SCOPE,
)
from gatekit.tui.widgets.plugin_table import (
    PluginTableWidget,
)

# Maximum number of plugin rows visible before scrolling (applies to server plugin tables and used for global cap)
MAX_PLUGIN_ROWS_VISIBLE = 5


@dataclass
class PluginActionContext:
    """Context for plugin action buttons."""

    handler: str
    plugin_type: str  # 'security' | 'middleware' | 'auditing'
    inheritance: str  # 'inherited' | 'overrides' | 'server-only' | 'disabled'
    enabled: bool
    server: str


class PluginDataTable(DataTable):
    """Custom DataTable for plugin display with Space key toggle support."""

    BINDINGS = [
        Binding("space", "toggle_current", "Toggle", show=False),
    ]

    def __init__(
        self, plugin_type: str, server_name: str, show_priority: bool = True, **kwargs
    ):
        """Initialize the plugin data table.

        Args:
            plugin_type: Type of plugins (security/middleware/auditing)
            server_name: Name of the server
            show_priority: Whether to show priority column
        """
        super().__init__(
            cursor_type="cell", show_header=True, zebra_stripes=False, **kwargs
        )
        self.plugin_type = plugin_type
        self.server_name = server_name
        self.show_priority = show_priority
        self._setup_columns()

    def _setup_columns(self):
        """Set up table columns based on plugin type."""
        # Use stable column IDs with user-facing labels
        if self.plugin_type == "auditing":
            self.add_columns(
                (PLUGIN_COL_ID_NAME, "Plugin Name"),
                (PLUGIN_COL_ID_SCOPE, "Scope"),
                (PLUGIN_COL_ID_ACTIONS, "Actions"),
            )
        else:
            self.add_columns(
                (PLUGIN_COL_ID_NAME, "Plugin Name"),
                (PLUGIN_COL_ID_SCOPE, "Scope"),
                (PLUGIN_COL_ID_PRIORITY, "Priority"),
                (PLUGIN_COL_ID_ACTIONS, "Actions"),
            )

    def action_toggle_current(self) -> None:
        """Toggle checkbox when space is pressed."""
        if self.cursor_column == 0:  # Plugin Name column
            # Get the row key from current cursor position
            row_key, column_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            # Post a CellSelected event to trigger toggle
            from textual.widgets.data_table import CellSelected

            self.post_message(
                CellSelected(self, row_key, column_key, self.cursor_coordinate)
            )


class PluginRenderingMixin:
    """Mixin providing plugin rendering functionality for ConfigEditorScreen."""

    def _build_plugin_display_data(
        self,
        plugin_type: str,
        scope: str,
    ) -> List[Dict[str, Any]]:
        """Build plugin display data for a given type and scope.

        Preserves plugin metadata including:
        - Plugin-specific status via describe_status()
        - Missing handler warnings
        - DISPLAY_SCOPE filtering for global plugins

        Args:
            plugin_type: "security", "middleware", or "auditing"
            scope: GLOBAL_SCOPE or server name

        Returns:
            List of plugin display data dicts
        """
        plugins_data = []

        # Get available handlers for this plugin type
        available_handlers = self.available_handlers.get(plugin_type, {})

        # Filter handlers based on DISPLAY_SCOPE when showing global plugins
        if scope == GLOBAL_SCOPE and plugin_type in ["security", "middleware"]:
            # For global security/middleware plugins, only show plugins with DISPLAY_SCOPE == "global"
            filtered_handlers = {}
            for handler_name, handler_class in available_handlers.items():
                display_scope = getattr(handler_class, "DISPLAY_SCOPE", "global")
                if display_scope == "global":
                    filtered_handlers[handler_name] = handler_class
            available_handlers = filtered_handlers
        # For auditing plugins and server scope, show all handlers (no filtering)

        # Get configuration for this scope
        plugins_config = {}
        if self.config.plugins:
            plugin_type_dict = getattr(self.config.plugins, plugin_type, {})
            plugins_config = plugin_type_dict.get(scope, [])

        # Build display data for each available plugin
        for handler_name, handler_class in available_handlers.items():
            # Find config for this handler in the scope
            plugin_config = None
            for p in plugins_config:
                if p.handler == handler_name:
                    plugin_config = p
                    break

            # Build complete config dict (matching global_plugins.py pattern)
            complete_config = {
                "handler": handler_name,
                "enabled": plugin_config.enabled if plugin_config else False,
                "priority": plugin_config.priority if plugin_config else 50,
                "config": plugin_config.config if plugin_config else {},
            }

            # Extract inner config for plugin methods (they expect config dict, not PluginConfig)
            inner_config = complete_config.get("config", {})
            config_for_plugin_methods = {
                **inner_config,
                "enabled": complete_config.get("enabled", False),
                "priority": complete_config.get("priority", 50),
            }

            try:
                # Get display information from plugin class methods
                display_name = getattr(handler_class, "DISPLAY_NAME", handler_name.title())

                # Call plugin's describe_status() for rich status messages
                status = handler_class.describe_status(config_for_plugin_methods)

                # Check if status represents a clickable file path
                status_file_path = None
                if hasattr(handler_class, "get_status_file_path"):
                    status_file_path = handler_class.get_status_file_path(config_for_plugin_methods)

                # Resolve status paths using the shared path resolution utility
                # to ensure consistent behavior with the gateway.
                resolved_status_file_path = None
                if status_file_path:
                    from gatekit.utils.paths import resolve_config_path
                    config_path = getattr(self, "config_file_path", None)
                    if config_path:
                        resolved_status_file_path = str(resolve_config_path(status_file_path, config_path.parent))
                    else:
                        # No config path - just expand ~ but can't resolve relative paths
                        from gatekit.utils.paths import expand_user_path
                        resolved_status_file_path = str(expand_user_path(status_file_path))

                display_data = {
                    "handler": handler_name,
                    "display_name": display_name,
                    "status": status,
                    # Path to open on click (absolute when config path is known)
                    "status_file_path": resolved_status_file_path,
                    "action": "Configure",  # Primary action
                    "enabled": complete_config.get("enabled", False),
                    "priority": complete_config.get("priority", 50),
                    "is_missing": False,  # Handler found
                    "plugin_type": plugin_type,  # Track actual plugin type
                }

                plugins_data.append(display_data)

            except Exception as e:
                # Fallback for plugin method failures (preserve existing error handling)
                plugins_data.append({
                    "handler": handler_name,
                    "display_name": handler_name.title(),
                    "status": "Error loading plugin status",
                    "action": "Configure",
                    "enabled": False,
                    "priority": complete_config.get("priority", 50),
                    "is_missing": False,
                    "error": str(e),
                    "plugin_type": plugin_type,  # Track actual plugin type
                })

        # Check for configured plugins that are missing from available handlers
        # (This preserves the "⚠ handler (not found)" warnings)
        for plugin_config in plugins_config:
            if plugin_config.handler not in available_handlers:
                plugins_data.append({
                    "handler": plugin_config.handler,
                    "display_name": plugin_config.handler,
                    "status": "Plugin not found",
                    "action": "Configure",
                    "enabled": plugin_config.enabled,
                    "priority": plugin_config.priority,
                    "is_missing": True,  # Will show ⚠ in UI
                    "plugin_type": plugin_type,  # Track actual plugin type
                })

        # Sort: enabled first, then by priority (lower = higher), then alphabetical
        plugins_data.sort(
            key=lambda p: (
                not p["enabled"],
                p.get("priority", 50),
                p["display_name"],
            )
        )

        return plugins_data

    def _sanitize_handler_for_id(self, handler_name: str, plugin_type: str) -> str:
        """Sanitize handler name for use in button IDs with collision detection.

        Args:
            handler_name: Original handler name
            plugin_type: Plugin type for additional context in collision resolution

        Returns:
            Sanitized handler name that is guaranteed to be unique
        """
        import re
        import hashlib

        # Basic sanitization
        base_sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", handler_name)

        # Start with base sanitized name
        sanitized = base_sanitized

        # Check for collision globally (IDs must be unique across all plugin types)
        if sanitized in self._sanitized_handler_map:
            existing_original, existing_type = self._sanitized_handler_map[sanitized]
            # If it's the same handler in the same type, reuse the ID
            if existing_original == handler_name and existing_type == plugin_type:
                return sanitized
            # Otherwise it's a collision - need unique suffix
            # Use plugin type in hash to ensure different IDs for same name in different types
            hash_input = f"{plugin_type}:{handler_name}"
            hash_suffix = hashlib.sha256(hash_input.encode()).hexdigest()[:4]
            sanitized = f"{base_sanitized}_{hash_suffix}"

        # Store mapping with plugin type
        self._sanitized_handler_map[sanitized] = (handler_name, plugin_type)

        return sanitized

    def _build_plugin_action_button(
        self,
        action_name: str,
        action_variant: str,
        handler_name: str,
        plugin_type: str,
        action_context: PluginActionContext,
    ) -> Button:
        """Build a plugin action button with proper ID and context.

        Args:
            action_name: Display name for the button (e.g., "Configure", "Disable")
            action_variant: Button variant for styling
            handler_name: Plugin handler name
            plugin_type: Type of plugin (security/middleware/auditing)
            action_context: Full context for the action

        Returns:
            Configured Button widget
        """
        # Get sanitized handler name with collision detection
        safe_handler = self._sanitize_handler_for_id(handler_name, plugin_type)

        # Map action names to expected prefixes for event handler
        action_prefix_map = {
            "Configure": "config",
            "Disable": "disable",
            "Enable": "enable",
            "Reset": "reset",
            "Remove": "remove",
        }
        action_prefix = action_prefix_map.get(action_name, action_name.lower())

        # Keep stable IDs for unit tests and handlers
        btn_id = f"{action_prefix}_{safe_handler}"
        btn = Button(action_name, id=btn_id, variant=action_variant)

        # Attach context for handler
        btn.data_ctx = action_context

        # Log action for debugging
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "button_created",
                widget=btn,
                screen=self,
                context={
                    "button_id": btn_id,
                    "action": action_name,
                    "handler": handler_name,
                    "plugin_type": plugin_type,
                    "inheritance": action_context.inheritance,
                    "enabled": action_context.enabled,
                    "server": action_context.server,
                },
            )

        return btn

    async def _populate_global_plugins(self) -> None:
        """Populate the global plugins section using PluginTableWidget."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        security_widget = self.query_one("#global_security_widget", PluginTableWidget)
        auditing_widget = self.query_one("#global_auditing_widget", PluginTableWidget)

        # Build plugin data using shared helper
        security_data = self._build_plugin_display_data("security", GLOBAL_SCOPE)
        middleware_data = self._build_plugin_display_data("middleware", GLOBAL_SCOPE)
        auditing_data = self._build_plugin_display_data("auditing", GLOBAL_SCOPE)

        # Combine security and middleware for display in the same widget
        # Re-sort combined list to ensure enabled plugins appear first regardless of type
        combined_data = security_data + middleware_data
        combined_data.sort(
            key=lambda p: (
                not p["enabled"],
                p.get("priority", 50),
                p["display_name"],
            )
        )

        # Update widgets with in-memory config data
        security_widget.update_plugins(combined_data)
        auditing_widget.update_plugins(auditing_data)

        if logger:
            logger.log_widget_lifecycle(
                "update",
                screen=self,
                component="global_plugins",
                action="populate_plugins_data",
            )

        # Adjust container heights
        self._adjust_global_plugins_section_height(security_widget, auditing_widget)
        self._setup_navigation_containers()

    def _adjust_global_plugins_section_height(
        self, security_widget, auditing_widget
    ) -> None:
        """Adjust the heights of .global-plugins-section based on number of plugins. The
        global-plugins-section container's auto and max-height properties do not work and will
        not size to content automatically ."""

        # Get plugin counts
        security_count = (
            len(security_widget.plugins_data)
            if hasattr(security_widget, "plugins_data")
            else 0
        )
        auditing_count = (
            len(auditing_widget.plugins_data)
            if hasattr(auditing_widget, "plugins_data")
            else 0
        )

        # Calculate heights (1 line per plugin + 2 for borders + 1 for title + 2 for top/bottom margins [5 total])
        # Cap at MAX_PLUGIN_ROWS_VISIBLE to match dynamic clamp in PluginTableWidget
        security_height = (
            min(security_count + 5, MAX_PLUGIN_ROWS_VISIBLE + 5)
            if security_count > 0
            else 3
        )
        auditing_height = (
            min(auditing_count + 5, MAX_PLUGIN_ROWS_VISIBLE + 5)
            if auditing_count > 0
            else 3
        )
        height = max(security_height, auditing_height)

        # Find and set heights for the .global-pane-content containers
        try:
            # Get the global-plugins-section container
            global_plugins_section = self.query(".global-plugins-section").first()
            if global_plugins_section:
                global_plugins_section.styles.height = height

        except Exception as e:
            # If we can't set specific heights, fall back to CSS defaults
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "height_adjustment_error",
                    screen=self,
                    context={"error": str(e), "where": "global_plugins_section"},
                )
            pass

    async def _render_server_plugin_groups(self) -> None:
        """Render plugin groups in the combined details panel using DataTables."""
        # Debug logging
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "render_plugins_start",
                    screen=self,
                    context={
                        "selected_server": self.selected_server,
                        "has_plugin_manager": bool(self.plugin_manager),
                    },
                )

                # Dump config state at render time for all plugin types
                for plugin_type in ["security", "middleware", "auditing"]:
                    if hasattr(self, '_dump_plugin_config_state'):
                        self._dump_plugin_config_state(logger, "AT_RENDER_START", plugin_type, "ALL")
        except Exception:
            logger = None  # Ensure defined below even if debug import fails

        if not self.selected_server or not self.plugin_manager:
            return

        plugins_container = self.query_one("#server_plugins_display")

        # Log container state before clear
        try:
            if logger:
                logger.log_event(
                    "container_state_before",
                    screen=self,
                    context={
                        "container_id": "server_plugins_display",
                        "child_count": len(plugins_container.children),
                        "is_visible": plugins_container.visible,
                        "display": plugins_container.styles.display,
                    },
                )
        except Exception:
            pass

        # Remove existing children and yield to the event loop so unmount completes
        plugins_container.remove_children()
        try:
            import asyncio

            # Yield control to allow Textual to process the unmount and release IDs
            await asyncio.sleep(0)
        except Exception:
            # Best-effort; continue even if sleep isn't available
            pass

        # Reset sanitized handler map and clear plugin row model for this render
        try:
            self._sanitized_handler_map.clear()
            self._plugin_row_model.clear()
        except Exception:
            # If map not present for some reason, ignore
            pass

        # Get enabled plugins from plugin manager
        upstream_plugins = self.plugin_manager.get_plugins_for_upstream(
            self.selected_server
        )

        # Helper to sanitize server name for use in IDs
        import re

        re.sub(r"[^a-zA-Z0-9_-]", "_", self.selected_server)

        for plugin_type in ["security", "middleware", "auditing"]:

            # Get all plugins (enabled and disabled)
            enabled_plugins = upstream_plugins.get(plugin_type, [])
            all_plugin_handlers = {}

            # Get handlers allowed for this server and plugin type
            available_handlers = self._get_contextual_handlers(
                plugin_type,
                scope=self.selected_server,
            )

            # ALWAYS add all available plugins first (as disabled/unconfigured)
            for handler_name in available_handlers.keys():
                all_plugin_handlers[handler_name] = (None, False, None, False)

            # Add enabled plugins (override the defaults above)
            for idx, plugin in enumerate(enabled_plugins):
                handler_name = getattr(plugin, "handler", plugin.__class__.__name__)
                all_plugin_handlers[handler_name] = (plugin, True, idx, False)

            # Check raw config for disabled/missing plugins (override defaults)
            if self.config.plugins:
                plugin_type_dict = getattr(self.config.plugins, plugin_type, {})

                # Check global plugins
                for config_plugin in plugin_type_dict.get("_global", []):
                    if config_plugin.handler in available_handlers:
                        # Only overwrite if the plugin is actually disabled
                        # (enabled plugins were already added above)
                        if not config_plugin.enabled:
                            all_plugin_handlers[config_plugin.handler] = (
                                None,
                                False,
                                None,
                                False,
                            )
                    else:
                        # Missing/invalid plugin
                        all_plugin_handlers[config_plugin.handler] = (
                            None,
                            False,
                            None,
                            True,
                        )

                # Check server-specific plugins
                for config_plugin in plugin_type_dict.get(self.selected_server, []):
                    if config_plugin.handler in available_handlers:
                        # Only overwrite if the plugin is actually disabled
                        # (enabled plugins were already added above)
                        if not config_plugin.enabled:
                            all_plugin_handlers[config_plugin.handler] = (
                                None,
                                False,
                                None,
                                False,
                            )
                    else:
                        # Missing/invalid plugin
                        all_plugin_handlers[config_plugin.handler] = (
                            None,
                            False,
                            None,
                            True,
                        )

            # Process and render plugins directly (like global plugins)
            if all_plugin_handlers:
                # Prepare plugin data list
                plugins_data_list = []

                # Sort by priority for initial display
                if plugin_type == "auditing":
                    sorted_handlers = sorted(
                        all_plugin_handlers.items(),
                        key=lambda x: (
                            not x[1][1],
                            x[1][2] if x[1][2] is not None else 999,
                            x[0],
                        ),
                    )
                else:

                    def get_sort_key(item, plugin_type=plugin_type):
                        handler_name, (plugin, is_enabled, orig_idx, is_missing) = item
                        resolved_priority = (
                            getattr(plugin, "priority", None) if plugin else None
                        )

                        if resolved_priority is None and self.config.plugins:
                            plugin_type_dict = getattr(
                                self.config.plugins, plugin_type, {}
                            )
                            for config_plugin in plugin_type_dict.get(
                                self.selected_server, []
                            ):
                                if config_plugin.handler == handler_name:
                                    resolved_priority = (
                                        getattr(config_plugin, "priority", 50) or 50
                                    )
                                    break
                            if resolved_priority is None:
                                for config_plugin in plugin_type_dict.get(
                                    "_global", []
                                ):
                                    if config_plugin.handler == handler_name:
                                        resolved_priority = (
                                            getattr(config_plugin, "priority", 50) or 50
                                        )
                                        break

                        if resolved_priority is None:
                            resolved_priority = 50

                        return (
                            not is_enabled,  # Enabled plugins first
                            resolved_priority,
                            orig_idx if orig_idx is not None else 999,
                            handler_name,
                        )

                    sorted_handlers = sorted(
                        all_plugin_handlers.items(), key=get_sort_key
                    )

                # Build plugin data list
                for handler_name, (
                    plugin,
                    _is_enabled,
                    _,
                    is_missing,
                ) in sorted_handlers:
                    # Get inheritance status and fall back priority
                    inheritance, priority, enabled_flag = self.get_plugin_inheritance(
                        handler_name, plugin_type, self.selected_server, plugin
                    )

                    # Always use priority from config (via get_plugin_inheritance), not from
                    # stale PluginManager plugin objects which aren't rebuilt until save
                    resolved_priority = priority if priority is not None else 50

                    # Get display name
                    display_name = self._format_handler_name(handler_name)

                    # Get status text
                    status_text = self._get_status_text(
                        inheritance, self.selected_server
                    )

                    # Check if global plugin exists and is enabled
                    global_enabled = False
                    if self.config.plugins:
                        plugin_type_dict = getattr(self.config.plugins, plugin_type, {})
                        for config_plugin in plugin_type_dict.get("_global", []):
                            if config_plugin.handler == handler_name:
                                global_enabled = config_plugin.enabled
                                break

                    # Show blank priority when plugin is disabled (matches scope field behavior)
                    display_priority = resolved_priority if enabled_flag else ""

                    # Create plugin data dictionary
                    plugin_data = {
                        "handler": handler_name,
                        "display_name": display_name,
                        "priority": display_priority,
                        "enabled": enabled_flag,
                        "inheritance": inheritance,
                        "scope": status_text,  # Renamed from 'status' to match content (scope/inheritance info)
                        "is_missing": is_missing,
                        "global_enabled": global_enabled,
                        "plugin_type": plugin_type,  # Track actual plugin type
                    }

                    # Store in model for later use (for compatibility)
                    safe_handler = self._sanitize_handler_for_id(
                        handler_name, plugin_type
                    )
                    row_key = f"{plugin_type}_{safe_handler}"
                    self._plugin_row_model[(plugin_type, row_key)] = plugin_data

                    # Add to plugins data list
                    plugins_data_list.append(plugin_data)

                # Create and mount the table widget with all plugin data
                table_widget = PluginTableWidget(
                    plugin_type=plugin_type,
                    server_name=self.selected_server,
                    plugins_data=plugins_data_list,
                    show_priority=(plugin_type != "auditing"),
                    max_visible_rows=MAX_PLUGIN_ROWS_VISIBLE,
                )
                plugins_container.mount(table_widget)

        # Log container state after mounting
        try:
            from ...debug import get_debug_logger

            logger2 = get_debug_logger()
            if logger2:
                logger2.log_event(
                    "container_state_after_mount",
                    screen=self,
                    context={
                        "container_id": "server_plugins_display",
                        "child_count": len(plugins_container.children),
                        "is_visible": plugins_container.visible,
                        "display": plugins_container.styles.display,
                        "server": self.selected_server,
                    },
                )
        except Exception:
            pass

        # Force refresh of the container after mounting all widgets
        plugins_container.refresh()

        # Log after refresh
        try:
            if logger:
                logger.log_event(
                    "container_state_after_refresh",
                    screen=self,
                    context={
                        "container_id": "server_plugins_display",
                        "child_count": len(plugins_container.children),
                        "is_visible": plugins_container.visible,
                        "display": plugins_container.styles.display,
                        "server": self.selected_server,
                    },
                )
        except Exception:
            pass

    def _get_status_text(
        self, inheritance: str, server_name: Optional[str] = None
    ) -> str:
        """Convert inheritance status to user-friendly display text.

        Args:
            inheritance: Formatted inheritance status
            server_name: Name of the currently selected server

        Returns:
            User-friendly status text (empty string if disabled)
        """
        server_scope_label = self._format_scope_for_server(server_name)
        status_map = {
            "global": "Global configuration",
            "inherited": "Inherited from global",
            "inherited (disabled)": "",
            "overrides": server_scope_label,
            "overrides (config)": server_scope_label,
            "overrides (disables)": "",
            "server-only": server_scope_label,
            "server-only (disabled)": "",
            "disabled": "",
        }
        return status_map.get(inheritance, inheritance)

    def _format_scope_for_server(self, server_name: Optional[str]) -> str:
        """Return the scope label for server-specific plugins."""
        if not server_name or server_name == "_global":
            return "Server-specific"

        server_label = server_name.replace("_", " ").strip()
        if not server_label:
            server_label = server_name

        return f"{server_label} only"

    def _build_actions_text(self, context: PluginActionContext) -> str:
        """Build actions text for display in table cell.

        Args:
            context: Plugin action context

        Returns:
            Styled button-like text for available actions
        """
        actions = []

        # Configure shown when enabled - styled EXACTLY like global plugins with background
        # Global plugins use background: $secondary
        if context.enabled:
            actions.append("[$text on $secondary] Configure [/]")

        # Use Global shown for overrides - styled with a different theme color
        # Using $panel or another secondary color to distinguish from Configure
        if context.inheritance in [
            "overrides",
            "overrides (config)",
            "overrides (disables)",
            "disabled",
            "server-only",
        ]:
            actions.append("[$text on $panel] Use Global [/]")

        return "  ".join(actions)  # Extra spacing between buttons

    def _get_plugin_actions(
        self, context: PluginActionContext
    ) -> List[Tuple[str, str]]:
        """Get appropriate action buttons for a plugin based on its state.

        Returns list of (action_name, variant) tuples.
        """
        actions = []

        # Configure is always available if enabled
        if context.enabled:
            actions.append(("Configure", "primary"))

        # Enable/Disable based on current state
        if context.enabled:
            actions.append(("Disable", "warning"))
        else:
            actions.append(("Enable", "success"))

        # Reset if there's an override
        if context.inheritance in ["overrides", "server-only", "disabled"]:
            actions.append(("Reset", "default"))

        # Remove if it's a server-specific config
        if context.server != "_global" and context.inheritance != "inherited":
            actions.append(("Remove", "error"))

        return actions

    def _format_handler_name(self, handler_name: str) -> str:
        """Format handler name for display using plugin metadata."""
        # Try to get the plugin class to use its DISPLAY_NAME
        for _plugin_type, handlers in self.available_handlers.items():
            if handler_name in handlers:
                handler_class = handlers[handler_name]
                # Use DISPLAY_NAME if available
                return getattr(
                    handler_class,
                    "DISPLAY_NAME",
                    handler_name.replace("_", " ").title(),
                )

        # Fallback to formatting the handler name
        return handler_name.replace("_", " ").title()

    def _get_plugin_description(
        self, handler_name: str, plugin_type: str, config: Dict[str, Any] = None
    ) -> str:
        """Get description for a plugin based on its configuration and status."""
        # Try to get the plugin class to use its describe_status method
        handlers = self.available_handlers.get(plugin_type, {})
        if handler_name in handlers:
            handler_class = handlers[handler_name]
            # Use describe_status if available
            if hasattr(handler_class, "describe_status") and config is not None:
                try:
                    return handler_class.describe_status(config)
                except Exception:
                    pass  # Fall through to default

            # Try to get a static description from the plugin
            if hasattr(handler_class, "DESCRIPTION"):
                return handler_class.DESCRIPTION

        # Default description
        return "Plugin configuration"

    def get_plugin_inheritance(
        self,
        handler_name: str,
        plugin_type: str,
        server_name: str,
        effective_plugin=None,
    ) -> tuple[str, Optional[int], bool]:
        """Determine how a plugin is configured for a server (for list display).

        Returns:
            Tuple of (display_status, priority, is_enabled)
        """
        # Use consolidated inheritance logic
        status, enabled, priority_from_config = self._compute_plugin_inheritance(
            handler_name, plugin_type, server_name
        )

        # For display, use priority from configuration only (server override first, then global).
        # Auditing plugins don't show priority.
        if plugin_type == "auditing":
            priority = None
        else:
            priority = priority_from_config

        # Use centralized formatter
        display_status = self._format_inheritance_status(status, enabled)
        return (display_status, priority, enabled)

    def _format_inheritance_status(self, status: str, enabled: bool) -> str:
        """Centralized inheritance status formatting.

        Args:
            status: Raw inheritance status from _compute_plugin_inheritance
            enabled: Whether plugin is enabled

        Returns:
            Human-readable inheritance status string
        """
        display_status_map = {
            "global": "global",
            "inherited": "inherited",
            "inherited (disabled)": "",
            "disabled": "disabled",  # Keep value so "Use Global" button can show
            "overrides": "overrides (config)",
            "server-only": "server-only" if enabled else "",
        }
        return display_status_map.get(status, "unknown")

    def _format_inheritance_text(
        self, inheritance: str, priority: Optional[int], plugin_type: str
    ) -> str:
        """Format the inheritance text line for display.

        Args:
            inheritance: Formatted inheritance status
            priority: Plugin priority (None for auditing plugins)
            plugin_type: Type of plugin

        Returns:
            Formatted inheritance text with arrow prefix
        """
        if priority is not None and plugin_type != "auditing":
            return f"   ↳ {inheritance} (pri: {priority})"
        else:
            return f"   ↳ {inheritance}"

    def _compute_plugin_inheritance(
        self, handler_name: str, plugin_type: str, scope: str
    ) -> tuple[str, bool, Optional[int]]:
        """Single source of truth for plugin inheritance status.

        Returns:
            Tuple of (inheritance_status, enabled, priority)
            inheritance_status: 'global' | 'inherited' | 'overrides' | 'server-only' | 'disabled'
            enabled: True if plugin is enabled
            priority: Plugin priority (for ordering)
        """
        if not self.config.plugins:
            # No plugins configured anywhere - default to disabled (consistent with line 1021)
            return ("server-only", False, 50)

        plugins_dict = getattr(self.config.plugins, plugin_type, {})

        # Check if plugin exists in global scope
        global_plugins = plugins_dict.get("_global", [])
        global_plugin = None
        for plugin in global_plugins:
            if plugin.handler == handler_name:
                global_plugin = plugin
                break

        # Check if plugin exists in server scope
        server_plugins = plugins_dict.get(scope, []) if scope != "_global" else []
        server_plugin = None
        for plugin in server_plugins:
            if plugin.handler == handler_name:
                server_plugin = plugin
                break

        # Determine inheritance status
        if scope == "_global":
            # At global scope, return 'global' status
            if global_plugin:
                return ("global", global_plugin.enabled, global_plugin.priority or 50)
            else:
                # Not configured in global scope - default to disabled
                return ("server-only", False, 50)
        else:
            # We're looking at a specific server
            if server_plugin:
                if global_plugin:
                    # Server has an override of a global plugin
                    # Check if it's a disable override (enabled=False, regardless of config content)
                    if not server_plugin.enabled:
                        return (
                            "disabled",
                            False,
                            server_plugin.priority or global_plugin.priority or 50,
                        )
                    else:
                        return (
                            "overrides",
                            server_plugin.enabled,
                            server_plugin.priority or 50,
                        )
                else:
                    # Server-only plugin
                    return (
                        "server-only",
                        server_plugin.enabled,
                        server_plugin.priority or 50,
                    )
            elif global_plugin:
                # Inherited from global
                if global_plugin.enabled:
                    return (
                        "inherited",
                        True,
                        global_plugin.priority or 50,
                    )
                else:
                    return (
                        "inherited (disabled)",
                        False,
                        global_plugin.priority or 50,
                    )
            else:
                # Not configured anywhere - default to disabled
                return ("server-only", False, 50)

    async def _get_plugin_inheritance_status(
        self, handler_name: str, plugin_type: str, scope: str
    ) -> tuple[str, bool]:
        """Legacy wrapper for compatibility - delegates to _compute_plugin_inheritance."""
        status, enabled, _ = self._compute_plugin_inheritance(
            handler_name, plugin_type, scope
        )
        return (status, enabled)

    def _get_current_plugin_config(
        self, handler_name: str, plugin_type: str, scope: str = None
    ) -> Dict[str, Any]:
        """Get current configuration for a plugin."""
        if not self.config.plugins:
            return {}

        plugins_dict = getattr(self.config.plugins, plugin_type, {})

        # If scope is specified, look in that scope first
        if scope:
            scope_plugins = plugins_dict.get(scope, [])
            for plugin_config in scope_plugins:
                if plugin_config.handler == handler_name:
                    return plugin_config.config

        # Fall back to global configuration if not found in scope
        if scope != "_global":
            global_plugins = plugins_dict.get("_global", [])
            for plugin_config in global_plugins:
                if plugin_config.handler == handler_name:
                    return plugin_config.config

        return {}

    async def _populate_server_plugins(self) -> None:
        """Populate server plugins display - delegates to _render_server_plugin_groups."""
        await self._render_server_plugin_groups()
