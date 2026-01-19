"""Navigation functionality for the Config Editor screen."""

from typing import Optional, Dict, List, Any
from textual.widgets import ListView, Button


class NavigationMixin:
    """Mixin providing navigation functionality for ConfigEditorScreen."""

    def _setup_navigation_containers(self) -> None:
        """Set up the navigation container order and their target widgets."""
        self.navigation_containers = [
            {
                "name": "global_security",
                "widget": "#global_security_widget",
                "get_target": self._get_security_plugin_target,
                "container_selector": "#global_security_widget",
            },
            {
                "name": "global_auditing",
                "widget": "#global_auditing_widget",
                "get_target": self._get_auditing_plugin_target,
                "container_selector": "#global_auditing_widget",
            },
            {
                "name": "servers_list",
                "widget": "#servers_list",
                "get_target": self._get_servers_list_target,
                "container_selector": "#servers_list",
            },
            {
                "name": "server_details",
                "widget": "#server_plugins_display",
                "get_target": self._get_server_details_target,
                "container_selector": "#server_plugins_display",
            },
        ]

    def action_navigate_next(self) -> None:
        """Navigate to the next container."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if not self.navigation_containers:
            return

        current_container = self.navigation_containers[self.current_container_index]

        # Debug logging for navigation
        if logger:
            logger.log_user_input(
                "keypress",
                key="tab",
                screen=self,
                action="navigate_next",
                current_container=current_container["name"],
            )

        # Move to the next container
        self._advance_to_next_container()

    def _advance_to_next_container(self) -> None:
        """Move to the next navigation container."""
        from textual.widgets import Input
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        # Reset scroll position if leaving an Input widget
        focused_widget = self.app.focused
        if isinstance(focused_widget, Input) and hasattr(self, "_reset_input_scroll"):
            self._reset_input_scroll(focused_widget)

        old_container_name = self.navigation_containers[self.current_container_index][
            "name"
        ]

        # Move to next container (with wraparound)
        self.current_container_index = (self.current_container_index + 1) % len(
            self.navigation_containers
        )

        # Find a container with focusable content
        attempts = 0
        while attempts < len(self.navigation_containers):
            current_container = self.navigation_containers[self.current_container_index]
            target_widget = current_container["get_target"]()

            if target_widget and getattr(target_widget, "can_focus", False):
                target_widget.focus()

                # Debug logging for successful navigation
                if logger:
                    logger.log_navigation(
                        "next",
                        old_container_name,
                        current_container["name"],
                        screen=self,
                        widget=target_widget,
                    )

                # Update the current container index to reflect where we actually are
                self.current_container_index = (self.current_container_index) % len(
                    self.navigation_containers
                )
                return

            # Try next container if current one has no focusable content
            self.current_container_index = (self.current_container_index + 1) % len(
                self.navigation_containers
            )
            attempts += 1

    def action_navigate_previous(self) -> None:
        """Navigate to the previous container."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if not self.navigation_containers:
            return

        current_container = self.navigation_containers[self.current_container_index]

        # Debug logging for navigation
        if logger:
            logger.log_user_input(
                "keypress",
                key="shift+tab",
                screen=self,
                action="navigate_previous",
                current_container=current_container["name"],
            )

        # Move to the previous container
        self._advance_to_previous_container()

    def _advance_to_previous_container(self) -> None:
        """Move to the previous navigation container."""
        from textual.widgets import Input
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        # Reset scroll position if leaving an Input widget
        focused_widget = self.app.focused
        if isinstance(focused_widget, Input) and hasattr(self, "_reset_input_scroll"):
            self._reset_input_scroll(focused_widget)

        old_container_name = self.navigation_containers[self.current_container_index][
            "name"
        ]

        # Move to previous container (with wraparound)
        self.current_container_index = (self.current_container_index - 1) % len(
            self.navigation_containers
        )

        # Find a container with focusable content
        attempts = 0
        while attempts < len(self.navigation_containers):
            current_container = self.navigation_containers[self.current_container_index]
            target_widget = current_container["get_target"]()

            if target_widget and getattr(target_widget, "can_focus", False):
                target_widget.focus()

                # Debug logging for successful navigation
                if logger:
                    logger.log_navigation(
                        "previous",
                        old_container_name,
                        current_container["name"],
                        screen=self,
                        widget=target_widget,
                    )

                # Update the current container index to reflect where we actually are
                self.current_container_index = (self.current_container_index) % len(
                    self.navigation_containers
                )
                return

            # Try previous container if current one has no focusable content
            self.current_container_index = (self.current_container_index - 1) % len(
                self.navigation_containers
            )
            attempts += 1

    def action_navigate_down(self) -> None:
        """Navigate down within current panel (same column) or move to next container at boundaries."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        focused_widget = self.app.focused
        if not focused_widget:
            return

        if logger:
            logger.log_user_input(
                "keypress",
                key="down",
                screen=self,
                action="navigate_down",
                focused_widget_id=getattr(focused_widget, "id", None),
            )
        # If ListView focused, pass-through to its cursor movement; handle only boundaries
        if isinstance(focused_widget, ListView):
            if focused_widget.id == "servers_list":
                # If at bottom, block navigation (don't wrap to top)
                list_items = list(focused_widget.children)
                current_index = getattr(focused_widget, "index", None)
                if (
                    list_items
                    and current_index is not None
                    and current_index >= len(list_items) - 1
                ):
                    return
            # Pass-through to widget for normal movement
            try:
                focused_widget.action_cursor_down()
            except Exception:
                pass
            return

        # Panel-aware vertical navigation
        panel_name = self._get_panel_name_for_widget(focused_widget)
        if panel_name:
            try:
                panel_widget = self._get_panel_widget_by_name(panel_name)
                pos = self._get_row_col_for_widget(panel_widget, focused_widget)
                rows = self._collect_panel_rows(panel_widget)
                if pos and rows:
                    row, col = pos["row"], pos["col"]
                    if row < len(rows) - 1:
                        # Preserve action_index when moving vertically between rows of action buttons
                        if col == "action":
                            action_index = pos.get("action_index", 0)
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row + 1, col, action_index=action_index
                            )
                        else:
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row + 1, col
                            )
                        if target:
                            self._set_panel_focus_memory(panel_name, row + 1, col)
                            target.focus()
                            return
                    else:
                        # Boundary behavior
                        if panel_name == "global_security" and col == "checkbox":
                            # Jump to + Add button instead of directly to servers list
                            try:
                                add_button = self.query_one("#add_server", Button)
                                if add_button and getattr(
                                    add_button, "can_focus", False
                                ):
                                    add_button.focus()
                                    return
                            except Exception:
                                # Button doesn't exist (e.g., in config selector screen)
                                pass
                            # Fallback to servers_list if Add button not available
                            try:
                                servers_list = self.query_one("#servers_list", ListView)
                                servers_list.focus()
                                if getattr(servers_list, "children", None):
                                    # List contains only server items; select first
                                    servers_list.index = 0
                                return
                            except Exception:
                                pass
                        elif panel_name in ["global_security", "global_auditing"]:
                            # Check if server is selected and server info panel is populated
                            server_selected = (
                                hasattr(self, "selected_server")
                                and self.selected_server
                            )

                            if not server_selected:
                                # No server selected - ALL last-row global plugin widgets go to + Add button
                                try:
                                    add_button = self.query_one("#add_server", Button)
                                    if add_button and getattr(
                                        add_button, "can_focus", False
                                    ):
                                        add_button.focus()
                                        if logger:
                                            logger.log_event(
                                                "NAV_GLOBAL_PLUGINS_TO_ADD_BUTTON",
                                                screen=self,
                                                context={
                                                    "from_panel": panel_name,
                                                    "from_column": col,
                                                    "reason": "no_server_selected",
                                                },
                                            )
                                        return
                                except Exception:
                                    # Button doesn't exist (e.g., in config selector screen)
                                    pass
                                # Fallback to servers_list if Add button not available
                                try:
                                    servers_list = self.query_one(
                                        "#servers_list", ListView
                                    )
                                    servers_list.focus()
                                    if getattr(servers_list, "children", None):
                                        servers_list.index = 0
                                    if logger:
                                        logger.log_event(
                                            "NAV_GLOBAL_PLUGINS_TO_SERVERS_LIST",
                                            screen=self,
                                            context={
                                                "from_panel": panel_name,
                                                "from_column": col,
                                                "reason": "no_server_selected",
                                            },
                                        )
                                    return
                                except Exception:
                                    pass
                            else:
                                # Server is selected - special handling for server name input
                                # Exception: last checkbox in security/middleware goes to normal navigation (servers list)
                                if (
                                    panel_name == "global_security"
                                    and col == "checkbox"
                                ):
                                    # This is handled above - goes to servers list
                                    pass
                                else:
                                    # From last row of global plugins (except security checkbox) to server name input
                                    try:
                                        server_name_input = self.query_one(
                                            "#server_name_input"
                                        )
                                        if server_name_input and getattr(
                                            server_name_input, "can_focus", False
                                        ):
                                            if logger:
                                                logger.log_event(
                                                    "NAV_GLOBAL_PLUGINS_TO_SERVER_NAME",
                                                    screen=self,
                                                    context={
                                                        "from_panel": panel_name,
                                                        "from_column": col,
                                                        "to_widget": "server_name_input",
                                                    },
                                                )
                                            server_name_input.focus()
                                            return
                                    except Exception:
                                        pass
                        elif panel_name == "server_plugins":
                            if self._focus_adjacent_server_plugin_row(
                                panel_widget,
                                "down",
                                col,
                                pos.get("action_index", 0),
                            ):
                                return
                            # Try to navigate to Remove Server button first
                            try:
                                remove_container = self.query_one(
                                    "#remove_server_container"
                                )
                                if remove_container and not remove_container.has_class(
                                    "hidden"
                                ):
                                    remove_btn = remove_container.query_one(
                                        "#remove_server", Button
                                    )
                                    if (
                                        remove_btn
                                        and getattr(remove_btn, "can_focus", False)
                                        and not remove_btn.disabled
                                    ):
                                        if logger:
                                            logger.log_event(
                                                "NAV_PLUGINS_TO_REMOVE_BUTTON",
                                                screen=self,
                                                context={
                                                    "from_panel": panel_name,
                                                    "from_column": col,
                                                    "to_widget": "remove_server",
                                                },
                                            )
                                        remove_btn.focus()
                                        return
                            except Exception:
                                pass
                            # Don't consume - let framework handle it by falling through
                        else:
                            # Otherwise consume without moving
                            return
            except Exception:
                pass

        # Special handling for server_info widgets (like server name input)
        try:
            server_info_container = self.query_one("#server_info")
            if self._is_widget_inside_container(focused_widget, server_info_container):
                # Get all focusable widgets in server_info container in order
                info_widgets = list(server_info_container.query("*"))
                focusable_info_widgets = [
                    w
                    for w in info_widgets
                    if getattr(w, "can_focus", False)
                    and not getattr(w, "disabled", False)
                ]

                if focusable_info_widgets:
                    try:
                        current_index = focusable_info_widgets.index(focused_widget)
                        # If not at the last server info widget, go to next server info widget
                        if current_index < len(focusable_info_widgets) - 1:
                            next_widget = focusable_info_widgets[current_index + 1]
                            if logger:
                                logger.log_event(
                                    "NAV_SERVER_INFO_INTERNAL",
                                    screen=self,
                                    context={
                                        "from_widget": (
                                            focused_widget.id
                                            if hasattr(focused_widget, "id")
                                            else None
                                        ),
                                        "to_widget": (
                                            next_widget.id
                                            if hasattr(next_widget, "id")
                                            else None
                                        ),
                                        "direction": "down",
                                    },
                                )
                            next_widget.focus()
                            return
                    except ValueError:
                        # focused_widget not in list, treat as last
                        pass

                # If at last server info widget (or not found), navigate to plugins
                plugins_container = self.query_one("#server_plugins_display")
                all_widgets = list(plugins_container.query("*"))
                focusable_widgets = [
                    w for w in all_widgets
                    if getattr(w, "can_focus", False)
                    and not getattr(w, "disabled", False)
                ]

                if focusable_widgets:
                    # If navigating away from any input, reset its scroll position
                    from textual.widgets import Input

                    if isinstance(focused_widget, Input) and hasattr(
                        self, "_reset_input_scroll"
                    ):
                        self._reset_input_scroll(focused_widget)

                    if logger:
                        logger.log_event(
                            "NAV_SERVER_INFO_TO_PLUGINS",
                            screen=self,
                            context={
                                "from_widget": (
                                    focused_widget.id
                                    if hasattr(focused_widget, "id")
                                    else None
                                ),
                                "to_widget": (
                                    focusable_widgets[0].id
                                    if hasattr(focusable_widgets[0], "id")
                                    else None
                                ),
                            },
                        )
                    focusable_widgets[0].focus()
                    return
        except Exception:
            pass

        # Special handling for + Add button
        try:
            if hasattr(focused_widget, "id") and focused_widget.id == "add_server":
                # Check if there are servers - if not, block navigation (at bottom)
                try:
                    servers_list = self.query_one("#servers_list", ListView)
                    list_items = list(servers_list.children) if servers_list else []
                    if not list_items:
                        # No servers - Add button is at bottom, block navigation
                        return
                    # There are servers, navigate to servers list
                    servers_list.focus()
                    servers_list.index = 0
                    if logger:
                        logger.log_event(
                            "NAV_ADD_BUTTON_TO_SERVERS_LIST",
                            screen=self,
                            context={
                                "from_widget": "add_server",
                                "to_widget": "servers_list",
                            },
                        )
                    return
                except Exception:
                    pass
        except Exception:
            pass

        # Block DOWN navigation from Remove Server button (bottom edge of UI)
        if hasattr(focused_widget, "id") and focused_widget.id == "remove_server":
            return

        # Not in plugin panel → advance to next container
        self.action_navigate_next()

    def action_navigate_up(self) -> None:
        """Navigate up within the current panel (same column) or move to previous container at boundaries."""
        from ...debug import get_debug_logger
        from ...widgets.plugin_table import PluginTableWidget

        logger = get_debug_logger()

        focused_widget = self.app.focused
        if not focused_widget:
            return

        if logger:
            logger.log_user_input(
                "keypress",
                key="up",
                screen=self,
                action="navigate_up",
                focused_widget_id=getattr(focused_widget, "id", None),
            )

        # If ListView focused, pass-through to its cursor movement; handle only boundaries
        if isinstance(focused_widget, ListView):
            if focused_widget.id == "servers_list":
                current_index = getattr(focused_widget, "index", None)
                if current_index in (None, 0):
                    # At top - move focus to + Add button instead of last checkbox
                    try:
                        add_button = self.query_one("#add_server", Button)
                        if add_button and getattr(add_button, "can_focus", False):
                            add_button.focus()
                            return
                    except Exception:
                        # Button doesn't exist (e.g., in config selector screen)
                        pass
                    # Fallback to last checkbox if Add button not available
                    try:
                        from ...widgets.plugin_table import PluginTableWidget

                        security_widget = self.query_one(
                            "#global_security_widget", PluginTableWidget
                        )
                        checkboxes = security_widget.query("ASCIICheckbox")
                        if checkboxes:
                            checkbox_list = list(checkboxes)
                            if checkbox_list:
                                checkbox_list[-1].focus()
                                return
                    except Exception:
                        pass
            # Pass-through to widget for normal movement
            try:
                focused_widget.action_cursor_up()
            except Exception:
                pass
            return

        # Panel-aware vertical navigation
        panel_name = self._get_panel_name_for_widget(focused_widget)
        if panel_name:
            try:
                panel_widget = self._get_panel_widget_by_name(panel_name)
                pos = self._get_row_col_for_widget(panel_widget, focused_widget)
                if pos:
                    row, col = pos["row"], pos["col"]
                    if row > 0:
                        # Preserve action_index when moving vertically between rows of action buttons
                        if col == "action":
                            action_index = pos.get("action_index", 0)
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row - 1, col, action_index=action_index
                            )
                        else:
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row - 1, col
                            )
                        if target:
                            self._set_panel_focus_memory(panel_name, row - 1, col)
                            target.focus()
                            return
                    else:
                        if panel_name == "server_plugins":
                            if self._focus_adjacent_server_plugin_row(
                                panel_widget,
                                "up",
                                col,
                                pos.get("action_index", 0),
                            ):
                                return
                            # At top of server plugins → navigate up to server_info
                            try:
                                server_info_container = self.query_one("#server_info")
                                info_widgets = list(server_info_container.query("*"))
                                focusable_widgets = [
                                    w
                                    for w in info_widgets
                                    if getattr(w, "can_focus", False)
                                    and not getattr(w, "disabled", False)
                                ]

                                if focusable_widgets:
                                    # If navigating away from any input, reset its scroll position
                                    from textual.widgets import Input

                                    if isinstance(focused_widget, Input) and hasattr(
                                        self, "_reset_input_scroll"
                                    ):
                                        self._reset_input_scroll(focused_widget)

                                    if logger:
                                        logger.log_event(
                                            "NAV_PLUGINS_TO_SERVER_INFO",
                                            screen=self,
                                            context={
                                                "from_widget": (
                                                    focused_widget.id
                                                    if hasattr(focused_widget, "id")
                                                    else None
                                                ),
                                                "to_widget": (
                                                    focusable_widgets[-1].id
                                                    if hasattr(
                                                        focusable_widgets[-1], "id"
                                                    )
                                                    else None
                                                ),
                                            },
                                        )
                                    # Focus last focusable widget in server_info (typically server name input)
                                    focusable_widgets[-1].focus()
                                    return
                            except Exception:
                                pass
                    # At top → consume without moving
                    return
            except Exception:
                pass

        # Special handling for server_info widgets (like server name input)
        try:
            server_info_container = self.query_one("#server_info")
            if self._is_widget_inside_container(focused_widget, server_info_container):
                # Get all focusable widgets in server_info container in order
                info_widgets = list(server_info_container.query("*"))
                focusable_info_widgets = [
                    w
                    for w in info_widgets
                    if getattr(w, "can_focus", False)
                    and not getattr(w, "disabled", False)
                ]

                if focusable_info_widgets:
                    try:
                        current_index = focusable_info_widgets.index(focused_widget)
                        # If not at the first server info widget, go to previous server info widget
                        if current_index > 0:
                            # If navigating away from any input, reset its scroll position
                            from textual.widgets import Input

                            if isinstance(focused_widget, Input) and hasattr(
                                self, "_reset_input_scroll"
                            ):
                                self._reset_input_scroll(focused_widget)

                            prev_widget = focusable_info_widgets[current_index - 1]
                            if logger:
                                logger.log_event(
                                    "NAV_SERVER_INFO_INTERNAL",
                                    screen=self,
                                    context={
                                        "from_widget": (
                                            focused_widget.id
                                            if hasattr(focused_widget, "id")
                                            else None
                                        ),
                                        "to_widget": (
                                            prev_widget.id
                                            if hasattr(prev_widget, "id")
                                            else None
                                        ),
                                        "direction": "up",
                                    },
                                )
                            prev_widget.focus()
                            return
                    except ValueError:
                        # focused_widget not in list, treat as first
                        pass

                # If at first server info widget (or not found), navigate to global security
                from ...widgets.plugin_table import PluginTableWidget

                security_widget = self.query_one(
                    "#global_security_widget", PluginTableWidget
                )

                # Look for action buttons first (they have IDs like action_handler_name)
                all_widgets = list(security_widget.query("*"))
                action_buttons = [
                    w
                    for w in all_widgets
                    if hasattr(w, "id")
                    and w.id
                    and w.id.startswith("action_")
                    and getattr(w, "can_focus", False)
                ]

                if action_buttons:
                    # If navigating away from any input, reset its scroll position
                    from textual.widgets import Input

                    if isinstance(focused_widget, Input) and hasattr(
                        self, "_reset_input_scroll"
                    ):
                        self._reset_input_scroll(focused_widget)

                    # Focus the last action button (typically the Configure button of the last plugin)
                    if logger:
                        logger.log_event(
                            "NAV_SERVER_INFO_TO_SECURITY",
                            screen=self,
                            context={
                                "from_widget": (
                                    focused_widget.id
                                    if hasattr(focused_widget, "id")
                                    else None
                                ),
                                "to_widget": (
                                    action_buttons[-1].id
                                    if hasattr(action_buttons[-1], "id")
                                    else None
                                ),
                                "button_count": len(action_buttons),
                            },
                        )
                    action_buttons[-1].focus()
                    return

                # Fallback to checkboxes if no action buttons found
                checkboxes = list(security_widget.query("ASCIICheckbox"))
                if checkboxes:
                    if logger:
                        logger.log_event(
                            "NAV_SERVER_INFO_TO_SECURITY_CHECKBOX",
                            screen=self,
                            context={
                                "from_widget": (
                                    focused_widget.id
                                    if hasattr(focused_widget, "id")
                                    else None
                                ),
                                "to_widget": (
                                    checkboxes[-1].id
                                    if hasattr(checkboxes[-1], "id")
                                    else None
                                ),
                            },
                        )
                    checkboxes[-1].focus()
                    return
        except Exception:
            pass

        # Special handling for Remove Server button
        try:
            if hasattr(focused_widget, "id") and focused_widget.id == "remove_server":
                # Navigate up to last plugin in auditing table
                try:
                    plugins_container = self.query_one("#server_plugins_display")
                    all_widgets = list(plugins_container.query("*"))
                    focusable_widgets = [
                        w for w in all_widgets
                        if getattr(w, "can_focus", False)
                        and not getattr(w, "disabled", False)
                    ]

                    if focusable_widgets:
                        # Find the last auditing plugin checkbox
                        auditing_checkboxes = [
                            w
                            for w in focusable_widgets
                            if hasattr(w, "id")
                            and w.id
                            and "auditing" in w.id
                            and w.id.startswith("checkbox_")
                        ]

                        if auditing_checkboxes:
                            last_auditing_checkbox = auditing_checkboxes[-1]
                            if logger:
                                logger.log_event(
                                    "NAV_REMOVE_TO_PLUGINS",
                                    screen=self,
                                    context={
                                        "from_widget": "remove_server",
                                        "to_widget": last_auditing_checkbox.id,
                                    },
                                )
                            last_auditing_checkbox.focus()
                            return

                        # Fallback to last focusable widget in plugins
                        if logger:
                            logger.log_event(
                                "NAV_REMOVE_TO_PLUGINS_FALLBACK",
                                screen=self,
                                context={
                                    "from_widget": "remove_server",
                                    "to_widget": (
                                        focusable_widgets[-1].id
                                        if hasattr(focusable_widgets[-1], "id")
                                        else None
                                    ),
                                },
                            )
                        focusable_widgets[-1].focus()
                        return
                except Exception:
                    pass
        except Exception:
            pass

        # Special handling for + Add button
        try:
            if hasattr(focused_widget, "id") and focused_widget.id == "add_server":
                # Up from + Add button goes to last checkbox in Global Security widget
                try:
                    from ...widgets.plugin_table import PluginTableWidget

                    security_widget = self.query_one(
                        "#global_security_widget", PluginTableWidget
                    )
                    checkboxes = security_widget.query("ASCIICheckbox")
                    if checkboxes:
                        checkbox_list = list(checkboxes)
                        if checkbox_list:
                            if logger:
                                logger.log_event(
                                    "NAV_ADD_BUTTON_TO_SECURITY",
                                    screen=self,
                                    context={
                                        "from_widget": "add_server",
                                        "to_widget": (
                                            checkbox_list[-1].id
                                            if hasattr(checkbox_list[-1], "id")
                                            else None
                                        ),
                                    },
                                )
                            checkbox_list[-1].focus()
                            return
                except Exception:
                    pass
        except Exception:
            pass

        # Not in plugin panel → go to previous container
        self.action_navigate_previous()

    def action_navigate_right(self) -> None:
        """Navigate right: within row (checkbox→action), or cross to Auditing from Security action; Auditing action behaves like Tab."""
        from textual.widgets import Input
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        focused_widget = self.app.focused
        if not focused_widget:
            return

        if logger:
            logger.log_user_input(
                "keypress",
                key="right",
                screen=self,
                action="navigate_right",
                focused_widget_id=getattr(focused_widget, "id", None),
            )

        # Input widgets handle their own right arrow - never navigate away
        if isinstance(focused_widget, Input):
            try:
                focused_widget.action_cursor_right()
            except Exception:
                pass
            return

        # Deterministic routing from servers_list → server_details
        # Rationale: When the servers list has focus and the user presses →,
        # always try to enter the server_details panel.
        try:
            from textual.widgets import ListView as _LV

            if (
                isinstance(focused_widget, _LV)
                and getattr(focused_widget, "id", None) == "servers_list"
            ):
                target = self._get_server_details_target()
                if target and getattr(target, "can_focus", False):
                    # Move focus and align container index/memory
                    target.focus()
                    self._update_container_index("server_details")
                    if logger:
                        logger.log_navigation(
                            "next",
                            "servers_list",
                            "server_details",
                            screen=self,
                            widget=target,
                        )
                    return
        except Exception:
            # Fall back to generic flow if anything goes wrong
            pass

        # Panel-aware horizontal navigation
        panel_name = self._get_panel_name_for_widget(focused_widget)
        if panel_name:
            try:
                panel_widget = self._get_panel_widget_by_name(panel_name)
                pos = self._get_row_col_for_widget(panel_widget, focused_widget)
                if pos:
                    row, col = pos["row"], pos["col"]
                    if panel_name == "global_security":
                        if col == "checkbox":
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row, "action"
                            )
                            if target:
                                self._set_panel_focus_memory(panel_name, row, "action")
                                target.focus()
                                return
                        else:  # action → cross to Auditing checkbox
                            try:
                                aud_widget = self._get_panel_widget_by_name(
                                    "global_auditing"
                                )
                                aud_rows = self._collect_panel_rows(aud_widget)
                                if aud_rows:
                                    target = self._resolve_widget_by_row_col(
                                        aud_widget,
                                        min(row, len(aud_rows) - 1),
                                        "checkbox",
                                    )
                                    if target:
                                        self._set_panel_focus_memory(
                                            "global_auditing",
                                            min(row, len(aud_rows) - 1),
                                            "checkbox",
                                        )
                                        self.action_navigate_next()
                                        return
                            except Exception:
                                pass
                    elif panel_name == "global_auditing":
                        if col == "checkbox":
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row, "action"
                            )
                            if target:
                                self._set_panel_focus_memory(panel_name, row, "action")
                                target.focus()
                                return
                        else:
                            # Auditing action → at right edge, block navigation
                            return
                    elif panel_name == "server_plugins":
                        # Handle horizontal navigation in server plugin rows
                        # Navigate checkbox → Configure → Use Global → next container
                        if col == "checkbox":
                            # Go to first action (Configure button)
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row, "action", action_index=0
                            )
                            if target:
                                self._set_panel_focus_memory(panel_name, row, "action")
                                target.focus()
                                return
                        elif col == "action":
                            # Check which action button we're on
                            action_index = pos.get("action_index", 0)
                            rows = self._collect_panel_rows(panel_widget)
                            if rows and row < len(rows):
                                actions = rows[row].get("actions", [])
                                # If there's a next action button, go to it
                                if action_index + 1 < len(actions):
                                    target = actions[action_index + 1]
                                    if target:
                                        target.focus()
                                        return
                            # No more action buttons → at right edge, block navigation
                            return
            except Exception:
                pass

        # Block RIGHT navigation from Test Connection and Remove Server buttons (right edge of UI)
        if hasattr(focused_widget, "id") and focused_widget.id in ("test_connection_button", "remove_server"):
            return

        # Not in plugin panel → fall back to next container
        self._advance_to_next_container()

    def action_navigate_left(self) -> None:
        """Navigate left: within row (action→checkbox), or cross from Auditing checkbox to Security action; Security checkbox behaves like Shift+Tab."""
        from textual.widgets import Input
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        focused_widget = self.app.focused
        if not focused_widget:
            return

        if logger:
            logger.log_user_input(
                "keypress",
                key="left",
                screen=self,
                action="navigate_left",
                focused_widget_id=getattr(focused_widget, "id", None),
            )

        # Input widgets handle their own left arrow - never navigate away
        if isinstance(focused_widget, Input):
            try:
                focused_widget.action_cursor_left()
            except Exception:
                pass
            return

        # Panel-aware horizontal navigation
        panel_name = self._get_panel_name_for_widget(focused_widget)
        if panel_name:
            try:
                panel_widget = self._get_panel_widget_by_name(panel_name)
                pos = self._get_row_col_for_widget(panel_widget, focused_widget)
                if pos:
                    row, col = pos["row"], pos["col"]
                    if panel_name == "global_auditing":
                        if col == "action":
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row, "checkbox"
                            )
                            if target:
                                self._set_panel_focus_memory(
                                    panel_name, row, "checkbox"
                                )
                                target.focus()
                                return
                        else:
                            # Auditing checkbox → cross to Security action same row
                            try:
                                sec_widget = self._get_panel_widget_by_name(
                                    "global_security"
                                )
                                sec_rows = self._collect_panel_rows(sec_widget)
                                if sec_rows:
                                    target = self._resolve_widget_by_row_col(
                                        sec_widget,
                                        min(row, len(sec_rows) - 1),
                                        "action",
                                    )
                                    if target:
                                        self._set_panel_focus_memory(
                                            "global_security",
                                            min(row, len(sec_rows) - 1),
                                            "action",
                                        )
                                        self.action_navigate_previous()
                                        return
                            except Exception:
                                pass
                    elif panel_name == "global_security":
                        if col == "action":
                            target = self._resolve_widget_by_row_col(
                                panel_widget, row, "checkbox"
                            )
                            if target:
                                self._set_panel_focus_memory(
                                    panel_name, row, "checkbox"
                                )
                                target.focus()
                                return
                        else:
                            # Security checkbox → at left edge, block navigation
                            return
                    elif panel_name == "server_plugins":
                        # Handle horizontal navigation in server plugin rows
                        # Navigate backward: next container ← Use Global ← Configure ← checkbox
                        if col == "action":
                            # Check which action button we're on
                            action_index = pos.get("action_index", 0)
                            if action_index > 0:
                                # Go to previous action button
                                rows = self._collect_panel_rows(panel_widget)
                                if rows and row < len(rows):
                                    actions = rows[row].get("actions", [])
                                    if action_index - 1 >= 0:
                                        target = actions[action_index - 1]
                                        if target:
                                            target.focus()
                                            return
                            else:
                                # We're on first action, go back to checkbox
                                target = self._resolve_widget_by_row_col(
                                    panel_widget, row, "checkbox"
                                )
                                if target:
                                    self._set_panel_focus_memory(
                                        panel_name, row, "checkbox"
                                    )
                                    target.focus()
                                    return
                        else:
                            # From checkbox, move to previous container
                            self.action_navigate_previous()
                            return
            except Exception:
                pass

        # Block LEFT navigation from servers list and Add button (left edge of UI)
        from textual.widgets import ListView
        if isinstance(focused_widget, ListView) and getattr(focused_widget, "id", None) == "servers_list":
            return
        if hasattr(focused_widget, "id") and focused_widget.id == "add_server":
            return

        # Not in plugin panel → previous container
        self._advance_to_previous_container()

    # Focus management helpers
    def _track_widget_focus(self, focused_widget) -> None:
        """Track focus for navigation memory system."""
        from ...debug import get_debug_logger
        from ...widgets.plugin_table import PluginTableWidget

        logger = get_debug_logger()

        # Special handling for plugin widgets - track row/column within panel
        if self._is_checkbox(focused_widget) or self._is_action(focused_widget):
            try:
                sec = self.query_one("#global_security_widget", PluginTableWidget)
                if self._is_widget_inside_container(focused_widget, sec):
                    pos = self._get_row_col_for_widget(sec, focused_widget)
                    if pos:
                        self._set_panel_focus_memory(
                            "global_security", pos["row"], pos["col"]
                        )
                    old_focus = self.container_focus_memory.get("global_security")
                    self.container_focus_memory["global_security"] = focused_widget
                    if logger:
                        logger.log_state_change(
                            "focus_memory",
                            {"global_security": old_focus},
                            {"global_security": focused_widget},
                            screen=self,
                            widget=focused_widget,
                        )
                    self._update_container_index("global_security")
                    return
            except Exception:
                pass
            try:
                aud = self.query_one("#global_auditing_widget", PluginTableWidget)
                if self._is_widget_inside_container(focused_widget, aud):
                    pos = self._get_row_col_for_widget(aud, focused_widget)
                    if pos:
                        self._set_panel_focus_memory(
                            "global_auditing", pos["row"], pos["col"]
                        )
                    old_focus = self.container_focus_memory.get("global_auditing")
                    self.container_focus_memory["global_auditing"] = focused_widget
                    if logger:
                        logger.log_state_change(
                            "focus_memory",
                            {"global_auditing": old_focus},
                            {"global_auditing": focused_widget},
                            screen=self,
                            widget=focused_widget,
                        )
                    self._update_container_index("global_auditing")
                    return
            except Exception:
                pass

        # Handle ListView widgets
        if isinstance(focused_widget, ListView):
            if focused_widget.id == "servers_list":
                old_focus = self.container_focus_memory.get("servers_list")
                self.container_focus_memory["servers_list"] = focused_widget

                # Log focus memory update
                if logger:
                    logger.log_state_change(
                        "focus_memory",
                        {"servers_list": old_focus},
                        {"servers_list": focused_widget},
                        screen=self,
                        widget=focused_widget,
                    )

                self._update_container_index("servers_list")
                return

        # Handle server details - any focusable widget in server details or server info containers
        try:
            # Check both server_plugins_display and server_info containers
            server_plugins_container = self.query_one("#server_plugins_display")
            server_info_container = self.query_one("#server_info")

            is_in_plugins = self._is_widget_inside_container(
                focused_widget, server_plugins_container
            )
            is_in_info = self._is_widget_inside_container(
                focused_widget, server_info_container
            )

            if is_in_plugins or is_in_info:
                old_focus = self.container_focus_memory.get("server_details")
                self.container_focus_memory["server_details"] = focused_widget

                # Log focus memory update
                if logger:
                    logger.log_state_change(
                        "focus_memory",
                        {"server_details": old_focus},
                        {"server_details": focused_widget},
                        screen=self,
                        widget=focused_widget,
                    )

                self._update_container_index("server_details")
        except Exception:
            # Widget query failed - continue without updating
            pass

    def _update_container_index(self, container_name: str) -> None:
        """Update current container index based on container name."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        old_index = self.current_container_index
        for i, container in enumerate(self.navigation_containers):
            if container["name"] == container_name:
                self.current_container_index = i

                # Log container index change
                if logger and old_index != i:
                    logger.log_event(
                        "state_change",
                        screen=self,
                        context={
                            "component": "container_index",
                            "container_name": container_name,
                        },
                        old_value=old_index,
                        new_value=i,
                    )
                break

    def _is_widget_inside_container(self, widget, container):
        """Check if a widget is inside a container (including nested containers)."""
        current = widget
        while current and current != self:
            if current == container:
                return True
            current = current.parent
        return False

    # Panel navigation helpers
    def _is_checkbox(self, widget) -> bool:
        wid = getattr(widget, "id", None)
        if isinstance(wid, str) and wid.startswith("checkbox_"):
            return True
        return hasattr(widget, "__class__") and "ASCIICheckbox" in str(widget.__class__)

    def _is_action(self, widget) -> bool:
        wid = getattr(widget, "id", None)
        return isinstance(wid, str) and wid.startswith("action_")

    def _get_handler_from_widget(self, widget) -> Optional[str]:
        wid = getattr(widget, "id", None)
        if not isinstance(wid, str):
            return None
        if wid.startswith("checkbox_"):
            return wid.replace("checkbox_", "", 1)
        if wid.startswith("action_"):
            # Handle both action_handler and action_configure_handler patterns
            action_part = wid.replace("action_", "", 1)
            # If it starts with configure_ or useglobal_, strip that prefix
            if action_part.startswith("configure_"):
                return action_part.replace("configure_", "", 1)
            elif action_part.startswith("useglobal_"):
                return action_part.replace("useglobal_", "", 1)
            # Otherwise return as-is (for global plugin pattern)
            return action_part
        return None

    def _get_panel_widget_by_name(self, panel_name: str):
        from ...widgets.plugin_table import PluginTableWidget

        if panel_name == "global_security":
            return self.query_one("#global_security_widget", PluginTableWidget)
        if panel_name == "global_auditing":
            return self.query_one("#global_auditing_widget", PluginTableWidget)
        if panel_name == "server_plugins":
            # Return the first PluginTableWidget that contains the focused widget
            focused_widget = self.app.focused
            try:
                server_display = self.query_one("#server_plugins_display")
                for table_widget in server_display.query(PluginTableWidget):
                    if self._is_widget_inside_container(focused_widget, table_widget):
                        return table_widget
                # If no focused widget, return first table widget
                tables = list(server_display.query(PluginTableWidget))
                return tables[0] if tables else None
            except Exception:
                pass
        return None

    def _get_panel_name_for_widget(self, widget) -> Optional[str]:
        from ...widgets.plugin_table import PluginTableWidget

        try:
            sec = self.query_one("#global_security_widget", PluginTableWidget)
            if self._is_widget_inside_container(widget, sec):
                return "global_security"
        except Exception:
            pass
        try:
            aud = self.query_one("#global_auditing_widget", PluginTableWidget)
            if self._is_widget_inside_container(widget, aud):
                return "global_auditing"
        except Exception:
            pass
        # Check if widget is inside any PluginTableWidget in the server_plugins_display
        try:
            server_display = self.query_one("#server_plugins_display")
            for table_widget in server_display.query(PluginTableWidget):
                if self._is_widget_inside_container(widget, table_widget):
                    return "server_plugins"
        except Exception:
            pass
        return None

    def _collect_panel_rows(self, panel_widget) -> List[Dict[str, Any]]:
        """Return ordered rows for a panel. Each row: {row, handler, checkbox, action(s)}."""
        if not panel_widget:
            return []
        checkboxes = list(panel_widget.query("ASCIICheckbox"))
        if not checkboxes:
            checkboxes = [w for w in panel_widget.query("*") if self._is_checkbox(w)]
        all_nodes = list(panel_widget.query("*"))

        # Collect ALL action buttons, grouped by handler
        # Important: maintain the order they appear in the DOM
        actions_by_handler: Dict[str, List[Any]] = {}
        for w in all_nodes:
            if self._is_action(w):
                h = self._get_handler_from_widget(w)
                if h:
                    if h not in actions_by_handler:
                        actions_by_handler[h] = []
                    actions_by_handler[h].append(w)

        # Sort action buttons within each handler by their ID
        # Configure buttons (action_configure_*) should come before Use Global (action_useglobal_*)
        for h in actions_by_handler:
            actions_by_handler[h].sort(
                key=lambda w: (0 if "configure" in getattr(w, "id", "").lower() else 1)
            )

        rows: List[Dict[str, Any]] = []
        for idx, cb in enumerate(checkboxes):
            handler = self._get_handler_from_widget(cb)
            action_list = actions_by_handler.get(handler, [])
            # For compatibility, keep 'action' as the first action button
            # But also store all actions for navigation
            rows.append(
                {
                    "row": idx,
                    "handler": handler,
                    "checkbox": cb,
                    "action": action_list[0] if action_list else None,
                    "actions": action_list,  # All action buttons for this row
                }
            )

        # Handle any actions without checkboxes
        known = {r["handler"] for r in rows if r["handler"]}
        extras = [h for h in actions_by_handler.keys() if h not in known]
        for h in extras:
            action_list = actions_by_handler[h]
            rows.append(
                {
                    "row": len(rows),
                    "handler": h,
                    "checkbox": None,
                    "action": action_list[0] if action_list else None,
                    "actions": action_list,
                }
            )

        return rows

    def _get_row_col_for_widget(self, panel_widget, widget) -> Optional[Dict[str, Any]]:
        rows = self._collect_panel_rows(panel_widget)
        for r in rows:
            if widget == r.get("checkbox"):
                return {"row": r["row"], "col": "checkbox"}
            # Check all actions in the row
            actions = r.get("actions", [])
            if widget in actions:
                # Return which action button this is
                action_index = actions.index(widget)
                return {"row": r["row"], "col": "action", "action_index": action_index}
        return None

    def _resolve_widget_by_row_col(
        self, panel_widget, row_index: int, column: str, action_index: int = 0
    ):
        rows = self._collect_panel_rows(panel_widget)
        if not rows:
            return None
        row_index = max(0, min(row_index, len(rows) - 1))
        target = rows[row_index]
        if column == "checkbox":
            checkbox = target.get("checkbox")
            if checkbox and getattr(checkbox, "can_focus", False) and not getattr(
                checkbox, "disabled", False
            ):
                return checkbox
            for action in target.get("actions", []):
                if getattr(action, "can_focus", False):
                    return action
            return checkbox
        elif column == "action":
            # Return specific action by index
            actions = target.get("actions", [])
            if actions and 0 <= action_index < len(actions):
                return actions[action_index]
            elif actions:
                # Fallback to first action if index out of range
                return actions[0]
        return None

    def _focus_adjacent_server_plugin_row(
        self,
        current_table,
        direction: str,
        column: str,
        action_index: int = 0,
    ) -> bool:
        """Move focus to the nearest adjacent server plugin table.

        Returns True when focus is moved successfully.
        """
        from ...widgets.plugin_table import PluginTableWidget

        try:
            server_display = self.query_one("#server_plugins_display")
            tables = list(server_display.query(PluginTableWidget))
        except Exception:
            return False

        if not tables:
            return False

        try:
            current_index = tables.index(current_table)
        except ValueError:
            return False

        if direction == "down":
            candidate_tables = tables[current_index + 1 :]
            def row_picker(rows):
                return 0
        elif direction == "up":
            candidate_tables = list(reversed(tables[:current_index]))
            def row_picker(rows):
                return len(rows) - 1
        else:
            return False

        for table in candidate_tables:
            rows = self._collect_panel_rows(table)
            if not rows:
                continue

            target_row = row_picker(rows)
            column_candidates = [column]
            if column == "action":
                column_candidates.append("checkbox")

            for col_option in column_candidates:
                action_idx = action_index if col_option == "action" else 0
                target = self._resolve_widget_by_row_col(
                    table,
                    target_row,
                    col_option,
                    action_index=action_idx,
                )
                if target and getattr(target, "can_focus", False):
                    self._set_panel_focus_memory(
                        "server_plugins", target_row, col_option
                    )
                    target.focus()
                    return True

        return False

    def _set_panel_focus_memory(
        self, panel_name: str, row_index: int, column: str
    ) -> None:
        self.panel_focus_memory[panel_name] = {"row": row_index, "col": column}

    def _get_panel_focus_memory(self, panel_name: str) -> Optional[Dict[str, Any]]:
        return self.panel_focus_memory.get(panel_name)

    # Navigation target getters
    def _get_security_plugin_target(self):
        """Get the target widget for security plugins section (remembered or first)."""
        from ...widgets.plugin_table import PluginTableWidget

        panel_name = "global_security"
        try:
            security_widget = self.query_one(
                "#global_security_widget", PluginTableWidget
            )
        except Exception:
            return None
        # Try row/column memory first
        mem = self._get_panel_focus_memory(panel_name)
        if mem:
            w = self._resolve_widget_by_row_col(
                security_widget, mem.get("row", 0), mem.get("col", "checkbox")
            )
            if w and getattr(w, "can_focus", False):
                return w
        # Fallback to first checkbox
        try:
            cbs = list(security_widget.query("ASCIICheckbox"))
            if not cbs:
                cbs = [w for w in security_widget.query("*") if self._is_checkbox(w)]
            return cbs[0] if cbs else None
        except Exception:
            return None

    def _get_auditing_plugin_target(self):
        """Get the target widget for auditing plugins section (remembered or first)."""
        from ...widgets.plugin_table import PluginTableWidget

        panel_name = "global_auditing"
        try:
            auditing_widget = self.query_one(
                "#global_auditing_widget", PluginTableWidget
            )
        except Exception:
            return None
        # Try row/column memory first
        mem = self._get_panel_focus_memory(panel_name)
        if mem:
            w = self._resolve_widget_by_row_col(
                auditing_widget, mem.get("row", 0), mem.get("col", "checkbox")
            )
            if w and getattr(w, "can_focus", False):
                return w
        # Fallback to first checkbox
        try:
            cbs = list(auditing_widget.query("ASCIICheckbox"))
            if not cbs:
                cbs = [w for w in auditing_widget.query("*") if self._is_checkbox(w)]
            return cbs[0] if cbs else None
        except Exception:
            return None

    def _get_servers_list_target(self):
        """Get the target widget for servers list (remembered or ListView itself)."""
        container_name = "servers_list"

        # For ListView widgets, we remember the ListView itself since it handles internal focus
        if container_name in self.container_focus_memory:
            remembered_widget = self.container_focus_memory[container_name]
            if remembered_widget and getattr(remembered_widget, "can_focus", False):
                return remembered_widget

        # Fall back to the ListView
        try:
            return self.query_one("#servers_list", ListView)
        except (KeyError, AttributeError):
            return None

    def _get_server_details_target(self):
        """Get the target widget for server details section (remembered or first)."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        container_name = "server_details"

        # Try to return remembered widget first
        if container_name in self.container_focus_memory:
            remembered_widget = self.container_focus_memory[container_name]
            if logger:
                logger.log_event(
                    "NAV_SERVER_DETAILS_MEMORY",
                    screen=self,
                    context={
                        "has_widget": remembered_widget is not None,
                        "can_focus": (
                            getattr(remembered_widget, "can_focus", False)
                            if remembered_widget
                            else False
                        ),
                        "widget_type": (
                            remembered_widget.__class__.__name__
                            if remembered_widget
                            else None
                        ),
                        "widget_id": (
                            remembered_widget.id
                            if remembered_widget and hasattr(remembered_widget, "id")
                            else None
                        ),
                    },
                )
            if remembered_widget and getattr(remembered_widget, "can_focus", False):
                return remembered_widget

        # Fall back to first focusable widget
        try:
            # First check server_info panel (contains server name input, etc.)
            info_container = self.query_one("#server_info")
            info_widgets = list(info_container.query("*"))
            info_focusable = [
                w
                for w in info_widgets
                if getattr(w, "can_focus", False) and not getattr(w, "disabled", False)
            ]

            if info_focusable:
                if logger:
                    logger.log_event(
                        "NAV_SERVER_INFO_TARGET",
                        screen=self,
                        context={
                            "focusable_count": len(info_focusable),
                            "target_widget": info_focusable[0].__class__.__name__,
                            "target_id": (
                                info_focusable[0].id
                                if hasattr(info_focusable[0], "id")
                                else None
                            ),
                        },
                    )
                return info_focusable[0]

            # Fallback to server_plugins_display panel
            details_container = self.query_one("#server_plugins_display")
            all_widgets = list(details_container.query("*"))
            focusable_widgets = [
                w for w in all_widgets
                if getattr(w, "can_focus", False)
                and not getattr(w, "disabled", False)
            ]

            if logger:
                logger.log_event(
                    "NAV_SERVER_DETAILS_SEARCH",
                    screen=self,
                    context={
                        "total_widgets": len(all_widgets),
                        "focusable_count": len(focusable_widgets),
                        "focusable_types": [
                            (w.__class__.__name__, w.id if hasattr(w, "id") else None)
                            for w in focusable_widgets[:10]
                        ],
                        "container_children": len(details_container.children),
                        "container_classes": (
                            details_container.classes
                            if hasattr(details_container, "classes")
                            else None
                        ),
                    },
                )

            return focusable_widgets[0] if focusable_widgets else None
        except (KeyError, AttributeError) as e:
            if logger:
                logger.log_event(
                    "NAV_SERVER_DETAILS_ERROR",
                    screen=self,
                    context={"error": str(e), "error_type": type(e).__name__},
                )
            return None
