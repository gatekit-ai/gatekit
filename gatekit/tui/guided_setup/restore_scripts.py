"""Restore script generation - create scripts to revert to original MCP client configs."""

import platform
import shlex
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .models import DetectedClient, DetectedServer, ClientType, ServerScope
from . import client_registry


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


def generate_restore_scripts(
    detected_clients: List[DetectedClient],
    restore_dir: Path,
) -> Dict[ClientType, Path]:
    """Generate restore scripts for all detected clients.

    Creates platform-appropriate restore scripts:
    - Claude Desktop: .txt file with manual instructions (all platforms)
    - Claude Code: .sh for POSIX, .txt for Windows
    - Codex: .sh for POSIX, .txt for Windows
    - Cursor: .txt file with manual instructions (all platforms)
    - Windsurf: .txt file with manual instructions (all platforms)

    Filenames include timestamp: restore-{client}-{YYYYMMDD}_{HHMMSS}.{ext}

    Args:
        detected_clients: List of detected MCP clients
        restore_dir: Directory to save restore scripts

    Returns:
        Dict mapping client type to restore script path
    """
    restore_dir.mkdir(parents=True, exist_ok=True)
    restore_scripts = {}

    # Generate timestamp once for all files in this run
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    for client in detected_clients:
        # Look up restore function from client registry
        registry_entry = client_registry.get_registry_entry(client.client_type)
        if registry_entry and registry_entry.restore_function:
            script_path = registry_entry.restore_function(client, restore_dir, timestamp)
            if script_path:
                restore_scripts[client.client_type] = script_path

    return restore_scripts


def _generate_claude_desktop_restore(
    client: DetectedClient,
    restore_dir: Path,
    timestamp: str,
) -> Path:
    """Generate Claude Desktop restore instructions (.txt file).

    Args:
        client: Detected Claude Desktop client
        restore_dir: Directory to save restore script
        timestamp: Timestamp string in YYYYMMDD_HHMMSS format

    Returns:
        Path to generated restore script
    """
    script_path = restore_dir / f"restore-claude-desktop-{timestamp}.txt"

    # Build JSON for original servers
    servers_json = _build_mcp_servers_json(client.servers)

    # Get absolute config path
    config_path = client.config_path.resolve()

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """
SECURITY WARNING: This file contains environment variables (API keys, tokens)
from your original configuration. Store this file securely.
"""

    content = f"""Gatekit Restore Instructions for Claude Desktop
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{security_warning}
To restore your original configuration:

1. Open your Claude Desktop config file:
   {config_path}

2. Replace the mcpServers section with this JSON:

{servers_json}

3. Restart Claude Desktop
"""

    script_path.write_text(content, encoding="utf-8")
    return script_path


def _generate_claude_code_restore(
    client: DetectedClient,
    restore_dir: Path,
    timestamp: str,
) -> Path:
    """Generate Claude Code restore script.

    Creates .sh for POSIX or .txt for Windows.

    Args:
        client: Detected Claude Code client
        restore_dir: Directory to save restore script
        timestamp: Timestamp string in YYYYMMDD_HHMMSS format

    Returns:
        Path to generated restore script
    """
    system = platform.system()
    is_windows = system == "Windows"

    if is_windows:
        script_path = restore_dir / f"restore-claude-code-{timestamp}.txt"
        content = _generate_claude_code_restore_windows(client)
    else:
        script_path = restore_dir / f"restore-claude-code-{timestamp}.sh"
        content = _generate_claude_code_restore_posix(client)

        # Make executable on POSIX
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    script_path.write_text(content, encoding="utf-8")
    return script_path


def _generate_claude_code_restore_posix(client: DetectedClient) -> str:
    """Generate Claude Code restore script for POSIX (bash).

    Args:
        client: Detected Claude Code client

    Returns:
        Bash script content
    """
    # Gatekit always uses user scope
    gatekit_scope_flag = "--scope user"

    # Build add commands with env vars - each server uses its own scope
    add_commands = []
    for server in client.servers:
        cmd = _build_claude_code_add_command_posix(server)
        add_commands.append(cmd)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Build restore section (only show "Restoring..." if there are servers)
    restore_section = ""
    if client.servers:
        restore_section = f"""echo "Restoring original servers..."
{chr(10).join(add_commands)}

"""

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """#
# SECURITY WARNING: This script contains environment variables (API keys, tokens)
# from your original configuration. Store this file securely."""

    return f"""#!/bin/bash
# Gatekit Restore Commands for Claude Code
# Generated: {timestamp}{security_warning}
#
# Run this script to restore your original MCP server configuration
# and remove Gatekit.

echo "Removing Gatekit..."
claude mcp remove gatekit {gatekit_scope_flag}

{restore_section}echo "Done! Restart Claude Code to see changes."
"""


