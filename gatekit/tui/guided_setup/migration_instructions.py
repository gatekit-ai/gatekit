"""Migration instruction generation - create snippets for updating MCP clients."""

import json
import platform
import shlex
from pathlib import Path
from typing import List

from .models import DetectedClient, DetectedServer, ClientType, ServerScope
from .config_generation import _collect_all_env_vars
from ..utils.terminal_compat import get_warning_icon


def _quote_powershell(value: str) -> str:
    """Quote a value for PowerShell command line.

    Wraps the value in double quotes and escapes any inner double quotes
    with PowerShell's backtick escape character.

    Args:
        value: Value to quote

    Returns:
        Quoted value safe for PowerShell command line
    """
    # Escape double quotes with backtick
    escaped = value.replace('"', '`"')
    return f'"{escaped}"'


def _quote_cmd_wrapper(value: str) -> str:
    """Quote a value for use inside a cmd /c "..." wrapper.

    Uses doubled quotes ("") which work in both PowerShell and cmd.exe
    when the entire command is wrapped in cmd /c "...".

    Args:
        value: Value to quote

    Returns:
        Quoted value using doubled quotes
    """
    # Escape any existing double quotes by doubling them
    escaped = value.replace('"', '""')
    return f'""{escaped}""'


class MigrationInstructions:
    """Migration instructions for a specific MCP client."""

    def __init__(
        self,
        client_type: ClientType,
        config_path: Path,
        servers_to_migrate: List[str],
        migration_snippet: str,
        instruction_text: str,
    ):
        """Initialize migration instructions.

        Args:
            client_type: Type of MCP client
            config_path: Absolute path to client config file
            servers_to_migrate: List of server names being migrated
            migration_snippet: Code/command snippet to copy
            instruction_text: Human-readable instructions
        """
        self.client_type = client_type
        self.config_path = config_path
        self.servers_to_migrate = servers_to_migrate
        self.migration_snippet = migration_snippet
        self.instruction_text = instruction_text


def generate_migration_instructions(
    detected_clients: List[DetectedClient],
    selected_server_names: set,
    gatekit_gateway_path: Path,
    gatekit_config_path: Path,
) -> List[MigrationInstructions]:
    """Generate migration instructions for all detected clients.

    Creates client-specific instructions for:
    - Claude Desktop: JSON snippet (manual editing, preserves unselected servers)
    - Claude Code: CLI commands (only removes selected servers)
    - Codex: CLI commands (only removes selected servers)
    - Cursor: JSON snippet (manual editing, preserves unselected servers)
    - Windsurf: JSON snippet (manual editing, preserves unselected servers)

    All paths are expanded to absolute paths (no ~, no env vars).

    Args:
        detected_clients: List of detected MCP clients
        selected_server_names: Set of server names user selected to migrate to Gatekit
        gatekit_gateway_path: Absolute path to gatekit-gateway executable
        gatekit_config_path: Absolute path to generated Gatekit config

    Returns:
        List of MigrationInstructions for each client
    """
    instructions = []

    for client in detected_clients:
        # Filter to only selected stdio servers for this client
        all_stdio_servers = client.get_stdio_servers()
        selected_stdio_servers = [s for s in all_stdio_servers if s.name in selected_server_names]

        # User explicitly selected this client - generate instructions regardless of server config
        # Instructions will explain what servers (if any) are being migrated vs preserved

        if client.client_type == ClientType.CLAUDE_DESKTOP:
            instr = _generate_claude_desktop_instructions(
                client,
                selected_stdio_servers,
                all_stdio_servers,
                gatekit_gateway_path,
                gatekit_config_path,
            )
        elif client.client_type == ClientType.CLAUDE_CODE:
            instr = _generate_claude_code_instructions(
                client,
                selected_stdio_servers,
                gatekit_gateway_path,
                gatekit_config_path,
            )
        elif client.client_type == ClientType.CODEX:
            instr = _generate_codex_instructions(
                client,
                selected_stdio_servers,
                gatekit_gateway_path,
                gatekit_config_path,
            )
        elif client.client_type == ClientType.CURSOR:
            instr = _generate_cursor_instructions(
                client,
                selected_stdio_servers,
                all_stdio_servers,
                gatekit_gateway_path,
                gatekit_config_path,
            )
        elif client.client_type == ClientType.WINDSURF:
            instr = _generate_windsurf_instructions(
                client,
                selected_stdio_servers,
                all_stdio_servers,
                gatekit_gateway_path,
                gatekit_config_path,
            )
        else:
            continue

        instructions.append(instr)

    return instructions


