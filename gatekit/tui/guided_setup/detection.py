"""MCP client detection - scan system for client config files."""

import os
import platform
from pathlib import Path
from typing import List, Optional

from .models import DetectedClient, ClientType, ServerScope
from .parsers import JSONConfigParser, TOMLConfigParser, detect_scope_from_path
from . import client_registry


def _log_detection(message: str, context: dict = None) -> None:
    """Log detection events if debug logger is available."""
    try:
        from ..debug import get_debug_logger
        logger = get_debug_logger()
        if logger:
            logger.log_event("client_detection", context={"message": message, **(context or {})})
    except Exception:
        pass  # Debug logging should never break detection


def get_home_dir() -> Path:
    """Get user's home directory in a cross-platform way.

    Returns:
        Path to home directory
    """
    return Path.home()


def get_platform_appdata() -> Path:
    """Get platform-specific AppData directory (Windows only).

    Returns:
        Path to AppData/Roaming on Windows

    Raises:
        RuntimeError: If called on non-Windows platform
    """
    if platform.system() != "Windows":
        raise RuntimeError("get_platform_appdata() is only for Windows")

    appdata = os.environ.get("APPDATA")
    if not appdata:
        # Fallback: construct manually
        home = get_home_dir()
        return home / "AppData" / "Roaming"

    return Path(appdata)


def extract_gatekit_config_path(args: List[str]) -> str:
    """Extract gatekit config path from server args or return default.

    Args:
        args: Server arguments list (from server config)

    Returns:
        Path to gatekit.yaml (from args or platform default)
    """
    # Look for --config argument
    for i, arg in enumerate(args):
        if arg == "--config" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--config="):
            return arg.split("=", 1)[1]

    # Default location (platform-specific)
    home = get_home_dir()
    system = platform.system()

    if system == "Darwin":  # macOS
        return str(home / ".config" / "gatekit" / "gatekit.yaml")
    elif system == "Linux":
        return str(home / ".config" / "gatekit" / "gatekit.yaml")
    elif system == "Windows":
        appdata = get_platform_appdata()
        return str(appdata / "gatekit" / "gatekit.yaml")
    else:
        # Unknown platform, use Linux default
        return str(home / ".config" / "gatekit" / "gatekit.yaml")


def is_gatekit_command(command: List[str]) -> bool:
    """Check if a command list represents a Gatekit server.

    Detects Gatekit via:
    - "gatekit-gateway" anywhere in command (specific enough to not false-match)
    - "gatekit.main" anywhere in command (Python module invocation)
    - Bare "gatekit" only in command position (first 3 tokens to handle wrappers)

    Does NOT match "gatekit" appearing as a directory path argument like
    "npx -y @pkg C:\\users\\dbrig\\gatekit".

    Args:
        command: Command list from server config

    Returns:
        True if this is a Gatekit server command
    """
    if not command:
        return False

    command_str = " ".join(command)

    # These are specific enough to match anywhere in the command
    if "gatekit-gateway" in command_str:
        return True
    if "gatekit.main" in command_str:
        return True

    # For bare "gatekit" or custom names ending with "gatekit",
    # only check the command position (first 3 tokens) to handle wrappers
    # like "uv run gatekit" but NOT match directory paths as arguments
    # like "npx -y @pkg C:\path\to\gatekit"
    for token in command[:3]:  # Only first 3 tokens
        # Check if basename (without extension) ends with "gatekit"
        # This handles: /usr/local/bin/gatekit, gatekit.exe, my-gatekit
        basename = Path(token).stem.lower()
        if basename.endswith("gatekit"):
            return True

    return False


def detect_gatekit_in_client(client: DetectedClient) -> Optional[str]:
    """Check if client has Gatekit configured, return config path if found.

    Scans the entire command list to detect Gatekit even when launched via wrappers
    like ["uv", "run", "gatekit-gateway"] or ["python", "-m", "gatekit.main"].

    Args:
        client: Detected MCP client to check

    Returns:
        Path to gatekit.yaml if client uses Gatekit, None otherwise
    """
    for server in client.servers:
        if not server.command:
            continue

        if is_gatekit_command(server.command):
            # Extract config path from full command list
            # Args could be anywhere in the list (after the actual command)
            return extract_gatekit_config_path(server.command)

    return None