def _generate_claude_code_restore_windows(client: DetectedClient) -> str:
    """Generate Claude Code restore instructions for Windows.

    Args:
        client: Detected Claude Code client

    Returns:
        Text file content with PowerShell commands
    """
    # Gatekit always uses user scope
    gatekit_scope_flag = "--scope user"

    # Build add commands with env vars - each server uses its own scope
    add_commands = []
    for server in client.servers:
        cmd = _build_claude_code_add_command_windows(server)
        add_commands.append(cmd)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Build restore section (only show "Restore..." if there are servers)
    restore_section = ""
    if client.servers:
        restore_section = f"""
# Restore original servers
{chr(10).join(add_commands)}
"""

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """
SECURITY WARNING: These commands contain environment variables (API keys, tokens)
from your original configuration. Store this file securely.
"""

    return f"""Gatekit Restore Commands for Claude Code (Windows)
Generated: {timestamp}{security_warning}
INSTRUCTIONS:
1. Open PowerShell (search for "PowerShell" in Start menu)
2. Copy the commands below
3. Paste into PowerShell window and press Enter
4. Restart Claude Code when complete

COMMANDS TO PASTE:

# Remove Gatekit
claude mcp remove gatekit {gatekit_scope_flag}{restore_section}

Write-Host "Done! Restart Claude Code to see changes."
"""


def _generate_codex_restore(
    client: DetectedClient,
    restore_dir: Path,
    timestamp: str,
) -> Path:
    """Generate Codex restore script.

    Creates .sh for POSIX or .txt for Windows.

    Args:
        client: Detected Codex client
        restore_dir: Directory to save restore script
        timestamp: Timestamp string in YYYYMMDD_HHMMSS format

    Returns:
        Path to generated restore script
    """
    system = platform.system()
    is_windows = system == "Windows"

    if is_windows:
        script_path = restore_dir / f"restore-codex-{timestamp}.txt"
        content = _generate_codex_restore_windows(client)
    else:
        script_path = restore_dir / f"restore-codex-{timestamp}.sh"
        content = _generate_codex_restore_posix(client)

        # Make executable on POSIX
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)
        return script_path

    script_path.write_text(content, encoding="utf-8")
    return script_path


def _generate_codex_restore_posix(client: DetectedClient) -> str:
    """Generate Codex restore script for POSIX (bash).

    Args:
        client: Detected Codex client

    Returns:
        Bash script content
    """
    # Build add commands with env vars
    add_commands = []
    for server in client.servers:
        cmd = _build_codex_add_command_posix(server)
        add_commands.append(cmd)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Build restore section (only show "Restoring..." if there are servers)
    restore_section = ""
    if client.servers:
        restore_section = f"""echo "Restoring original servers..."
{chr(10).join(add_commands)}

"""

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """#
# SECURITY WARNING: This script contains environment variables (API keys, tokens)
# from your original configuration. Store this file securely."""

    return f"""#!/bin/bash
# Gatekit Restore Commands for Codex
# Generated: {timestamp}{security_warning}

echo "Removing Gatekit..."
codex mcp remove gatekit

{restore_section}echo "Done! Restart Codex to see changes."
"""


