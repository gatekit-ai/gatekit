"""Base ConfigEditorScreen class with core functionality."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.events import Focus, Resize
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static, ListView, Input

from gatekit.config.models import ProxyConfig
from gatekit.plugins.manager import PluginManager
from gatekit.tui.widgets.plugin_table import PluginTableWidget
from gatekit.tui.constants import GLOBAL_SCOPE
from gatekit.tui.utils.mcp_handshake import handshake_upstream
from gatekit.tui.utils.terminal_compat import lacks_enhanced_keyboard_protocol

# Import all mixins
from .navigation import NavigationMixin
from .config_persistence import ConfigPersistenceMixin
from .plugin_rendering import PluginRenderingMixin
from .server_management import ServerManagementMixin
from .plugin_actions import PluginActionsMixin
from gatekit.tui.widgets.plugin_table import PluginActionClick, PluginToggle

logger = logging.getLogger(__name__)

# Traditional VT100/ANSI terminals can't distinguish Ctrl+S from Ctrl+Shift+S
# because both generate the same control character (0x13). This affects:
# - Windows legacy terminals (cmd.exe, PowerShell without VT support)
# - SSH sessions (can't detect client terminal capabilities)
# - macOS Terminal.app (no Kitty keyboard protocol support)
#
# Modern terminals (iTerm2, Ghostty, Kitty, WezTerm) support enhanced keyboard
# protocols that properly encode modifier keys. Use F12 as fallback for
# terminals that lack this support.
_SAVE_AS_KEY = "f12" if lacks_enhanced_keyboard_protocol() else "ctrl+shift+s"


@dataclass(frozen=True)
class PluginModalTarget:
    """Descriptor for opening a plugin configuration modal on start."""

    plugin_type: str
    handler: str
    scope: Optional[str] = None


class ConfigEditorScreen(
    NavigationMixin,
    ConfigPersistenceMixin,
    PluginRenderingMixin,
    ServerManagementMixin,
    PluginActionsMixin,
    Screen,
):
    """Main configuration editor screen with horizontal split layout."""

    CSS = """
    ConfigEditorScreen {
        background: $surface;
    }

    .global-plugins-section {
        width: 100%;  /* Fill screen width */
        border: solid $primary;
    }

    .global-panes-container {
        width: 100%;  /* Fill section width */
        align: left top;
    }

    .global-security-pane {
        width: 50%;
        border-right: solid $secondary;
    }

    .global-auditing-pane {
        width: 50%;
    }
    
    .global-pane-title {
        background: $secondary;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }
    
    .global-pane-content {
        /* Height will be set dynamically in code based on plugin count */
        width: 100%;  /* Fill parent pane */
        padding: 0 1;  /* Only left/right padding */
        margin-top: 1;  /* Use margin instead of padding for spacing */
        margin-bottom: 1;  /* Bottom margin for aesthetics */
        align: left top;
        overflow-y: auto;
    }
    
    .server-management-section {
        height: 1fr;
        min-height: 0;
        border: solid $primary;
    }

    .server-panes-container {
        height: 1fr;
        min-height: 0;
    }

    .server-list-pane {
        width: 30%;
        border-right: solid $primary;
    }

    .server-details-pane {
        width: 70%;
        padding: 1;
        height: 1fr;
        min-height: 0;
        overflow-y: auto;
    }

    .server-info {
    /* Keep this panel to content height; no flex growth */
    height: auto;
    min-height: 0;
    padding: 0 0 0 0;  /* 1 line bottom padding only */
    margin-bottom: 1;  /* visual gap below panel */
    }

    /* Make info labels fill the available width so ellipsis can apply */
    .server-info Label, .server-info Static {
        width: 100%;
    }

    /* Server label in horizontal layout with input */
    .server-info Horizontal > .server-label {
        width: 20;
        min-width: 20;
        margin: 0 1 0 0;
        content-align: right middle;
        color: $text;
        text-style: bold;
    }

    /* Server alias input in horizontal layout */
    .server-info Horizontal > Input {
        width: 1fr;
        scrollbar-size-horizontal: 0;
    }

    .server-title {
        text-style: bold;
    }

    .server-helper {
        color: $warning;
        padding-left: 2;
    }

    #server_plugins_display {
        width: auto;
        margin-top: 1;
        height: auto;
        min-height: 0;
    }

    .servers-header {
        text-style: bold;
        border-bottom: solid $secondary;
    }

    .server-buttons {
        margin-top: 1;
        align: center middle;
    }

    .hidden {
        display: none;
    }

    #remove_server_container {
        padding: 0;
        height: auto;
        min-height: 0;
        align: left top;
    }

    #remove_server_container Button {
        width: auto;
    }
    
    .pane-header {
        height: 1;
        background: $secondary;
        color: $text;
        padding: 0 1;
        layout: horizontal;
        align: left middle;
    }

    .pane-header > .pane-title {
        text-style: bold;
        content-align: left middle;
        color: $text;
        margin-right: 1;
        width: 1fr;
    }

    .pane-header-button {
        height: 1;
        min-height: 1;
        min-width: 6;
        width: auto;
        padding: 0 1;
        border: none;
        background: $primary;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }

    .pane-header-button:hover,
    .pane-header-button:focus {
        background: $primary;
        color: $background;
    }

    .other-pane-title {
        content-align: center middle;
        text-style: bold;
    }
    
    .pane-content {
        height: 1fr;
        padding: 1;
    }
    
    .plugin-item {
        height: 1;
        margin-bottom: 1;
        padding: 0 1;
    }
    
    .plugin-item:hover {
        background: $primary;
        color: $background;
    }
    
    .plugin-item:focus {
        background: $primary;
        color: $background;
    }
    
    .plugin-status-active {
        color: $success;
        text-style: bold;
    }
    
    .plugin-status-disabled {
        color: $error;
    }
    
    .plugin-status-available {
        color: $text-muted;
    }
    
    .plugin-section-header {
        height: 1;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        padding: 0 1;
    }

    Button {
        margin: 0 1;
    }

    Button:hover {
        background: $primary;
        color: $background;
    }

    .plugin-actions {
        height: 1;
        align: left middle;
    }

    .plugin-actions Button {
        height: 1;
        margin: 0 1 0 0;
    }

    .plugin-row {
        margin-bottom: 1;
        align: left middle;
    }

    .debug-status {
        dock: bottom;
        height: 1;
        background: $primary-background-darken-2;
        color: $text-muted;
        text-align: center;
        padding: 0 1;
    }

    .plugin-inheritance {
        color: $text-muted;
        padding-left: 2;
    }

    /* DataTable styling for plugin tables */
    DataTable {
        height: auto;
        min-height: 5;  /* Header + 3 rows minimum */
        max-height: 15;  /* Prevent excessive height */
        margin: 0 1 1 1;
        border: solid $secondary;
    }

    DataTable:focus-within {
        border: solid $accent;
    }

    /* Empty state styling */
    .empty-state-message {
        height: 5;
        content-align: center middle;
        color: $text-muted;
        text-style: italic;
        margin: 1;
    }

    /* Scroll container for plugin rows (like global plugins) */
    .plugin-scroll {
        height: auto;
        max-height: 10;
        overflow-y: auto;
        margin: 0;
        padding: 0;
        border: none;
    }

    /* Truncate overflowing text for Labels and Statics with an ellipsis */
    Label, Static {
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    /* Hide blurred highlight in servers list when unfocused */
    #servers_list > ListItem.-highlight {
        background: transparent;
    }

    #servers_list:focus > ListItem.-highlight {
        background: $block-cursor-background;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save_config", "Save", priority=True),
        Binding(_SAVE_AS_KEY, "save_config_as", "Save As", priority=True),
        Binding("tab", "navigate_next", "Next Section", priority=True, show=False),
        Binding("shift+tab", "navigate_previous", "Previous Section", priority=True, show=False),
        # Up/Down are priority so we can manage boundary transitions; we pass through to widgets
        Binding("down", "navigate_down", "Next Item", priority=True, show=False),
        Binding("up", "navigate_up", "Previous Item", priority=True, show=False),
        Binding("right", "navigate_right", "Navigate Right", priority=True, show=False),
        Binding("left", "navigate_left", "Navigate Left", priority=True, show=False),
        Binding(
            "ctrl+shift+d",
            "debug_state_dump",
            "Debug State Dump",
            priority=True,
            show=False,
        ),
        Binding("escape", "quit", "Quit", priority=True, show=False),
        # Note: Ctrl+Q is also bound to quit at App level, but we provide action_quit() here for escape
    ]

    def __init__(
        self,
        config_file_path: Optional[Path],
        loaded_config: ProxyConfig,
        initial_plugin_modal: Optional[PluginModalTarget] = None,
    ):
        """Initialize the configuration editor.

        Args:
            config_file_path: Path to the configuration file, or None for new documents
            loaded_config: Loaded and validated configuration
            initial_plugin_modal: Optional plugin modal to open on startup
        """
        super().__init__()
        # Core state
        self.config_file_path = config_file_path
        self.config = loaded_config
        self.plugin_manager = None
        self.available_handlers = {}
        self.server_identity_map: Dict[str, str] = {}
        self.server_tool_map: Dict[str, Dict[str, Any]] = {}
        self._identity_test_status: Dict[str, Dict[str, Optional[str]]] = {}
        self._pending_command_cache: Dict[str, str] = {}
        self.selected_server = None
        self.selected_plugin = None
        self._identity_discovery_attempted: set[str] = set()
        self._tool_discovery_attempted: set[str] = set()
        self._initial_plugin_modal = initial_plugin_modal
        self._initial_plugin_modal_triggered = False

        # Concurrency safety
        self._save_lock = asyncio.Lock()

        # Override stash for preserving custom configurations during disable/enable cycles
        # This is an EPHEMERAL in-memory cache that does NOT persist across app sessions.
        #
        # Lifecycle:
        # 1. When disabling a server override with custom config, we stash the config here
        # 2. When re-enabling, we restore the stashed config if available
        # 3. Stash is cleared after successful re-enable
        # 4. If save fails during enable, stash remains (config was already reverted)
        #
        # Key format: (server_name, plugin_type, handler_name)
        # Value format: {'config': {...custom config...}, 'priority': int}
        self._override_stash: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        # Navigation state
        self.navigation_containers = []
        self.current_container_index = 0
        # Remember last focused widget in each container
        self.container_focus_memory = {}
        # Panel-focused memory to store row/column for plugin panels
        self.panel_focus_memory = {}

        # Collision guard for sanitized handler names
        # Maps sanitized name to (original_name, plugin_type) to detect collisions
        self._sanitized_handler_map: Dict[str, tuple[str, str]] = (
            {}
        )  # sanitized -> (original, type)

        # DataTable plugin row model and sort state
        self._plugin_row_model: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._table_sort_state: Dict[str, Tuple[str, bool]] = (
            {}
        )  # table_id -> (column, is_descending)

        # Dirty state tracking - new documents start dirty, existing documents start clean
        if self.config_file_path is None:
            # New document - always dirty until first save
            self._config_dirty = True
            self._last_saved_config_hash = ""  # No saved state to compare against
        else:
            # Existing document - start clean
            self._config_dirty = False
            self._last_saved_config_hash = self._compute_config_hash()

    @property
    def is_new_document(self) -> bool:
        """True if this is a new unsaved document (no file path yet)."""
        return self.config_file_path is None

    def _get_key_display(self, action: str) -> str:
        """Get user-friendly display text for a key binding.

        Args:
            action: Action name (e.g., "save_config")

        Returns:
            Formatted key display (e.g., "Ctrl+S")
        """
        for binding in self.BINDINGS:
            if binding.action == action:
                # Format key for display: "ctrl+s" -> "Ctrl+S"
                key = binding.key
                if "+" in key:
                    parts = key.split("+")
                    return "+".join(part.capitalize() for part in parts)
                return key.capitalize()
        return ""

    def compose(self) -> ComposeResult:
        """Compose the screen layout."""
        yield Header()

        # Global plugins section (top)
        with Container(classes="global-plugins-section"):
            with Horizontal(classes="global-panes-container"):
                # Left pane: Global Security
                with Vertical(classes="global-security-pane"):
                    yield Static(
                        "Global Middleware and Security Plugins (Applies to All MCP Servers)",
                        id="global_security_title",
                        classes="global-pane-title",
                    )
                    with Container(classes="global-pane-content"):
                        yield PluginTableWidget(
                            plugin_type="security",
                            server_name=GLOBAL_SCOPE,
                            plugins_data=[],  # Will be populated later
                            show_priority=False,  # Global plugins don't show priority
                            show_header=False,    # Cleaner look without header
                            id="global_security_widget"
                        )

                # Right pane: Global Auditing
                with Vertical(classes="global-auditing-pane"):
                    yield Static("Auditing Plugins", classes="global-pane-title")
                    with Container(classes="global-pane-content"):
                        yield PluginTableWidget(
                            plugin_type="auditing",
                            server_name=GLOBAL_SCOPE,
                            plugins_data=[],
                            show_priority=False,
                            show_header=False,
                            id="global_auditing_widget"
                        )

        # Server management section (bottom) - two-panel layout
        with Container(classes="server-management-section"):
            with Horizontal(classes="server-panes-container"):
                # Left pane: Simple server list
                with Vertical(classes="server-list-pane"):
                    with Horizontal(id="servers_header", classes="pane-header"):
                        yield Static(
                            "MCP Servers",
                            id="servers_title",
                            classes="pane-title",
                        )
                        yield Button(
                            "+ Add", id="add_server", classes="pane-header-button"
                        )
                    with Container(classes="pane-content"):
                        # IMPORTANT: Keep ListView pure (only selectable items). Do not mount headers/buttons in the list.
                        # See docs/visual-configuration-interface/tui-developer-guidelines.md
                        yield ListView(id="servers_list")

                # Right pane: Combined details and plugins
                with VerticalScroll(
                    id="server_details_scroll", classes="server-details-pane"
                ):
                    # SERVER INFO PANEL - Top panel showing server details
                    # User refers to this as: "server info panel"
                    # Shows: Server alias, transport type, command, URL
                    yield Container(id="server_info", classes="server-info")

                    # SERVER PLUGINS PANEL - Bottom scrollable panel showing plugin configuration
                    # User refers to this as: "server plugins panel" or "server plugin panel"
                    # Shows: Which plugins are enabled/disabled for the selected server
                    # Note: PluginTableWidget provides its own scrolling
                    yield Container(
                        id="server_plugins_display", classes="server-plugins-container"
                    )

                    with Horizontal(
                        id="remove_server_container", classes="server-buttons hidden"
                    ):
                        yield Button(
                            "Remove Server…",
                            id="remove_server",
                            variant="error",
                            disabled=True,
                        )

        # Debug status line
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger and logger.enabled:
            yield Static(
                f"🔍 Debug: {logger.log_path}",
                id="debug_status",
                classes="debug-status",
            )

        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the screen when mounted."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_widget_lifecycle(
                "mount", screen=self, config_path=str(self.config_file_path)
            )

        # Update header with filename and dirty state
        self._update_header()

        await self._initialize_plugin_system()

        # Setup navigation containers early to ensure they exist even if population fails
        self._setup_navigation_containers()

        await self._populate_global_plugins()
        await self._populate_servers_list()
        await self._populate_server_details()

        # Set initial focus to the first checkbox in Global Security widget
        # Use call_after_refresh to ensure this happens after the UI is fully rendered
        self.call_after_refresh(self._set_initial_focus_sync)
        # Also ensure servers list has a valid highlight once rendered
        try:
            # Bound method defined in ServerManagementMixin
            self.call_after_refresh(self._ensure_initial_server_highlight)
        except Exception:
            pass

        # Update title based on initial size
        self.call_after_refresh(lambda: self.on_resize(None))

        # Begin background discovery of upstream handshake identities
        self._run_worker(self._discover_server_identities())

        if self._initial_plugin_modal:
            self.call_after_refresh(self._schedule_initial_plugin_modal)

    async def _initialize_plugin_system(self) -> None:
        """Initialize plugin manager and discover available policies."""
        try:
            # Create a plugin manager to discover available policies
            plugins_config = {}
            if self.config.plugins:
                plugins_config = self.config.plugins.to_dict()

            # Use config file's directory or cwd for new documents
            config_dir = self.config_file_path.parent if self.config_file_path else Path.cwd()
            self.plugin_manager = PluginManager(
                plugins_config, config_directory=config_dir
            )
            # IMPORTANT: Load plugins so get_plugins_for_upstream() returns data
            # Without this, PluginManager._initialized remains False and the
            # server plugins panel will appear empty.
            await self.plugin_manager.load_plugins()

            # Discover available handlers and refresh server identity mapping
            self._refresh_discovery_state()

            # Launch background identity discovery (handles new/updating servers)
            self._run_worker(self._discover_server_identities())

        except Exception:
            # Handle plugin system initialization errors gracefully
            self.available_handlers = {
                "security": {},
                "middleware": {},
                "auditing": {},
            }
            self.server_identity_map = {}

    def _get_server_identity(self, scope: Optional[str]) -> Optional[str]:
        """Resolve the MCP-reported server name for the given scope."""
        if not scope or scope == "_global":
            return None
        return self.server_identity_map.get(scope)

    def _get_contextual_handlers(self, plugin_type: str, scope: str) -> Dict[str, type]:
        """Fetch handlers filtered for the current context using the plugin manager."""
        server_identity = self._get_server_identity(scope)
        server_alias = None if scope == "_global" else scope

        if self.plugin_manager and hasattr(
            self.plugin_manager, "get_available_handlers"
        ):
            try:
                handlers = self.plugin_manager.get_available_handlers(
                    plugin_type,
                    scope=scope,
                    server_identity=server_identity,
                    server_alias=server_alias,
                )
                if isinstance(handlers, dict):
                    return handlers
            except Exception:
                pass

        # Fallback for tests or when plugin_manager is unavailable: reuse the
        # central compatibility logic against the cached handler list
        fallback_handlers = {}
        available = self.available_handlers.get(plugin_type, {})

        # Reuse PluginManager filtering logic for consistency
        temp_manager = PluginManager({})
        for handler_name, handler_class in available.items():
            if temp_manager._handler_is_available_for_scope(
                handler_class,
                scope=scope,
                server_identity=server_identity,
                server_alias=server_alias,
            ):
                fallback_handlers[handler_name] = handler_class

        return fallback_handlers

    def _refresh_server_identity_map(self) -> None:
        """Rebuild mapping of upstream aliases to MCP handshake identities."""
        identity_map: Dict[str, str] = {}
        if getattr(self.config, "upstreams", None):
            for upstream in self.config.upstreams:
                identity = getattr(upstream, "server_identity", None)
                if identity:
                    identity_map[upstream.name] = identity

        self.server_identity_map = identity_map

    def _refresh_discovery_state(self) -> None:
        """Refresh handler discovery caches and server identity mapping."""
        if self.plugin_manager:
            try:
                self.available_handlers = {
                    "security": self.plugin_manager.get_available_handlers("security"),
                    "middleware": self.plugin_manager.get_available_handlers("middleware"),
                    "auditing": self.plugin_manager.get_available_handlers("auditing"),
                }
            except Exception:
                self.available_handlers = {
                    "security": {},
                    "middleware": {},
                    "auditing": {},
                }
        else:
            self.available_handlers = {"security": {}, "middleware": {}, "auditing": {}}

        self._refresh_server_identity_map()

    async def _discover_server_identities(self) -> None:
        """Probe upstream servers asynchronously to learn their handshake identities."""
        upstreams: List = getattr(self.config, "upstreams", []) or []
        if not upstreams:
            return

        discovery_tasks = []
        for upstream in upstreams:
            alias = getattr(upstream, "name", None)
            if not alias:
                continue

            current_identity = getattr(upstream, "server_identity", None)
            if current_identity:
                self.server_identity_map[alias] = current_identity
                if alias in self.server_tool_map:
                    continue

            if alias in self._identity_discovery_attempted:
                continue

            if getattr(upstream, "is_draft", False):
                continue

            if upstream.transport != "stdio" or not upstream.command:
                self._identity_discovery_attempted.add(alias)
                self._tool_discovery_attempted.add(alias)
                if alias not in self.server_tool_map:
                    self.server_tool_map[alias] = {
                        "tools": [],
                        "last_refreshed": None,
                        "status": "unsupported",
                        "message": "Tool discovery available only for stdio transports with launch commands.",
                    }
                continue

            self._identity_discovery_attempted.add(alias)
            self._tool_discovery_attempted.add(alias)
            discovery_tasks.append(self._discover_identity_for_upstream(upstream))

        if discovery_tasks:
            await asyncio.gather(*discovery_tasks, return_exceptions=True)

    async def _discover_identity_for_upstream(self, upstream) -> None:
        """Discover handshake identity and tool catalog for a single upstream."""
        alias = getattr(upstream, "name", "")
        try:
            identity, tool_payload = await self._handshake_upstream(upstream)
        except Exception as exc:  # Defensive: never bubble into UI loop
            logger.debug(
                "Identity discovery failed for upstream %s: %s",
                alias or "<unknown>",
                exc,
            )
            if alias:
                self.server_tool_map[alias] = {
                    "tools": [],
                    "last_refreshed": datetime.now(timezone.utc),
                    "status": "error",
                    "message": str(exc),
                }
            return

        if alias and tool_payload is not None:
            logger.debug(
                "Tool discovery complete for %s: status=%s count=%s sample=%s",
                alias,
                tool_payload.get("status"),
                len(tool_payload.get("tools") or []),
                (tool_payload.get("tools") or [])[:1],
            )
            self.server_tool_map[alias] = {
                "tools": tool_payload.get("tools", []),
                "last_refreshed": datetime.now(timezone.utc),
                "status": tool_payload.get("status", "ok"),
                "message": tool_payload.get("message"),
            }
            
            # Notify any open PluginConfigModal to update with new discovery data
            self._notify_modal_discovery_update(alias)
            
        elif alias and alias not in self.server_tool_map:
            self.server_tool_map[alias] = {
                "tools": [],
                "last_refreshed": datetime.now(timezone.utc),
                "status": "unavailable",
                "message": "Tool discovery did not return data.",
            }

        if not identity:
            return

        existing = getattr(upstream, "server_identity", None)
        if existing == identity:
            self.server_identity_map[alias] = identity
            # Still mark as success so button shows "Refresh"
            self._set_identity_status(alias, "success")
            return

        upstream.server_identity = identity
        self.server_identity_map[alias] = identity

        # Mark identity status as success so the Connect button shows "Refresh"
        self._set_identity_status(alias, "success")

        # Refresh handler discovery so scope filtering incorporates the new identity
        self._refresh_discovery_state()

        # If user is viewing this server, refresh plugin table for immediate feedback
        if self.selected_server == alias:
            try:
                await self._render_server_plugin_groups()
            except Exception as exc:
                logger.debug("Failed to refresh plugin table for %s: %s", alias, exc)

            def _update_identity_field() -> None:
                try:
                    identity_input = self.query_one("#server_identity_input", Input)
                    identity_input.value = identity
                    identity_input.refresh()
                except Exception:
                    pass

            self.call_after_refresh(_update_identity_field)

    def _notify_modal_discovery_update(self, alias: str) -> None:
        """Notify any open PluginConfigModal about updated discovery data."""
        from gatekit.tui.screens.plugin_config.modal import PluginConfigModal
        
        # Check if there's a PluginConfigModal in the screen stack
        for screen in self.app.screen_stack:
            if isinstance(screen, PluginConfigModal):
                # Check if this modal is for the tool_manager plugin for this server
                if self.selected_server == alias:
                    discovery_data = self.server_tool_map.get(alias)
                    if discovery_data:
                        screen.update_discovery(discovery_data)
                        logger.debug(
                            "Updated PluginConfigModal with discovery for %s: %d tools",
                            alias,
                            len(discovery_data.get("tools", [])),
                        )

    async def _handshake_upstream(self, upstream) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Perform a lightweight MCP handshake and fetch tool metadata."""
        if upstream.transport != "stdio" or not upstream.command:
            return None, None

        # Use shared handshake utility
        # 30s timeout allows for first-run npx/uvx package downloads
        identity, tools_payload = await handshake_upstream(
            command=upstream.command,
            timeout=30.0,
        )

        if identity:
            logger.debug(
                "Discovered server identity '%s' for upstream %s",
                identity,
                upstream.name,
            )

        return identity, tools_payload

    def _set_initial_focus_sync(self) -> None:
        """Synchronous version of _set_initial_focus for use with call_after_refresh."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        if logger:
            logger.log_widget_lifecycle(
                "initial_focus_attempt",
                screen=self,
                action="starting_set_initial_focus_sync",
            )

        try:
            # Get the first checkbox in the Global Security widget
            target_widget = self._get_security_plugin_target()

            if logger:
                logger.log_widget_lifecycle(
                    "initial_focus_target",
                    screen=self,
                    target_found=target_widget is not None,
                    target_can_focus=(
                        getattr(target_widget, "can_focus", False)
                        if target_widget
                        else False
                    ),
                )

            if target_widget and getattr(target_widget, "can_focus", False):
                target_widget.focus()

                if logger:
                    logger.log_focus_change(
                        old_widget=None,
                        new_widget=target_widget,
                        screen=self,
                        reason="initial_focus_on_mount",
                    )
            else:
                # Fallback: try to focus any available checkbox in global security
                try:
                    security_widget = self.query_one(
                        "#global_security_widget", PluginTableWidget
                    )
                    checkboxes = security_widget.query("ASCIICheckbox")

                    if logger:
                        logger.log_widget_lifecycle(
                            "fallback_attempt",
                            screen=self,
                            checkboxes_found=len(checkboxes) if checkboxes else 0,
                        )

                    if checkboxes:
                        first_checkbox = checkboxes.first()
                        first_checkbox.focus()

                        if logger:
                            logger.log_focus_change(
                                old_widget=None,
                                new_widget=first_checkbox,
                                screen=self,
                                reason="fallback_initial_focus",
                            )
                except Exception as e:
                    if logger:
                        logger.log_widget_lifecycle(
                            "fallback_error", screen=self, error=f"fallback failed: {e}"
                        )

                    # If all else fails, try to focus the global security widget itself
                    try:
                        security_widget = self.query_one(
                            "#global_security_widget", PluginTableWidget
                        )
                        security_widget.focus()

                        if logger:
                            logger.log_focus_change(
                                old_widget=None,
                                new_widget=security_widget,
                                screen=self,
                                reason="container_fallback_focus",
                            )
                    except Exception as e2:
                        # Final fallback: let Textual handle focus
                        if logger:
                            logger.log_widget_lifecycle(
                                "focus_error",
                                screen=self,
                                error=f"all fallbacks failed: {e2}",
                            )

        except Exception as e:
            # Log error but don't crash
            if logger:
                logger.log_widget_lifecycle(
                    "focus_error",
                    screen=self,
                    error=f"_set_initial_focus_sync failed: {e}",
                )

    def on_resize(self, event: Resize) -> None:
        """Handle resize events to update the security panel title based on available width."""
        try:
            # Get the title widget
            title_widget = self.query_one("#global_security_title", Static)

            # Check the width of the global security pane
            # The pane is set to 1fr (50% of horizontal space)
            # So we use half of the total width
            available_width = self.size.width // 2 if self.size else 80

            # Choose title based on available width
            # Full title is ~60 chars, so we need at least 70 chars to display comfortably
            if available_width >= 70:
                title_widget.update(
                    "Global Middleware and Security Plugins (Applies to All MCP Servers)"
                )
            else:
                title_widget.update("Global Middleware and Security Plugins")

        except Exception:
            # Silently ignore any errors during resize
            pass

    def on_descendant_focus(self, event: Focus) -> None:
        """Catch focus events from any descendant widget and track them for navigation memory."""
        focused_widget = event.widget

        # Debug logging for focus events
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            # Get previously focused widget if possible
            old_widget = (
                getattr(self.app, "focused", None) if hasattr(self, "app") else None
            )
            logger.log_focus_change(
                old_widget, focused_widget, screen=self, reason="descendant_focus"
            )

        # Track focus for navigation memory
        self._track_widget_focus(focused_widget)

    def action_debug_state_dump(self) -> None:
        """Trigger a debug state dump for this screen."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.dump_state(self)

    def _run_worker(self, coro):
        """Helper to schedule async work via Textual's worker system."""
        try:
            return self.run_worker(coro, exit_on_error=False)
        except Exception:
            coro.close()  # Clean up orphaned coroutine to prevent "never awaited" warning
            return None

    def _schedule_initial_plugin_modal(self) -> None:
        """Schedule opening of an initial plugin modal, if requested."""
        if self._initial_plugin_modal_triggered:
            return
        if not self._initial_plugin_modal:
            return
        self._initial_plugin_modal_triggered = True
        self._run_worker(self._open_initial_plugin_modal())

    async def _open_initial_plugin_modal(self) -> None:
        """Attempt to open a plugin configuration modal based on startup parameters."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()

        try:
            target = self._initial_plugin_modal
            if not target:
                return

            handler_map = self.available_handlers.get(target.plugin_type, {})
            handler_class = handler_map.get(target.handler)
            if not handler_class:
                if logger:
                    logger.log_event(
                        "initial_plugin_modal_skipped",
                        screen=self,
                        context={
                            "reason": "handler_unavailable",
                            "plugin_type": target.plugin_type,
                            "handler": target.handler,
                        },
                    )
                return

            upstreams = list(getattr(self.config, "upstreams", []) or [])
            requested_scope = target.scope

            if not requested_scope:
                display_scope = getattr(handler_class, "DISPLAY_SCOPE", "")
                if display_scope == "server_aware":
                    requested_scope = upstreams[0].name if upstreams else None
                else:
                    requested_scope = "_global"

            if not requested_scope:
                if logger:
                    logger.log_event(
                        "initial_plugin_modal_skipped",
                        screen=self,
                        context={
                            "reason": "no_scope_available",
                            "plugin_type": target.plugin_type,
                            "handler": target.handler,
                        },
                    )
                return

            if requested_scope != "_global":
                available_aliases = {u.name for u in upstreams}
                if requested_scope not in available_aliases:
                    if target.scope:
                        if logger:
                            logger.log_event(
                                "initial_plugin_modal_skipped",
                                screen=self,
                                context={
                                    "reason": "unknown_scope",
                                    "requested_scope": target.scope,
                                },
                            )
                        return
                    elif upstreams:
                        requested_scope = upstreams[0].name
                    else:
                        if logger:
                            logger.log_event(
                                "initial_plugin_modal_skipped",
                                screen=self,
                                context={"reason": "no_upstreams"},
                            )
                        return

                servers_list = None
                for _ in range(10):
                    try:
                        servers_list = self.query_one("#servers_list", ListView)
                        break
                    except Exception:
                        await asyncio.sleep(0.05)

                if servers_list is not None:
                    target_item = None
                    for item in servers_list.children:
                        if getattr(item, "data_server_name", None) == requested_scope:
                            target_item = item
                            break

                    if target_item is not None:
                        await self._activate_server_item(target_item)
                    else:
                        self.selected_server = requested_scope
                        await self._populate_server_details()
                else:
                    self.selected_server = requested_scope
                    await self._populate_server_details()
            else:
                # Ensure global panels have been rendered
                await asyncio.sleep(0)

            scope_for_inheritance = (
                requested_scope if requested_scope else "_global"
            )
            inheritance_display, _, _ = self.get_plugin_inheritance(
                target.handler,
                target.plugin_type,
                scope_for_inheritance,
                None,
            )

            await self._handle_plugin_configure(
                target.handler,
                target.plugin_type,
                inheritance_display,
            )

            if logger:
                logger.log_event(
                    "initial_plugin_modal_opened",
                    screen=self,
                    context={
                        "plugin_type": target.plugin_type,
                        "handler": target.handler,
                        "scope": scope_for_inheritance,
                    },
                )
        except Exception as exc:
            if logger:
                logger.log_event(
                    "initial_plugin_modal_failed",
                    screen=self,
                    context={"error": str(exc)},
                )

    def action_quit(self) -> None:
        """Handle Quit action (Escape key or Ctrl+Q).

        Prompts for confirmation if there are unsaved changes.
        """
        # Run the actual quit logic in a worker since push_screen_wait requires it
        self.run_worker(self._quit_with_confirmation())

    async def _quit_with_confirmation(self) -> None:
        """Worker coroutine to quit with confirmation if needed."""
        # Check for unsaved changes
        if self._config_dirty:
            from ..simple_modals import ConfirmModal

            result = await self.app.push_screen_wait(
                ConfirmModal(
                    title="Unsaved Changes",
                    message="You have unsaved changes. Are you sure you want to quit?",
                    confirm_label="Quit",
                    cancel_label="Cancel",
                    confirm_variant="warning",
                )
            )

            if not result:
                # User chose to stay
                return

        # No unsaved changes or user confirmed - proceed with quit
        self.app.exit()

    # IMPORTANT: Register handler on the concrete screen class to ensure Textual
    # picks it up reliably (decorators on mixins may not be collected in some cases).
    @on(PluginActionClick)
    async def _config_editor_on_plugin_action_click(
        self, event: PluginActionClick
    ) -> None:
        """Forward PluginActionClick to the mixin implementation.

        This shim ensures the handler is registered on the concrete Screen class,
        avoiding any issues where @on on a base mixin class isn't collected.
        """
        # Immediate debug log to verify delivery to the screen-level shim
        try:
            from ...debug import get_debug_logger

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_ACTION_SHIM_RECEIVED",
                    screen=self,
                    context={
                        "handler": getattr(event, "handler", None),
                        "plugin_type": getattr(event, "plugin_type", None),
                        "action": getattr(event, "action", None),
                        "event_class": event.__class__.__name__,
                    },
                )
        except Exception:
            pass
        from .plugin_actions import PluginActionsMixin as _PAM

        await _PAM.on_plugin_action_click(self, event)

    @on(PluginToggle)
    async def _config_editor_on_plugin_toggle(
        self, event: PluginToggle
    ) -> None:
        """Forward PluginToggle to the mixin implementation.

        This shim ensures the handler is registered on the concrete Screen class,
        avoiding any issues where @on on a base mixin class isn't collected.
        """
        # Immediate debug log to verify delivery to the screen-level shim
        try:
            from ...debug import get_debug_logger

            _logger = get_debug_logger()
            if _logger:
                _logger.log_event(
                    "PLUGIN_TOGGLE_SHIM_RECEIVED",
                    screen=self,
                    context={
                        "handler": getattr(event, "handler", None),
                        "plugin_type": getattr(event, "plugin_type", None),
                        "enabled": getattr(event, "enabled", None),
                        "event_class": event.__class__.__name__,
                    },
                )
        except Exception:
            pass
        from .plugin_actions import PluginActionsMixin as _PAM

        await _PAM.on_plugin_toggle(self, event)

    # Server management button event handlers (shims to ensure proper registration)
    @on(Button.Pressed, "#add_server")
    async def _on_add_server_button(self, event: Button.Pressed) -> None:
        """Shim handler for add server button - forwards to mixin implementation."""
        await self.on_add_server_button(event)

    @on(Button.Pressed, "#remove_server")
    def _on_remove_server_button(self, event: Button.Pressed) -> None:
        """Shim handler for remove server button - forwards to mixin implementation."""
        self.on_remove_server_button(event)

    # Input event handlers for dynamically mounted widgets
    # IMPORTANT: These shims are required because @on decorators in mixin classes
    # don't work for widgets mounted dynamically via container.mount().
    # Textual's decorator registration happens at class composition time, but dynamic
    # widgets are mounted after composition. By defining these handlers on the concrete
    # Screen class, we ensure proper registration, then forward to mixin implementations.
    # See: docs/visual-configuration-interface/tui-developer-guidelines.md

    @on(Input.Submitted, "#server_name_input")
    async def _on_server_name_submitted_shim(self, event: Input.Submitted) -> None:
        """Shim handler for server name input - forwards to mixin implementation."""
        await self.on_server_name_submitted(event)

    @on(Input.Blurred, "#server_name_input")
    async def _on_server_name_blurred_shim(self, event: Input.Blurred) -> None:
        """Shim handler for server name input - forwards to mixin implementation."""
        await self.on_server_name_blurred(event)

    @on(Input.Submitted, "#server_command_input")
    async def _on_server_command_submitted_shim(self, event: Input.Submitted) -> None:
        """Shim handler for server command input - forwards to mixin implementation."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "SERVER_COMMAND_SUBMITTED_SHIM",
                screen=self,
                context={
                    "event_input_id": getattr(event.input, "id", None),
                    "event_value": event.value,
                    "event_sender": getattr(event, "sender", None),
                    "event_sender_id": getattr(event.sender, "id", None) if hasattr(event, "sender") else None,
                },
            )

        await self.on_server_command_submitted(event)

    @on(Input.Blurred, "#server_command_input")
    async def _on_server_command_blurred_shim(self, event: Input.Blurred) -> None:
        """Shim handler for server command input - forwards to mixin implementation."""
        await self.on_server_command_blurred(event)

    # ListView event handlers with debug logging to trace event flow
    @on(ListView.Selected)
    async def _debug_list_view_selected(self, event: ListView.Selected) -> None:
        """Debug shim to trace ListView.Selected events.

        Note: We only log here - do NOT forward to on_list_view_selected.
        Textual auto-discovers and calls on_list_view_selected via naming convention.
        Explicit forwarding would cause double invocation.
        """
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "BASE_SCREEN_LIST_VIEW_SELECTED",
                    screen=self,
                    context={
                        "event_type": "ListView.Selected",
                        "list_view_id": getattr(event.list_view, "id", None),
                        "item": str(event.item),
                    },
                )
        except Exception as e:
            print(f"Debug logging failed in base screen ListView.Selected: {e}")

    @on(ListView.Highlighted)
    async def _debug_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Debug shim to trace ListView.Highlighted events.

        Note: We only log here - do NOT forward to on_server_highlighted.
        The mixin's handler is registered via @on decorator and Textual will call it.
        Explicit forwarding would cause double invocation.
        """
        try:
            from ...debug import get_debug_logger

            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    "BASE_SCREEN_LIST_VIEW_HIGHLIGHTED",
                    screen=self,
                    context={
                        "event_type": "ListView.Highlighted",
                        "list_view_id": getattr(event.list_view, "id", None),
                        "item": str(event.item),
                    },
                )
        except Exception as e:
            print(f"Debug logging failed in base screen ListView.Highlighted: {e}")
