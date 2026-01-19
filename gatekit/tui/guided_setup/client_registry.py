"""Centralized registry of supported MCP clients for guided setup.

This module provides a single source of truth for:
- Which MCP clients Gatekit can auto-detect
- Where their config files are located (per platform)
- How to parse their configurations
- Display names and metadata

Adding support for new clients requires:
1. Add enum value to ClientType in models.py
2. Add entry to CLIENT_REGISTRY below
3. Implement detection function (can follow existing patterns)
"""

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ClientType, DetectedClient
else:
    # Import at runtime to avoid circular imports
    from .models import ClientType, DetectedClient

# Type aliases
ConfigFormat = Literal["json", "toml"]
MigrationMethod = Literal["cli", "manual_edit"]
# Type for restore function: (client, restore_dir, timestamp) -> script_path
RestoreFunction = Callable[["DetectedClient", Path, str], Path]


@dataclass
class ClientRegistryEntry:
    """Metadata for a supported MCP client.

    Attributes:
        client_type: Enum identifying this client
        display_name: Human-readable name shown in UI
        config_format: File format (json or toml)
        migration_method: How to apply migration changes:
            - "cli": Run shell commands (e.g., Claude Code, Codex)
            - "manual_edit": Manually edit config file (e.g., Claude Desktop, Cursor, Windsurf)
        config_paths: Platform-specific config paths (callable that returns Path)
                     Callable takes no args and returns Path or None
        detection_function: Function that attempts to detect and parse this client
                           Returns DetectedClient or None
        restore_function: Function to generate restore script for this client
                         Takes (client, restore_dir, timestamp) and returns script path
    """

    client_type: "ClientType"
    display_name: str
    config_format: ConfigFormat
    migration_method: MigrationMethod
    config_paths: Callable[[], Optional[Path]]
    detection_function: Callable[[], Optional["DetectedClient"]]
    restore_function: Optional[RestoreFunction] = None


# Lazily import detection helpers so tests can patch detection.get_home_dir
_detection_module = None


def _ensure_helpers_initialized():
    """Lazy import helper module from detection to avoid circular imports."""
    global _detection_module
    if _detection_module is None:
        import gatekit.tui.guided_setup.detection as detection_module

        _detection_module = detection_module


def get_home_dir() -> Path:
    """Get user's home directory cross-platform.

    This delegates to detection.get_home_dir() which is what tests mock.
    """
    _ensure_helpers_initialized()
    return _detection_module.get_home_dir()


def get_appdata() -> Path:
    """Get Windows AppData/Roaming directory.

    This delegates to detection.get_platform_appdata() which respects test mocks.
    """
    _ensure_helpers_initialized()
    return _detection_module.get_platform_appdata()


# ============================================================================
# Config Path Resolvers
# ============================================================================
# These functions return the config path for a client based on current platform


def get_claude_desktop_path() -> Optional[Path]:
    """Get Claude Desktop config path for current platform."""
    home = get_home_dir()
    system = platform.system()

    if system == "Darwin":  # macOS
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Linux":
        return home / ".config" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        return get_appdata() / "Claude" / "claude_desktop_config.json"
    return None


def get_claude_code_path() -> Optional[Path]:
    """Get Claude Code config path (user-level).

    Note: Claude Code also supports project-level configs (.mcp.json),
    but we return the primary user config here.
    """
    return get_home_dir() / ".claude.json"


def get_codex_path() -> Optional[Path]:
    """Get Codex config path.

    Checks $CODEX_HOME first, then falls back to default.
    """
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home) / "config.toml"
    return get_home_dir() / ".codex" / "config.toml"


# ============================================================================
# Client Registry
# ============================================================================
# This is the single source of truth for supported clients
# Add new clients here to enable auto-detection in guided setup

# Import detection and restore functions lazily to avoid circular imports
# These will be set by detection.py and restore_scripts.py after module load
_detection_functions: Dict[ClientType, Callable[[], Optional[DetectedClient]]] = {}
_restore_functions: Dict[ClientType, RestoreFunction] = {}


def register_detection_function(
    client_type: ClientType, func: Callable[[], Optional[DetectedClient]]
) -> None:
    """Register a detection function for a client type.

    This is called by detection.py during module initialization.

    Raises:
        ValueError: If no registry entry exists for the client type
    """
    entry = get_registry_entry(client_type)
    if not entry:
        raise ValueError(
            f"Cannot register detection function for {client_type.value}: "
            f"No registry entry found. Add ClientRegistryEntry to CLIENT_REGISTRY first."
        )
    _detection_functions[client_type] = func


