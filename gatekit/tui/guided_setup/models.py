"""Data models for guided setup - detected clients and servers."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from .migration_instructions import MigrationInstructions


class ClientType(str, Enum):
    """Supported MCP client types."""

    CLAUDE_DESKTOP = "claude_desktop"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    CURSOR = "cursor"
    WINDSURF = "windsurf"

    def display_name(self) -> str:
        """Get human-readable display name for the client."""
        return {
            ClientType.CLAUDE_DESKTOP: "Claude Desktop",
            ClientType.CLAUDE_CODE: "Claude Code",
            ClientType.CODEX: "Codex",
            ClientType.CURSOR: "Cursor",
            ClientType.WINDSURF: "Windsurf",
        }[self]


class TransportType(str, Enum):
    """MCP transport types."""

    STDIO = "stdio"  # command + args
    HTTP = "http"  # url-based (future support)
    SSE = "sse"  # Server-Sent Events (future support)


class ServerScope(str, Enum):
    """Scope where the server was configured (for Claude Code)."""

    USER = "user"  # ~/.claude.json top-level (available in all projects)
    PROJECT = "project"  # .mcp.json (shared via git)
    LOCAL = "local"  # ~/.claude.json project-specific section (private, per-project)


@dataclass
class DetectedServer:
    """Represents a detected MCP server from a client configuration.

    Attributes:
        name: Server name/identifier from the config (may be renamed during deduplication)
        transport: Transport type (stdio, http, etc.)
        command: Command to execute (for stdio transport) as list [cmd, arg1, arg2, ...]
        url: URL for HTTP/SSE transport (future)
        env: Environment variables for the server (with actual values)
        scope: Where the server was configured (for Claude Code only)
        project_path: Project path for servers from Claude Code projects section
        raw_config: Original config dict for debugging/advanced use
        original_name: Original name before deduplication renaming (for CLI removal commands)
    """

    name: str
    transport: TransportType
    command: Optional[List[str]] = None  # For stdio: [command, arg1, arg2, ...]
    url: Optional[str] = None  # For HTTP/SSE
    env: Optional[Dict[str, str]] = None  # Environment variables with actual values
    scope: Optional[ServerScope] = None  # For Claude Code scope tracking
    project_path: Optional[str] = None  # Project path for servers from projects section
    raw_config: Dict = field(default_factory=dict)  # Original config for reference
    original_name: Optional[str] = None  # Original name before deduplication renaming

    def __post_init__(self):
        """Validate server configuration after initialization."""
        # Ensure env is a dict if provided
        if self.env is None:
            self.env = {}

        # Validate transport-specific requirements
        if self.transport == TransportType.STDIO:
            if not self.command:
                raise ValueError(f"Server '{self.name}': stdio transport requires command")
        elif self.transport in (TransportType.HTTP, TransportType.SSE):
            if not self.url:
                raise ValueError(f"Server '{self.name}': {self.transport} transport requires url")

    def has_env_vars(self) -> bool:
        """Check if server has environment variables configured."""
        return bool(self.env)

    def is_stdio(self) -> bool:
        """Check if server uses stdio transport."""
        return self.transport == TransportType.STDIO

    def is_http_based(self) -> bool:
        """Check if server uses HTTP or SSE transport."""
        return self.transport in (TransportType.HTTP, TransportType.SSE)


@dataclass
class DetectedClient:
    """Represents a detected MCP client on the system.

    Attributes:
        client_type: Type of client (Claude Desktop, Claude Code, Codex)
        config_path: Absolute path to the config file
        servers: List of detected MCP servers in this client's config
        parse_errors: Any errors encountered during parsing (non-fatal)
        gatekit_config_path: Path to gatekit.yaml if client already uses Gatekit
    """

    client_type: ClientType
    config_path: Path
    servers: List[DetectedServer] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)
    gatekit_config_path: Optional[str] = None

    def __post_init__(self):
        """Ensure config_path is absolute."""
        self.config_path = self.config_path.resolve()

    def has_servers(self) -> bool:
        """Check if client has any servers configured."""
        return len(self.servers) > 0

    def has_errors(self) -> bool:
        """Check if there were any parse errors."""
        return len(self.parse_errors) > 0

    def has_gatekit(self) -> bool:
        """Check if client has Gatekit configured."""
        return self.gatekit_config_path is not None

    def display_name(self) -> str:
        """Get human-readable display name for the client."""
        return self.client_type.display_name()

    def get_stdio_servers(self) -> List[DetectedServer]:
        """Get only stdio servers (supported in MVP)."""
        return [s for s in self.servers if s.is_stdio()]

    def get_http_servers(self) -> List[DetectedServer]:
        """Get HTTP/SSE servers (future support)."""
        return [s for s in self.servers if s.is_http_based()]


class NavigationAction(Enum):
    """User navigation decision from a screen."""

    CONTINUE = "continue"  # Proceed to next screen
    BACK = "back"  # Return to previous screen
    CANCEL = "cancel"  # Abort wizard entirely


@dataclass
class ScreenResult:
    """Result returned by each wizard screen.

    Contract:
    - All screens MUST call dismiss(ScreenResult(...)) when transitioning
    - CONTINUE: User wants to proceed (state contains their selections)
    - BACK: User wants to go back (state contains preserved selections)
    - CANCEL: User wants to abort (state may be None)
    """

    action: NavigationAction
    state: Optional["GuidedSetupState"] = None


@dataclass
class DeduplicatedServer:
    """Represents a unique server after deduplication.

    Attributes:
        server: The detected server (may have renamed name)
        client_names: Display names of clients using this server
        is_shared: True if multiple clients use identical config
        was_renamed: True if name was changed due to conflict
        original_name: Original name before conflict resolution
    """

    server: DetectedServer
    client_names: List[str]  # e.g., ["Claude Desktop", "Codex"]
    is_shared: bool
    was_renamed: bool
    original_name: Optional[str] = None


@dataclass
class GuidedSetupState:
    """Wizard state that flows through all screens.

    Lifecycle (updated flow):
    1. ServerSelectionScreen: Populates detected_clients, deduplicated_servers, user modifies selected_server_names, sets config_path
    2. ClientSelectionScreen: User modifies selected_client_types, sets restore_dir, generate_restore,
       populates already_configured_clients; generates files and populates created_files, generation_errors, migration_instructions
    3. ClientSetupScreen: Displays interactive client setup instructions using migration_instructions and already_configured_clients
    4. SetupCompleteScreen: Displays final summary of configuration
    """

    # Populated by ServerSelectionScreen
    detected_clients: List[DetectedClient] = field(default_factory=list)
    deduplicated_servers: List[DeduplicatedServer] = field(default_factory=list)

    # User selections (modified by ServerSelectionScreen for servers, ClientSelectionScreen for clients)
    selected_server_names: Set[str] = field(default_factory=set)
    selected_client_types: Set[ClientType] = field(default_factory=set)

    # File paths (set by ServerSelectionScreen for config_path, ClientSelectionScreen for restore paths)
    config_path: Optional[Path] = None
    restore_dir: Optional[Path] = None
    generate_restore: bool = False

    # Clients already using Gatekit (populated by ConfigurationSummaryScreen)
    already_configured_clients: List[DetectedClient] = field(default_factory=list)

    # Results (populated by ConfigurationSummaryScreen during file generation)
    created_files: List[Path] = field(default_factory=list)
    generation_errors: List[str] = field(default_factory=list)
    migration_instructions: List["MigrationInstructions"] = field(default_factory=list)
    restore_script_paths: Dict[ClientType, Path] = field(default_factory=dict)  # Maps client type to restore script path

    def update_deduplicated_servers(
        self,
        new_servers: List[DeduplicatedServer],
        new_clients: List[DetectedClient],
    ) -> None:
        """Update after rescan, preserving user intent.

        Smart reconciliation:
        - Removes selections for servers/clients that no longer exist
        - Auto-selects NEWLY discovered servers/clients
        - Preserves user's intentional deselections
        - Updates server names in detected_clients to match renamed servers

        Example:
            Initial: A, B, C all selected
            User unchecks B
            Rescan adds D
            Result: A, C, D selected (B stays unchecked)
        """
        # Capture old state
        old_server_names = {s.server.name for s in self.deduplicated_servers}
        old_client_types = {c.client_type for c in self.detected_clients}

        # Create mapping of (original_name, command, env, scope) → renamed server name
        # Multiple servers can have the same original_name, so we need to match by full properties
        # This ensures detected_clients have the same names as deduplicated_servers
        def _make_server_key(server: DetectedServer, original_name: Optional[str] = None) -> Tuple:
            """Create a unique key for matching servers during name mapping."""
            return (
                original_name if original_name else server.name,
                tuple(server.command) if server.command else None,
                frozenset(server.env.items()) if server.env else frozenset(),
                server.scope,
            )

        name_mapping: Dict[Tuple, str] = {}
        for ds in new_servers:
            if ds.was_renamed and ds.original_name:
                # Key = (original_name, command, env, scope)
                key = _make_server_key(ds.server, ds.original_name)
                name_mapping[key] = ds.server.name

        # Update server names in detected_clients to match renamed servers
        # This fixes the bug where ClientSelectionScreen filters using renamed names
        # but detected_clients still have original names
        # IMPORTANT: Preserve original_name before mutation for CLI removal commands
        for client in new_clients:
            for server in client.servers:
                key = _make_server_key(server)
                if key in name_mapping:
                    # Preserve the original name (what's actually in the client config)
                    if server.original_name is None:
                        server.original_name = server.name
                    # Rename to the deduped name (for internal tracking)
                    server.name = name_mapping[key]

        # Update data
        self.deduplicated_servers = new_servers
        self.detected_clients = new_clients

        # Reconcile servers
        valid_server_names = {s.server.name for s in new_servers}
        newly_discovered = valid_server_names - old_server_names

        self.selected_server_names = (
            (self.selected_server_names & valid_server_names)  # Keep valid selections
            | newly_discovered  # Auto-select new servers
        )

        # Reconcile clients (identical logic)
        valid_client_types = {c.client_type for c in new_clients}
        newly_detected = valid_client_types - old_client_types

        self.selected_client_types = (
            (self.selected_client_types & valid_client_types) | newly_detected
        )

    def get_selected_servers(self) -> List[DeduplicatedServer]:
        """Get deduplicated servers that user selected."""
        return [
            ds
            for ds in self.deduplicated_servers
            if ds.server.name in self.selected_server_names
        ]

    def get_selected_clients(self) -> List[DetectedClient]:
        """Get clients that user selected for migration."""
        return [
            c for c in self.detected_clients if c.client_type in self.selected_client_types
        ]