def _generate_codex_restore_windows(client: DetectedClient) -> str:
    """Generate Codex restore instructions for Windows.

    Args:
        client: Detected Codex client

    Returns:
        Text file content with PowerShell commands
    """
    # Build add commands with env vars
    add_commands = []
    for server in client.servers:
        cmd = _build_codex_add_command_windows(server)
        add_commands.append(cmd)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Build restore section (only show "Restore..." if there are servers)
    restore_section = ""
    if client.servers:
        restore_section = f"""
# Restore original servers
{chr(10).join(add_commands)}
"""

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """
SECURITY WARNING: These commands contain environment variables (API keys, tokens)
from your original configuration. Store this file securely.
"""

    return f"""Gatekit Restore Commands for Codex (Windows)
Generated: {timestamp}{security_warning}
INSTRUCTIONS:
1. Open PowerShell (search for "PowerShell" in Start menu)
2. Copy the commands below
3. Paste into PowerShell window and press Enter
4. Restart Codex when complete

COMMANDS TO PASTE:

# Remove Gatekit
codex mcp remove gatekit{restore_section}

Write-Host "Done! Restart Codex to see changes."
"""


def _generate_cursor_restore(
    client: DetectedClient,
    restore_dir: Path,
    timestamp: str,
) -> Path:
    """Generate Cursor restore instructions (.txt file).

    Args:
        client: Detected Cursor client
        restore_dir: Directory to save restore script
        timestamp: Timestamp string in YYYYMMDD_HHMMSS format

    Returns:
        Path to generated restore script
    """
    script_path = restore_dir / f"restore-cursor-{timestamp}.txt"

    # Build JSON for original servers
    servers_json = _build_mcp_servers_json(client.servers)

    # Get absolute config path
    config_path = client.config_path.resolve()

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """
SECURITY WARNING: This file contains environment variables (API keys, tokens)
from your original configuration. Store this file securely.
"""

    content = f"""Gatekit Restore Instructions for Cursor
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{security_warning}
To restore your original configuration:

1. Open your Cursor config file:
   {config_path}

2. Replace the mcpServers section with this JSON:

{servers_json}

3. Restart Cursor
"""

    script_path.write_text(content, encoding="utf-8")
    return script_path


def _generate_windsurf_restore(
    client: DetectedClient,
    restore_dir: Path,
    timestamp: str,
) -> Path:
    """Generate Windsurf restore instructions (.txt file).

    Args:
        client: Detected Windsurf client
        restore_dir: Directory to save restore script
        timestamp: Timestamp string in YYYYMMDD_HHMMSS format

    Returns:
        Path to generated restore script
    """
    script_path = restore_dir / f"restore-windsurf-{timestamp}.txt"

    # Build JSON for original servers
    servers_json = _build_mcp_servers_json(client.servers)

    # Get absolute config path
    config_path = client.config_path.resolve()

    # Check if any server has env vars
    has_env_vars = any(server.has_env_vars() for server in client.servers)
    security_warning = ""
    if has_env_vars:
        security_warning = """
SECURITY WARNING: This file contains environment variables (API keys, tokens)
from your original configuration. Store this file securely.
"""

    content = f"""Gatekit Restore Instructions for Windsurf
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{security_warning}
To restore your original configuration:

1. Open your Windsurf config file:
   {config_path}

2. Replace the mcpServers section with this JSON:

{servers_json}

3. Restart Windsurf
"""

    script_path.write_text(content, encoding="utf-8")
    return script_path


def _build_mcp_servers_json(servers: List[DetectedServer]) -> str:
    """Build JSON representation of mcpServers section.

    Args:
        servers: List of detected servers

    Returns:
        Formatted JSON string
    """
    import json

    mcp_servers = {}
    for server in servers:
        # Reconstruct original server config from raw_config
        # This preserves the original structure and env vars
        # Use original_name if available (for renamed servers)
        server_name = server.original_name or server.name
        mcp_servers[server_name] = server.raw_config

    # Pretty-print JSON
    return json.dumps({"mcpServers": mcp_servers}, indent=2)


def _build_claude_code_add_command_posix(server: DetectedServer) -> str:
    """Build Claude Code add command for POSIX (bash).

    Uses backslash line continuation and proper shell quoting.

    Args:
        server: Detected server

    Returns:
        Bash command string
    """
    if not server.command:
        return f"# Skipping {server.name}: no command"

    # Get scope flag for this specific server
    scope_flag = _get_scope_flag(server)

    # Build base command - use original_name if available (for renamed servers)
    server_name = server.original_name or server.name
    cmd_parts = [f"claude mcp add --transport stdio {scope_flag} {server_name}"]

    # Add env vars if present with proper quoting
    if server.has_env_vars():
        for key, value in server.env.items():
            quoted_env = shlex.quote(f"{key}={value}")
            cmd_parts.append(f"  --env {quoted_env}")

    # Add server command with proper quoting for each argument
    cmd_parts.append("  --")
    for arg in server.command:
        quoted_arg = shlex.quote(str(arg))
        cmd_parts.append(f"  {quoted_arg}")

    # Join with backslash line continuation
    return " \\\n".join(cmd_parts)