def register_restore_function(
    client_type: ClientType, func: RestoreFunction
) -> None:
    """Register a restore script generation function for a client type.

    This is called by restore_scripts.py during module initialization.
    Directly assigns the function to the registry entry's restore_function field.

    Raises:
        ValueError: If no registry entry exists for the client type
    """
    _restore_functions[client_type] = func
    entry = get_registry_entry(client_type)
    if not entry:
        raise ValueError(
            f"Cannot register restore function for {client_type.value}: "
            f"No registry entry found. Add ClientRegistryEntry to CLIENT_REGISTRY first."
        )
    entry.restore_function = func


# Additional config path resolvers
def get_cursor_path() -> Optional[Path]:
    """Get Cursor native MCP config path.

    Cursor has built-in MCP support with a centralized config file.
    Location is the same across all platforms.
    """
    return get_home_dir() / ".cursor" / "mcp.json"


def get_windsurf_path() -> Optional[Path]:
    """Get Windsurf Cascade MCP config path.

    Windsurf has built-in Cascade AI with MCP support.
    Uses same schema as Claude Desktop config.
    Location is the same across all platforms.
    """
    return get_home_dir() / ".codeium" / "windsurf" / "mcp_config.json"


# Client registry entries (without detection/restore functions initially)
# Detection functions are injected by detection.py to avoid circular imports
# Restore functions are injected by restore_scripts.py via register_restore_function()
# Note: restore_function defaults to None, so we omit it from entries
CLIENT_REGISTRY: List[ClientRegistryEntry] = [
    ClientRegistryEntry(
        client_type=ClientType.CLAUDE_DESKTOP,
        display_name=ClientType.CLAUDE_DESKTOP.display_name(),
        config_format="json",
        migration_method="manual_edit",
        config_paths=get_claude_desktop_path,
        detection_function=lambda: _detection_functions.get(ClientType.CLAUDE_DESKTOP, lambda: None)(),
    ),
    ClientRegistryEntry(
        client_type=ClientType.CLAUDE_CODE,
        display_name=ClientType.CLAUDE_CODE.display_name(),
        config_format="json",
        migration_method="cli",
        config_paths=get_claude_code_path,
        detection_function=lambda: _detection_functions.get(ClientType.CLAUDE_CODE, lambda: None)(),
    ),
    ClientRegistryEntry(
        client_type=ClientType.CODEX,
        display_name=ClientType.CODEX.display_name(),
        config_format="toml",
        migration_method="cli",
        config_paths=get_codex_path,
        detection_function=lambda: _detection_functions.get(ClientType.CODEX, lambda: None)(),
    ),
    ClientRegistryEntry(
        client_type=ClientType.CURSOR,
        display_name=ClientType.CURSOR.display_name(),
        config_format="json",
        migration_method="manual_edit",
        config_paths=get_cursor_path,
        detection_function=lambda: _detection_functions.get(ClientType.CURSOR, lambda: None)(),
    ),
    ClientRegistryEntry(
        client_type=ClientType.WINDSURF,
        display_name=ClientType.WINDSURF.display_name(),
        config_format="json",
        migration_method="manual_edit",
        config_paths=get_windsurf_path,
        detection_function=lambda: _detection_functions.get(ClientType.WINDSURF, lambda: None)(),
    ),
]


# ============================================================================
# Public API
# ============================================================================


def get_supported_client_names() -> List[str]:
    """Get list of display names for all supported clients.

    Returns:
        List of human-readable client names (e.g., ["Claude Desktop", "Claude Code", "Codex"])

    Example:
        >>> names = get_supported_client_names()
        >>> print(", ".join(names))
        Claude Desktop, Claude Code, Codex
    """
    return [entry.display_name for entry in CLIENT_REGISTRY]


def get_registry_entry(client_type: ClientType) -> Optional[ClientRegistryEntry]:
    """Get registry entry for a specific client type.

    Args:
        client_type: Client type to look up

    Returns:
        Registry entry if found, None otherwise
    """
    for entry in CLIENT_REGISTRY:
        if entry.client_type == client_type:
            return entry
    return None