def _generate_claude_desktop_instructions(
    client: DetectedClient,
    selected_stdio_servers: List[DetectedServer],
    all_stdio_servers: List[DetectedServer],
    gatekit_gateway_path: Path,
    gatekit_config_path: Path,
) -> MigrationInstructions:
    """Generate Claude Desktop migration instructions (JSON snippet).

    Returns complete config file with mcpServers section modified to:
    - Replace selected servers with Gatekit
    - Preserve unselected servers as-is

    Reads the existing config file and modifies only selected servers,
    preserving all other settings and unselected servers.

    Args:
        client: Detected Claude Desktop client
        selected_stdio_servers: List of stdio servers user selected to migrate
        all_stdio_servers: List of all stdio servers in this client
        gatekit_gateway_path: Absolute path to gatekit-gateway
        gatekit_config_path: Absolute path to Gatekit config

    Returns:
        MigrationInstructions instance
    """
    # Sort servers by name for deterministic env var collection
    servers_sorted = sorted(selected_stdio_servers, key=lambda s: s.name)

    # Collect env vars and detect conflicts
    all_env_vars, env_conflicts = _collect_all_env_vars(servers_sorted)

    # Build Gatekit mcpServers entry
    gatekit_entry = {
        "command": str(gatekit_gateway_path),
        "args": ["--config", str(gatekit_config_path)],
    }

    # Add env vars if any were found
    if all_env_vars:
        gatekit_entry["env"] = all_env_vars

    # Read existing config file and modify mcpServers section
    try:
        with open(client.config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # If file doesn't exist or is invalid, create minimal config
        config_data = {}

    # Get existing mcpServers section
    existing_servers = config_data.get("mcpServers", {})
    if not isinstance(existing_servers, dict):
        existing_servers = {}

    # Build new mcpServers: preserve unselected servers, add Gatekit for selected
    selected_names = {s.name for s in selected_stdio_servers}
    new_mcp_servers = {}

    # Keep servers that were NOT selected (but skip existing gatekit entry - we'll add new one)
    for server_name, server_config in existing_servers.items():
        if server_name not in selected_names and server_name != "gatekit":
            new_mcp_servers[server_name] = server_config

    # Always add Gatekit entry (user selected this client to configure)
    new_mcp_servers["gatekit"] = gatekit_entry

    # Update config
    config_data["mcpServers"] = new_mcp_servers

    # Generate complete config file snippet
    snippet = json.dumps(config_data, indent=2)

    # Build server lists
    selected_names_list = [s.name for s in selected_stdio_servers]
    all_names = {s.name for s in all_stdio_servers}
    unselected_names = [name for name in existing_servers.keys() if name not in selected_names_list and name in all_names and name != "gatekit"]

    # Build instructions with conflict warnings
    if selected_stdio_servers:
        instruction_text = f"""Update Claude Desktop

Config file: {client.config_path}

Servers to migrate to Gatekit (will be managed by Gatekit):
{_format_bullet_list(selected_names_list)}"""
    else:
        instruction_text = f"""Update Claude Desktop

Config file: {client.config_path}

No servers selected for migration to Gatekit."""

    if unselected_names:
        instruction_text += f"""

Servers to preserve (will remain in your config):
{_format_bullet_list(unselected_names)}"""

    instruction_text += f"""

Replace your entire config file with:
{snippet}

After editing config, restart Claude Desktop"""

    # Add conflict warnings if any
    if env_conflicts:
        warning = f"\n{get_warning_icon()} Environment Variable Conflicts:\n"
        warning += "\n".join(env_conflicts)
        instruction_text = warning + "\n\n" + instruction_text

    return MigrationInstructions(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=client.config_path,
        servers_to_migrate=selected_names_list,
        migration_snippet=snippet,
        instruction_text=instruction_text,
    )


def _is_gatekit_server(server: DetectedServer) -> bool:
    """Check if a server is Gatekit based on its command.

    Detects Gatekit via:
    - "gatekit-gateway" anywhere in command (specific enough to not false-match)
    - "gatekit.main" anywhere in command (Python module invocation)
    - Bare "gatekit" only in command position (first 3 tokens to handle wrappers)

    Does NOT match "gatekit" appearing as a directory path argument like
    "npx -y @pkg C:\\users\\dbrig\\gatekit".

    Args:
        server: Server to check

    Returns:
        True if server is Gatekit, False otherwise
    """
    if not server.command:
        return False

    command_str = " ".join(server.command)

    # These are specific enough to match anywhere in the command
    if "gatekit-gateway" in command_str:
        return True
    if "gatekit.main" in command_str:
        return True

    # For bare "gatekit" or custom names ending with "gatekit",
    # only check the command position (first 3 tokens) to handle wrappers
    # like "uv run gatekit" but NOT match directory paths as arguments
    # like "npx -y @pkg C:\path\to\gatekit"
    for token in server.command[:3]:  # Only first 3 tokens
        # Check if basename (without extension) ends with "gatekit"
        # This handles: /usr/local/bin/gatekit, gatekit.exe, my-gatekit
        basename = Path(token).stem.lower()
        if basename.endswith("gatekit"):
            return True

    return False


def _generate_claude_code_instructions(
    client: DetectedClient,
    stdio_servers: List[DetectedServer],
    gatekit_gateway_path: Path,
    gatekit_config_path: Path,
) -> MigrationInstructions:
    """Generate Claude Code migration instructions (CLI commands).

    Args:
        client: Detected Claude Code client
        stdio_servers: List of stdio servers to migrate
        gatekit_gateway_path: Absolute path to gatekit-gateway
        gatekit_config_path: Absolute path to Gatekit config

    Returns:
        MigrationInstructions instance
    """
    # Build commands
    system = platform.system()
    is_windows = system == "Windows"

    # Find ALL existing Gatekit entries (user may have it in multiple scopes)
    # Use command-based detection, not name-based (server might be renamed)
    existing_gatekit_servers = [s for s in client.servers if _is_gatekit_server(s)]

    # Remove commands - each server gets its own scope flag
    # Use original_name (what's in the config) for removal, not the deduped name
    remove_commands = []
    for server in stdio_servers:
        scope_flag = _get_scope_flag(server)
        # Use original_name if available (for renamed servers), otherwise use current name
        server_name = server.original_name or server.name
        remove_commands.append(f"claude mcp remove {server_name} {scope_flag}")

    # Sort servers by name for deterministic env var collection
    servers_sorted = sorted(stdio_servers, key=lambda s: s.name)

    # Collect env vars and detect conflicts
    all_env_vars, env_conflicts = _collect_all_env_vars(servers_sorted)

    # Add gatekit command - always use user scope
    gatekit_scope_flag = "--scope user"

    # Build the add gatekit command based on platform
    if is_windows:
        # On Windows, wrap in cmd /c "..." with doubled quotes to work in both
        # PowerShell and cmd.exe. This avoids PowerShell's argument parsing issues
        # where --config gets interpreted as a claude option instead of being
        # passed through after --.
        # See: https://github.com/PowerShell/PowerShell/issues/20645
        shell_name = "terminal (PowerShell or Command Prompt)"

        # Build env var flags
        env_flags = ""
        if all_env_vars:
            env_parts = [f"--env {_quote_cmd_wrapper(f'{k}={v}')}" for k, v in all_env_vars.items()]
            env_flags = " " + " ".join(env_parts)

        # Build the full command wrapped in cmd /c
        inner_cmd = (
            f"claude mcp add --transport stdio {gatekit_scope_flag} gatekit"
            f"{env_flags} -- "
            f"{_quote_cmd_wrapper(str(gatekit_gateway_path))} "
            f"--config {_quote_cmd_wrapper(str(gatekit_config_path))}"
        )
        add_gatekit_cmd = f'cmd /c "{inner_cmd}"'
    else:
        def quote_fn(s: str) -> str:
            return shlex.quote(str(s))
        line_continuation = " \\\n"
        shell_name = "terminal"

        # Build command parts with appropriate quoting
        add_gatekit_parts = [
            f"claude mcp add --transport stdio {gatekit_scope_flag} gatekit",
        ]

        # Add env vars if any were found
        if all_env_vars:
            for key, value in all_env_vars.items():
                quoted_env = quote_fn(f"{key}={value}")
                add_gatekit_parts.append(f"  --env {quoted_env}")

        # Add command separator and gatekit-gateway command
        add_gatekit_parts.append(
            f"  -- {quote_fn(str(gatekit_gateway_path))} --config {quote_fn(str(gatekit_config_path))}"
        )

        add_gatekit_cmd = line_continuation.join(add_gatekit_parts)

    # Combine all commands with echo statements instead of comments
    # (echo avoids "command not found" errors when copy-pasting)
    commands = []

    # Remove ALL existing Gatekit entries first (user may have multiple scopes)
    # to avoid "already exists" error when adding new one
    if existing_gatekit_servers:
        commands.append("echo 'Removing existing Gatekit configuration...'")
        for wg_server in existing_gatekit_servers:
            scope_flag = _get_scope_flag(wg_server)
            # Use original_name if available (for renamed servers), otherwise use current name
            server_name = wg_server.original_name or wg_server.name
            commands.append(f"claude mcp remove {server_name} {scope_flag}")
        commands.append("")  # Blank line after group

    if remove_commands:
        commands.extend([
            "echo 'Removing original servers...'",
            *remove_commands,
            "",
        ])
    commands.extend([
        "echo 'Adding Gatekit...'",
        add_gatekit_cmd,
    ])

    # Add trailing newline so the last command executes when pasted into terminal.
    # Without this, Windows Terminal leaves the last command waiting for Enter.
    # See: https://github.com/microsoft/terminal/issues/12387
    snippet = "\n".join(commands) + "\n"

    # Build server list
    server_names = [s.name for s in stdio_servers]

    # Instruction text
    if server_names:
        instruction_text = f"""Update Claude Code

Servers detected (will be migrated to Gatekit):
{_format_bullet_list(server_names)}

Run these commands in your {shell_name}:
{snippet}

After running commands, restart Claude Code"""
    else:
        instruction_text = f"""Update Claude Code

Run these commands in your {shell_name}:
{snippet}

After running commands, restart Claude Code"""

    # Add scope information - always user scope for Claude Code
    scope_note = "ⓘ  Gatekit will be configured at user scope (available across all projects)\n\n"
    instruction_text = scope_note + instruction_text

    # Add conflict warnings if any
    if env_conflicts:
        warning = f"\n{get_warning_icon()} Environment Variable Conflicts:\n"
        warning += "\n".join(env_conflicts)
        instruction_text = warning + "\n\n" + instruction_text

    return MigrationInstructions(
        client_type=ClientType.CLAUDE_CODE,
        config_path=client.config_path,
        servers_to_migrate=server_names,
        migration_snippet=snippet,
        instruction_text=instruction_text,
    )


def _generate_codex_instructions(
    client: DetectedClient,
    stdio_servers: List[DetectedServer],
    gatekit_gateway_path: Path,
    gatekit_config_path: Path,
) -> MigrationInstructions:
    """Generate Codex migration instructions (CLI commands).

    Args:
        client: Detected Codex client
        stdio_servers: List of stdio servers to migrate
        gatekit_gateway_path: Absolute path to gatekit-gateway
        gatekit_config_path: Absolute path to Gatekit config

    Returns:
        MigrationInstructions instance
    """
    # Build commands
    system = platform.system()
    is_windows = system == "Windows"

    # Remove commands
    # Use original_name (what's in the config) for removal, not the deduped name
    remove_commands = [
        f"codex mcp remove {server.original_name or server.name}"
        for server in stdio_servers
    ]

    # Sort servers by name for deterministic env var collection
    servers_sorted = sorted(stdio_servers, key=lambda s: s.name)

    # Collect env vars and detect conflicts
    all_env_vars, env_conflicts = _collect_all_env_vars(servers_sorted)

    # Build the add gatekit command based on platform
    if is_windows:
        # On Windows, wrap in cmd /c "..." with doubled quotes to work in both
        # PowerShell and cmd.exe. This avoids PowerShell's argument parsing issues
        # where --config gets interpreted as a codex option instead of being
        # passed through after --.
        # See: https://github.com/PowerShell/PowerShell/issues/20645
        shell_name = "terminal (PowerShell or Command Prompt)"

        # Build env var flags
        env_flags = ""
        if all_env_vars:
            env_parts = [f"--env {_quote_cmd_wrapper(f'{k}={v}')}" for k, v in all_env_vars.items()]
            env_flags = " " + " ".join(env_parts)

        # Build the full command wrapped in cmd /c
        inner_cmd = (
            f"codex mcp add gatekit"
            f"{env_flags} -- "
            f"{_quote_cmd_wrapper(str(gatekit_gateway_path))} "
            f"--config {_quote_cmd_wrapper(str(gatekit_config_path))}"
        )
        add_gatekit_cmd = f'cmd /c "{inner_cmd}"'
    else:
        def quote_fn(s: str) -> str:
            return shlex.quote(str(s))
        line_continuation = " \\\n"
        shell_name = "terminal"

        # Build command parts with appropriate quoting
        add_gatekit_parts = [
            "codex mcp add gatekit",
        ]

        # Add env vars if any were found
        if all_env_vars:
            for key, value in all_env_vars.items():
                quoted_env = quote_fn(f"{key}={value}")
                add_gatekit_parts.append(f"  --env {quoted_env}")

        # Add command separator and gatekit-gateway command
        add_gatekit_parts.append(
            f"  -- {quote_fn(str(gatekit_gateway_path))} --config {quote_fn(str(gatekit_config_path))}"
        )

        add_gatekit_cmd = line_continuation.join(add_gatekit_parts)

    # Combine all commands with echo statements instead of comments
    # (echo avoids "command not found" errors when copy-pasting)
    commands = []
    if remove_commands:
        commands.extend([
            "echo 'Removing original servers...'",
            *remove_commands,
            "",
        ])
    commands.extend([
        "echo 'Adding Gatekit...'",
        add_gatekit_cmd,
    ])

    # Add trailing newline so the last command executes when pasted into terminal.
    # Without this, Windows Terminal leaves the last command waiting for Enter.
    # See: https://github.com/microsoft/terminal/issues/12387
    snippet = "\n".join(commands) + "\n"

    # Build server list
    server_names = [s.name for s in stdio_servers]

    # Instruction text
    if server_names:
        instruction_text = f"""Update Codex

Servers detected (will be migrated to Gatekit):
{_format_bullet_list(server_names)}

Run these commands in your {shell_name}:
{snippet}

After running commands, restart Codex"""
    else:
        instruction_text = f"""Update Codex

Run these commands in your {shell_name}:
{snippet}

After running commands, restart Codex"""

    # Add scope information (Codex uses user scope)
    scope_note = "ⓘ  Gatekit will be configured at user scope (available across all projects)\n\n"
    instruction_text = scope_note + instruction_text

    # Add conflict warnings if any
    if env_conflicts:
        warning = f"\n{get_warning_icon()} Environment Variable Conflicts:\n"
        warning += "\n".join(env_conflicts)
        instruction_text = warning + "\n\n" + instruction_text

    return MigrationInstructions(
        client_type=ClientType.CODEX,
        config_path=client.config_path,
        servers_to_migrate=server_names,
        migration_snippet=snippet,
        instruction_text=instruction_text,
    )


def _generate_cursor_instructions(
    client: DetectedClient,
    selected_stdio_servers: List[DetectedServer],
    all_stdio_servers: List[DetectedServer],
    gatekit_gateway_path: Path,
    gatekit_config_path: Path,
) -> MigrationInstructions:
    """Generate Cursor migration instructions (JSON snippet).

    Cursor uses the same schema as Claude Desktop with "mcpServers" key.
    Returns complete config file with mcpServers section modified to:
    - Replace selected servers with Gatekit
    - Preserve unselected servers as-is

    Args:
        client: Detected Cursor client
        selected_stdio_servers: List of stdio servers user selected to migrate
        all_stdio_servers: List of all stdio servers in this client
        gatekit_gateway_path: Absolute path to gatekit-gateway
        gatekit_config_path: Absolute path to Gatekit config

    Returns:
        MigrationInstructions instance
    """
    # Sort servers by name for deterministic env var collection
    servers_sorted = sorted(selected_stdio_servers, key=lambda s: s.name)

    # Collect env vars and detect conflicts
    all_env_vars, env_conflicts = _collect_all_env_vars(servers_sorted)

    # Build Gatekit mcpServers entry (same schema as Claude Desktop)
    gatekit_entry = {
        "command": str(gatekit_gateway_path),
        "args": ["--config", str(gatekit_config_path)],
    }

    # Add env vars if any were found
    if all_env_vars:
        gatekit_entry["env"] = all_env_vars

    # Read existing config file and modify mcpServers section
    try:
        with open(client.config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # If file doesn't exist or is invalid, create minimal config
        config_data = {}

    # Get existing mcpServers section
    existing_servers = config_data.get("mcpServers", {})
    if not isinstance(existing_servers, dict):
        existing_servers = {}

    # Build new mcpServers: preserve unselected servers, add Gatekit for selected
    selected_names = {s.name for s in selected_stdio_servers}
    new_mcp_servers = {}

    # Keep servers that were NOT selected (but skip existing gatekit entry - we'll add new one)
    for server_name, server_config in existing_servers.items():
        if server_name not in selected_names and server_name != "gatekit":
            new_mcp_servers[server_name] = server_config

    # Always add Gatekit entry (user selected this client to configure)
    new_mcp_servers["gatekit"] = gatekit_entry

    # Update config
    config_data["mcpServers"] = new_mcp_servers

    # Generate complete config file snippet
    snippet = json.dumps(config_data, indent=2)

    # Build server lists
    selected_names_list = [s.name for s in selected_stdio_servers]
    all_names = {s.name for s in all_stdio_servers}
    unselected_names = [name for name in existing_servers.keys() if name not in selected_names and name in all_names and name != "gatekit"]

    # Build instructions with conflict warnings
    if selected_stdio_servers:
        instruction_text = f"""Update Cursor

Config file: {client.config_path}

Servers to migrate to Gatekit (will be managed by Gatekit):
{_format_bullet_list(selected_names_list)}"""
    else:
        instruction_text = f"""Update Cursor

Config file: {client.config_path}

No servers selected for migration to Gatekit."""

    if unselected_names:
        instruction_text += f"""

Servers to preserve (will remain in your config):
{_format_bullet_list(unselected_names)}"""

    instruction_text += f"""

Replace your entire config file with:
{snippet}

After editing config, restart Cursor"""

    # Add conflict warnings if any
    if env_conflicts:
        warning = f"\n{get_warning_icon()} Environment Variable Conflicts:\n"
        warning += "\n".join(env_conflicts)
        instruction_text = warning + "\n\n" + instruction_text

    return MigrationInstructions(
        client_type=ClientType.CURSOR,
        config_path=client.config_path,
        servers_to_migrate=selected_names_list,
        migration_snippet=snippet,
        instruction_text=instruction_text,
    )


def _generate_windsurf_instructions(
    client: DetectedClient,
    selected_stdio_servers: List[DetectedServer],
    all_stdio_servers: List[DetectedServer],
    gatekit_gateway_path: Path,
    gatekit_config_path: Path,
) -> MigrationInstructions:
    """Generate Windsurf migration instructions (JSON snippet).

    Windsurf uses the same schema as Claude Desktop with "mcpServers" key.
    Returns complete config file with mcpServers section modified to:
    - Replace selected servers with Gatekit
    - Preserve unselected servers as-is

    Note: Windsurf recommends using the Plugin Store UI, but we provide
    manual JSON editing instructions since that's required for Gatekit setup.

    Args:
        client: Detected Windsurf client
        selected_stdio_servers: List of stdio servers user selected to migrate
        all_stdio_servers: List of all stdio servers in this client
        gatekit_gateway_path: Absolute path to gatekit-gateway
        gatekit_config_path: Absolute path to Gatekit config

    Returns:
        MigrationInstructions instance
    """
    # Sort servers by name for deterministic env var collection
    servers_sorted = sorted(selected_stdio_servers, key=lambda s: s.name)

    # Collect env vars and detect conflicts
    all_env_vars, env_conflicts = _collect_all_env_vars(servers_sorted)

    # Build Gatekit mcpServers entry (same schema as Claude Desktop)
    gatekit_entry = {
        "command": str(gatekit_gateway_path),
        "args": ["--config", str(gatekit_config_path)],
    }

    # Add env vars if any were found
    if all_env_vars:
        gatekit_entry["env"] = all_env_vars

    # Read existing config file and modify mcpServers section
    try:
        with open(client.config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # If file doesn't exist or is invalid, create minimal config
        config_data = {}

    # Get existing mcpServers section
    existing_servers = config_data.get("mcpServers", {})
    if not isinstance(existing_servers, dict):
        existing_servers = {}

    # Build new mcpServers: preserve unselected servers, add Gatekit for selected
    selected_names = {s.name for s in selected_stdio_servers}
    new_mcp_servers = {}

    # Keep servers that were NOT selected (but skip existing gatekit entry - we'll add new one)
    for server_name, server_config in existing_servers.items():
        if server_name not in selected_names and server_name != "gatekit":
            new_mcp_servers[server_name] = server_config

    # Always add Gatekit entry (user selected this client to configure)
    new_mcp_servers["gatekit"] = gatekit_entry

    # Update config
    config_data["mcpServers"] = new_mcp_servers

    # Generate complete config file snippet
    snippet = json.dumps(config_data, indent=2)

    # Build server lists
    selected_names_list = [s.name for s in selected_stdio_servers]
    all_names = {s.name for s in all_stdio_servers}
    unselected_names = [name for name in existing_servers.keys() if name not in selected_names and name in all_names and name != "gatekit"]

    # Build instructions with conflict warnings
    if selected_stdio_servers:
        instruction_text = f"""Update Windsurf

Config file: {client.config_path}

Servers to migrate to Gatekit (will be managed by Gatekit):
{_format_bullet_list(selected_names_list)}"""
    else:
        instruction_text = f"""Update Windsurf

Config file: {client.config_path}

No servers selected for migration to Gatekit."""

    if unselected_names:
        instruction_text += f"""

Servers to preserve (will remain in your config):
{_format_bullet_list(unselected_names)}"""

    instruction_text += f"""

Replace your entire config file with:
{snippet}

After editing config, click the refresh button in Cascade panel (Plugins menu)"""

    # Add conflict warnings if any
    if env_conflicts:
        warning = f"\n{get_warning_icon()} Environment Variable Conflicts:\n"
        warning += "\n".join(env_conflicts)
        instruction_text = warning + "\n\n" + instruction_text

    return MigrationInstructions(
        client_type=ClientType.WINDSURF,
        config_path=client.config_path,
        servers_to_migrate=selected_names_list,
        migration_snippet=snippet,
        instruction_text=instruction_text,
    )


def _format_bullet_list(items: List[str]) -> str:
    """Format a list of items as bullet points.

    Args:
        items: List of items to format

    Returns:
        Formatted bullet list string
    """
    return "\n".join(f"• {item}" for item in items)


def _get_scope_flag(server: DetectedServer) -> str:
    """Get the --scope flag for a server based on its scope.

    Args:
        server: Detected server

    Returns:
        Scope flag string (e.g., '--scope user', '--scope project', '--scope local')
    """
    if server.scope == ServerScope.PROJECT:
        return "--scope project"
    elif server.scope == ServerScope.LOCAL:
        return "--scope local"
    elif server.scope == ServerScope.USER:
        return "--scope user"
    else:
        # Default to user if scope not specified
        return "--scope user"