def _build_claude_code_add_command_windows(server: DetectedServer) -> str:
    """Build Claude Code add command for Windows (PowerShell).

    Uses backtick line continuation and proper PowerShell quoting.

    Args:
        server: Detected server

    Returns:
        PowerShell command string
    """
    if not server.command:
        return f"# Skipping {server.name}: no command"

    # Get scope flag for this specific server
    scope_flag = _get_scope_flag(server)

    # Build base command - use original_name if available (for renamed servers)
    server_name = server.original_name or server.name
    cmd_parts = [f"claude mcp add --transport stdio {scope_flag} {server_name}"]

    # Add env vars if present with proper quoting
    if server.has_env_vars():
        for key, value in server.env.items():
            quoted_env = _quote_powershell(f"{key}={value}")
            cmd_parts.append(f"  --env {quoted_env}")

    # Add server command with proper quoting for each argument
    cmd_parts.append("  --")
    for arg in server.command:
        quoted_arg = _quote_powershell(str(arg))
        cmd_parts.append(f"  {quoted_arg}")

    # Join with backtick line continuation (PowerShell)
    return " `\n".join(cmd_parts)


def _build_codex_add_command_posix(server: DetectedServer) -> str:
    """Build Codex add command for POSIX (bash).

    Uses backslash line continuation and proper shell quoting.

    Args:
        server: Detected server

    Returns:
        Bash command string
    """
    if not server.command:
        return f"# Skipping {server.name}: no command"

    # Build base command - use original_name if available (for renamed servers)
    server_name = server.original_name or server.name
    cmd_parts = [f"codex mcp add {server_name}"]

    # Add env vars if present with proper quoting
    if server.has_env_vars():
        for key, value in server.env.items():
            quoted_env = shlex.quote(f"{key}={value}")
            cmd_parts.append(f"  --env {quoted_env}")

    # Add server command with proper quoting for each argument
    cmd_parts.append("  --")
    for arg in server.command:
        quoted_arg = shlex.quote(str(arg))
        cmd_parts.append(f"  {quoted_arg}")

    # Join with backslash line continuation
    return " \\\n".join(cmd_parts)


def _build_codex_add_command_windows(server: DetectedServer) -> str:
    """Build Codex add command for Windows (PowerShell).

    Uses backtick line continuation and proper PowerShell quoting.

    Args:
        server: Detected server

    Returns:
        PowerShell command string
    """
    if not server.command:
        return f"# Skipping {server.name}: no command"

    # Build base command - use original_name if available (for renamed servers)
    server_name = server.original_name or server.name
    cmd_parts = [f"codex mcp add {server_name}"]

    # Add env vars if present with proper quoting
    if server.has_env_vars():
        for key, value in server.env.items():
            quoted_env = _quote_powershell(f"{key}={value}")
            cmd_parts.append(f"  --env {quoted_env}")

    # Add server command with proper quoting for each argument
    cmd_parts.append("  --")
    for arg in server.command:
        quoted_arg = _quote_powershell(str(arg))
        cmd_parts.append(f"  {quoted_arg}")

    # Join with backtick line continuation (PowerShell)
    return " `\n".join(cmd_parts)


def _get_scope_flag(server: DetectedServer) -> str:
    """Get the --scope flag for a server based on its scope.

    Args:
        server: Detected server (must be from Claude Code with scope set)

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


# Register restore functions with client registry
# This allows the registry to be the single source of truth for client metadata
client_registry.register_restore_function(ClientType.CLAUDE_DESKTOP, _generate_claude_desktop_restore)
client_registry.register_restore_function(ClientType.CLAUDE_CODE, _generate_claude_code_restore)
client_registry.register_restore_function(ClientType.CODEX, _generate_codex_restore)
client_registry.register_restore_function(ClientType.CURSOR, _generate_cursor_restore)
client_registry.register_restore_function(ClientType.WINDSURF, _generate_windsurf_restore)