def detect_all_clients() -> List[DetectedClient]:
    """Detect all registered clients on the system.

    Iterates through CLIENT_REGISTRY and attempts detection for each client.
    Failures are silently ignored (client just won't be included in results).

    Returns:
        List of successfully detected clients (may be empty)
    """
    clients = []

    for entry in CLIENT_REGISTRY:
        try:
            client = entry.detection_function()
            if client is not None:
                clients.append(client)
        except Exception:
            # Silently skip clients that fail detection
            # Parse errors for individual servers are captured in DetectedClient.parse_errors
            pass

    return clients


# ============================================================================
# How to Add Support for New MCP Clients
# ============================================================================
#
# Follow these steps to add detection for a new MCP client (e.g., Windsurf, Cursor, VSCode):
#
# STEP 1: Add Client Type Enum
# -----------------------------
# In gatekit/tui/guided_setup/models.py, add the new client to ClientType:
#
#   class ClientType(str, Enum):
#       CLAUDE_DESKTOP = "claude_desktop"
#       CLAUDE_CODE = "claude_code"
#       CODEX = "codex"
#       WINDSURF = "windsurf"  # <-- Add this
#
#   Update the display_name() method:
#
#       def display_name(self) -> str:
#           return {
#               ClientType.CLAUDE_DESKTOP: "Claude Desktop",
#               ClientType.CLAUDE_CODE: "Claude Code",
#               ClientType.CODEX: "Codex",
#               ClientType.WINDSURF: "Windsurf",  # <-- Add this
#           }[self]
#
# STEP 2: Implement Config Path Resolver
# ---------------------------------------
# In this file (client_registry.py), add a function that returns the config path:
#
#   def get_windsurf_path() -> Optional[Path]:
#       """Get Windsurf config path for current platform."""
#       home = get_home_dir()
#       system = platform.system()
#       if system == "Darwin":
#           return home / "Library" / "Application Support" / "Windsurf" / "User" / "globalStorage" / "mcp.json"
#       elif system == "Linux":
#           return home / ".config" / "Windsurf" / "User" / "globalStorage" / "mcp.json"
#       elif system == "Windows":
#           return get_appdata() / "Windsurf" / "User" / "globalStorage" / "mcp.json"
#       return None
#
# STEP 3: Add Registry Entry
# ---------------------------
# Add a ClientRegistryEntry to CLIENT_REGISTRY (around line 197):
#
#   CLIENT_REGISTRY: List[ClientRegistryEntry] = [
#       # ... existing entries ...
#       ClientRegistryEntry(
#           client_type=ClientType.WINDSURF,
#           display_name="Windsurf",
#           config_format="json",  # or "toml" if applicable
#           migration_method="manual_edit",  # Use "cli" if client supports shell commands, "manual_edit" for JSON/TOML file editing
#           config_paths=get_windsurf_path,
#           detection_function=lambda: _detection_functions.get(ClientType.WINDSURF, lambda: None)(),
#           # restore_function defaults to None, set later by register_restore_function() in restore_scripts.py
#       ),
#   ]
#
# Migration method guidelines:
#   - "manual_edit": Client requires manual JSON/TOML file editing (e.g., Claude Desktop, Cursor, Windsurf)
#                    UI will show "Replace your entire config file with:", "Open in Editor", and "Copy Config" buttons
#   - "cli": Client supports CLI commands to modify config (e.g., Claude Code, Codex)
#            UI will show "Run these commands in your terminal:" with shell command syntax highlighting
#
# STEP 4: Implement Detection Function
# -------------------------------------
# In gatekit/tui/guided_setup/detection.py, implement the detection function.
# You can follow the pattern from detect_claude_desktop() or detect_codex():
#
#   def detect_windsurf() -> Optional[DetectedClient]:
#       """Detect Windsurf client and parse its configuration."""
#       from . import client_registry
#
#       # Get config path from registry
#       entry = client_registry.get_registry_entry(ClientType.WINDSURF)
#       if not entry:
#           return None
#
#       config_path = entry.config_paths()
#       if not config_path or not config_path.exists():
#           return None
#
#       # Parse the config (use appropriate parser for format)
#       servers, errors = JSONConfigParser.parse_file(config_path)
#
#       client = DetectedClient(
#           client_type=ClientType.WINDSURF,
#           config_path=config_path,
#           servers=servers,
#           parse_errors=errors,
#       )
#
#       # Detect if Gatekit is already configured
#       client.gatekit_config_path = detect_gatekit_in_client(client)
#
#       return client
#
# STEP 5: Register Detection Function
# ------------------------------------
# At the bottom of detection.py, register the function:
#
#   client_registry.register_detection_function(ClientType.WINDSURF, detect_windsurf)
#
# STEP 6: Implement Restore Function
# -----------------------------------
# In gatekit/tui/guided_setup/restore_scripts.py, implement the restore function.
# For manual-edit clients (JSON/TOML), follow the pattern from _generate_cursor_restore().
# For CLI clients, follow the pattern from _generate_claude_code_restore().
#
#   def _generate_windsurf_restore(
#       client: DetectedClient,
#       restore_dir: Path,
#       timestamp: str,
#   ) -> Path:
#       """Generate Windsurf restore instructions (.txt file)."""
#       script_path = restore_dir / f"restore-windsurf-{timestamp}.txt"
#       servers_json = _build_mcp_servers_json(client.servers)
#       # ... build restore instructions content ...
#       script_path.write_text(content, encoding="utf-8")
#       return script_path
#
# Then register the function at the bottom of restore_scripts.py:
#
#   client_registry.register_restore_function(ClientType.WINDSURF, _generate_windsurf_restore)
#
# STEP 7: Test
# ------------
# That's it! The new client will:
# - Appear in guided setup discovery
# - Show in "No servers found" modal automatically
# - Work with all existing guided setup flows
# - Generate restore scripts automatically
#
# Test by running:
#   pytest tests/unit/test_guided_setup_detection.py -v
#   pytest tests/unit/tui/guided_setup/test_restore_scripts.py -v
#
# ============================================================================
# Future Client Templates (Ready to Uncomment)
# ============================================================================
# Below are pre-written templates for common clients. Uncomment and adjust as needed.