def detect_claude_desktop() -> Optional[DetectedClient]:
    """Detect Claude Desktop client and parse its configuration.

    Tries platform-specific config locations:
    - macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
    - Linux: ~/.config/Claude/claude_desktop_config.json
    - Windows: %APPDATA%/Claude/claude_desktop_config.json

    Returns:
        DetectedClient if found and parsed, None if not found
    """
    home = get_home_dir()
    system = platform.system()

    # Determine config path based on platform
    if system == "Darwin":  # macOS
        config_path = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Linux":
        config_path = home / ".config" / "Claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = get_platform_appdata()
        config_path = appdata / "Claude" / "claude_desktop_config.json"
    else:
        # Unknown platform
        return None

    # Check if config exists
    if not config_path.exists():
        return None

    # Parse the config
    servers, errors = JSONConfigParser.parse_file(config_path)

    client = DetectedClient(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=config_path,
        servers=servers,
        parse_errors=errors,
    )

    # Detect if Gatekit is already configured
    client.gatekit_config_path = detect_gatekit_in_client(client)

    return client


def detect_claude_code() -> Optional[DetectedClient]:
    """Detect Claude Code client and parse its configuration.

    Tries multiple locations in order:
    1. User-level: ~/.claude.json (primary)
    2. Project-level: .mcp.json (in current directory)

    For ~/.claude.json, also checks for a "projects" section that contains
    per-project MCP server configurations. These are tagged with the project
    path and scope=PROJECT.

    Tracks the scope (user vs project) for each detected server,
    which is needed for generating correct CLI commands.

    Returns:
        DetectedClient if found and parsed, None if not found
    """
    import json

    home = get_home_dir()
    cwd = Path.cwd()

    # Try locations in order
    config_paths = [
        home / ".claude.json",  # User-level (primary)
        cwd / ".mcp.json",  # Project-level
    ]

    all_servers = []
    all_errors = []
    config_path_found = None

    for config_path in config_paths:
        if not config_path.exists():
            continue

        # Track the first config path we found
        if config_path_found is None:
            config_path_found = config_path

        # Parse root-level mcpServers (existing behavior)
        servers, errors = JSONConfigParser.parse_file(config_path)

        # Detect scope from path and assign to each server
        scope = detect_scope_from_path(config_path)
        for server in servers:
            server.scope = scope

        all_servers.extend(servers)
        all_errors.extend(errors)

        # For ~/.claude.json, also check for project-level servers
        if config_path.name == ".claude.json":
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # Check for projects section
                projects = config.get("projects", {})
                if isinstance(projects, dict):
                    for project_path, project_data in projects.items():
                        if not isinstance(project_data, dict):
                            continue

                        project_servers = project_data.get("mcpServers", {})
                        if not project_servers or not isinstance(project_servers, dict):
                            continue

                        # Parse servers from this project
                        for server_name, server_config in project_servers.items():
                            try:
                                server = JSONConfigParser._parse_server(server_name, server_config)
                                server.project_path = project_path
                                # These servers are in ~/.claude.json but project-specific
                                # (private to you in this project) - this is LOCAL scope
                                server.scope = ServerScope.LOCAL
                                all_servers.append(server)
                            except Exception as e:
                                all_errors.append(
                                    f"Failed to parse server '{server_name}' from project {project_path}: {e}"
                                )

            except json.JSONDecodeError:
                # Already handled by JSONConfigParser.parse_file
                pass
            except Exception as e:
                all_errors.append(f"Failed to parse projects section from {config_path}: {e}")

    # If we didn't find any configs, return None
    if config_path_found is None:
        return None

    client = DetectedClient(
        client_type=ClientType.CLAUDE_CODE,
        config_path=config_path_found,
        servers=all_servers,
        parse_errors=all_errors,
    )

    # Detect if Gatekit is already configured
    client.gatekit_config_path = detect_gatekit_in_client(client)

    return client


def detect_codex() -> Optional[DetectedClient]:
    """Detect Codex client and parse its configuration.

    Tries multiple locations:
    1. $CODEX_HOME/config.toml (if env var set)
    2. ~/.codex/config.toml (default location)

    Returns:
        DetectedClient if found and parsed, None if not found
    """
    # Check environment variable first
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        config_path = Path(codex_home) / "config.toml"
        if config_path.exists():
            servers, errors = TOMLConfigParser.parse_file(config_path)
            client = DetectedClient(
                client_type=ClientType.CODEX,
                config_path=config_path,
                servers=servers,
                parse_errors=errors,
            )
            # Detect if Gatekit is already configured
            client.gatekit_config_path = detect_gatekit_in_client(client)
            return client

    # Try default location
    home = get_home_dir()
    config_path = home / ".codex" / "config.toml"

    if not config_path.exists():
        return None

    servers, errors = TOMLConfigParser.parse_file(config_path)

    client = DetectedClient(
        client_type=ClientType.CODEX,
        config_path=config_path,
        servers=servers,
        parse_errors=errors,
    )

    # Detect if Gatekit is already configured
    client.gatekit_config_path = detect_gatekit_in_client(client)

    return client


def detect_cursor() -> Optional[DetectedClient]:
    """Detect Cursor with native MCP support and parse its configuration.

    Cursor has built-in MCP support with a centralized config file.
    Location (all platforms): ~/.cursor/mcp.json

    Returns:
        DetectedClient if found and parsed, None if not found
    """
    _log_detection("detect_cursor() called")

    registry_entry = client_registry.get_registry_entry(ClientType.CURSOR)
    if not registry_entry:
        _log_detection("No registry entry for CURSOR")
        return None

    config_path = registry_entry.config_paths()
    _log_detection(f"Cursor config_path: {config_path}", {"path": str(config_path) if config_path else None})

    if not config_path:
        _log_detection("config_path is None")
        return None

    path_exists = config_path.exists()
    _log_detection(f"Cursor config exists: {path_exists}", {"exists": path_exists, "path": str(config_path)})

    if not path_exists:
        return None

    # Parse the config using JSON parser
    servers, errors = JSONConfigParser.parse_file(config_path)
    _log_detection(f"Cursor parse result: {len(servers)} servers, {len(errors)} errors", {
        "server_count": len(servers),
        "server_names": [s.name for s in servers],
        "errors": errors,
    })

    client = DetectedClient(
        client_type=ClientType.CURSOR,
        config_path=config_path,
        servers=servers,
        parse_errors=errors,
    )

    # Detect if Gatekit is already configured
    client.gatekit_config_path = detect_gatekit_in_client(client)

    return client


def detect_windsurf() -> Optional[DetectedClient]:
    """Detect Windsurf with built-in Cascade AI and parse its configuration.

    Windsurf has built-in Cascade AI with MCP support.
    Uses same config schema as Claude Desktop.
    Location (all platforms): ~/.codeium/windsurf/mcp_config.json

    Returns:
        DetectedClient if found and parsed, None if not found
    """
    config_path = client_registry.get_registry_entry(ClientType.WINDSURF)
    if not config_path:
        return None

    config_path = config_path.config_paths()
    if not config_path or not config_path.exists():
        return None

    # Parse the config using JSON parser
    servers, errors = JSONConfigParser.parse_file(config_path)

    client = DetectedClient(
        client_type=ClientType.WINDSURF,
        config_path=config_path,
        servers=servers,
        parse_errors=errors,
    )

    # Detect if Gatekit is already configured
    client.gatekit_config_path = detect_gatekit_in_client(client)

    return client


# ============================================================================
# Registry Integration
# ============================================================================
# Register detection functions with the client registry so they can be
# called dynamically. This avoids circular imports and centralizes client metadata.

client_registry.register_detection_function(ClientType.CLAUDE_DESKTOP, detect_claude_desktop)
client_registry.register_detection_function(ClientType.CLAUDE_CODE, detect_claude_code)
client_registry.register_detection_function(ClientType.CODEX, detect_codex)
client_registry.register_detection_function(ClientType.CURSOR, detect_cursor)
client_registry.register_detection_function(ClientType.WINDSURF, detect_windsurf)


def detect_all_clients() -> List[DetectedClient]:
    """Detect all supported MCP clients on the system.

    Uses the client registry to determine which clients to scan for.
    See client_registry.py for the list of supported clients.

    Returns:
        List of detected clients (empty if none found)
    """
    return client_registry.detect_all_clients()