# # Windsurf Configuration Paths
# def get_windsurf_path() -> Optional[Path]:
#     """Get Windsurf config path."""
#     home = get_home_dir()
#     system = platform.system()
#     if system == "Darwin":
#         return home / "Library" / "Application Support" / "Windsurf" / "User" / "globalStorage" / "mcp.json"
#     elif system == "Linux":
#         return home / ".config" / "Windsurf" / "User" / "globalStorage" / "mcp.json"
#     elif system == "Windows":
#         return get_appdata() / "Windsurf" / "User" / "globalStorage" / "mcp.json"
#     return None

# # Cursor Configuration Paths
# def get_cursor_path() -> Optional[Path]:
#     """Get Cursor config path."""
#     home = get_home_dir()
#     system = platform.system()
#     if system == "Darwin":
#         return home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "mcp.json"
#     elif system == "Linux":
#         return home / ".config" / "Cursor" / "User" / "globalStorage" / "mcp.json"
#     elif system == "Windows":
#         return get_appdata() / "Cursor" / "User" / "globalStorage" / "mcp.json"
#     return None

# # VSCode Configuration Paths
# def get_vscode_path() -> Optional[Path]:
#     """Get VSCode config path."""
#     home = get_home_dir()
#     system = platform.system()
#     if system == "Darwin":
#         return home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "mcp.json"
#     elif system == "Linux":
#         return home / ".config" / "Code" / "User" / "globalStorage" / "mcp.json"
#     elif system == "Windows":
#         return get_appdata() / "Code" / "User" / "globalStorage" / "mcp.json"
#     return None

# # Registry Entries (uncomment and add to CLIENT_REGISTRY list above):
# # ClientRegistryEntry(
# #     client_type=ClientType.WINDSURF,
# #     display_name="Windsurf",
# #     config_format="json",
# #     migration_method="manual_edit",  # Windsurf requires manual JSON file editing
# #     config_paths=get_windsurf_path,
# #     detection_function=lambda: _detection_functions.get(ClientType.WINDSURF, lambda: None)(),
# # ),
# # ClientRegistryEntry(
# #     client_type=ClientType.CURSOR,
# #     display_name="Cursor",
# #     config_format="json",
# #     migration_method="manual_edit",  # Cursor requires manual JSON file editing
# #     config_paths=get_cursor_path,
# #     detection_function=lambda: _detection_functions.get(ClientType.CURSOR, lambda: None)(),
# # ),
# # ClientRegistryEntry(
# #     client_type=ClientType.VSCODE,
# #     display_name="VSCode",
# #     config_format="json",
# #     migration_method="manual_edit",  # VSCode requires manual JSON file editing (adjust if it has CLI)
# #     config_paths=get_vscode_path,
# #     detection_function=lambda: _detection_functions.get(ClientType.VSCODE, lambda: None)(),
# # ),
