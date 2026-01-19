"""Configuration generation for Gatekit from detected MCP clients."""

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import yaml

from gatekit.config.models import (
    UpstreamConfig,
    ProxyConfig,
    PluginConfig,
    PluginsConfig,
    TimeoutConfig,
    LoggingConfig,
)
from gatekit.config.serialization import config_to_dict
from ..platform_paths import get_user_log_dir
from .models import DetectedClient, DetectedServer


class ConfigGenerationResult:
    """Result of configuration generation with metadata."""

    def __init__(
        self,
        config: ProxyConfig,
        stdio_servers: List[DetectedServer],
        http_servers: List[DetectedServer],
        has_env_vars: bool,
    ):
        """Initialize config generation result.

        Args:
            config: Generated ProxyConfig
            stdio_servers: List of stdio servers included in config
            http_servers: List of HTTP/SSE servers skipped
            has_env_vars: Whether any servers had environment variables
        """
        self.config = config
        self.stdio_servers = stdio_servers
        self.http_servers = http_servers
        self.has_env_vars = has_env_vars

    def get_http_skip_message(self) -> Optional[str]:
        """Get informational message about skipped HTTP servers.

        Returns:
            Message string if HTTP servers were skipped, None otherwise
        """
        if not self.http_servers:
            return None

        server_names = ", ".join(s.name for s in self.http_servers)
        count = len(self.http_servers)
        return f"Found {count} HTTP/SSE servers ({server_names}) - skipped (not supported in this release)"

    def get_security_warning(self) -> Optional[str]:
        """Get security warning about environment variables.

        Returns:
            Warning message if env vars detected, None otherwise
        """
        if not self.has_env_vars:
            return None

        return (
            "Your configuration contains environment variables (API keys, tokens). "
            "These will be included in the Gatekit config in plaintext. "
            "Consider using a secrets manager for production use."
        )


def convert_detected_servers_to_upstreams(
    detected_servers: List[DetectedServer],
) -> List[UpstreamConfig]:
    """Convert detected servers to UpstreamConfig format.

    Only includes stdio servers. HTTP/SSE servers are filtered out.

    Args:
        detected_servers: List of detected servers from client configs

    Returns:
        List of UpstreamConfig instances (stdio only)
    """
    upstreams = []

    for server in detected_servers:
        # Filter: stdio only (HTTP/SSE not supported in MVP)
        if not server.is_stdio():
            continue

        # Create UpstreamConfig
        upstream = UpstreamConfig(
            name=server.name,
            transport="stdio",
            command=server.command,
            restart_on_failure=True,
            max_restart_attempts=3,
        )

        upstreams.append(upstream)

    return upstreams


def create_default_plugins_config() -> PluginsConfig:
    """Create default plugin configuration for generated configs.

    Default configuration (MVP):
    - Auditing: JSON lines logger only (minimal, observable)
    - Middleware: Call trace (diagnostic info appended to responses)
    - Security: None (explicit opt-in after users understand the tool)

    Returns:
        PluginsConfig with default auditing and middleware plugins
    """
    # Default auditing plugin: JSON lines logger
    # Note: auditing plugins don't have priority (unlike security/middleware)
    # Default output_file matches the plugin schema default (json_lines.py)
    audit_jsonl = PluginConfig(
        handler="audit_jsonl",
        config={
            "enabled": True,
            "output_file": "logs/gatekit_audit.jsonl",
        },
    )

    # Default middleware plugin: Call trace
    call_trace = PluginConfig(
        handler="call_trace",
        config={
            "enabled": True,
            "priority": 100,
            "max_param_length": 200,
        },
    )

    # Apply to _global scope
    plugins = PluginsConfig(
        auditing={"_global": [audit_jsonl]},
        security={},
        middleware={"_global": [call_trace]},
    )

    return plugins


def create_default_logging_config() -> LoggingConfig:
    """Create default logging configuration for generated configs.

    Default configuration enables file-only logging at INFO level.
    File logging uses the platform-appropriate log directory:
    - macOS: ~/Library/Logs/gatekit/
    - Linux: ~/.local/state/gatekit/
    - Windows: %LOCALAPPDATA%/gatekit/logs/

    Note: stderr logging is intentionally disabled by default because some MCP
    clients (notably Windsurf on Windows) appear to terminate the server process
    when stderr output is detected. The MCP specification explicitly allows
    stderr for logging, but file-only is the safest default for maximum client
    compatibility.

    Returns:
        LoggingConfig with file handler only
    """
    log_dir = get_user_log_dir("gatekit")
    log_file = log_dir / "gatekit.log"

    return LoggingConfig(
        level="INFO",
        handlers=["file"],
        file_path=str(log_file),
    )


def generate_gatekit_config(
    detected_clients: List[DetectedClient],
) -> ConfigGenerationResult:
    """Generate Gatekit configuration from detected MCP clients.

    Combines all stdio servers from all detected clients into a single
    Gatekit configuration with default plugin setup.

    Args:
        detected_clients: List of detected MCP clients with their servers

    Returns:
        ConfigGenerationResult with generated config and metadata

    Raises:
        ValueError: If no stdio servers found or server names conflict
    """
    # Collect all servers from all clients
    all_servers = []
    for client in detected_clients:
        all_servers.extend(client.servers)

    # Separate stdio and HTTP servers
    stdio_servers = [s for s in all_servers if s.is_stdio()]
    http_servers = [s for s in all_servers if s.is_http_based()]

    # Check if we have any stdio servers
    if not stdio_servers:
        raise ValueError(
            "No stdio servers found. "
            "HTTP/SSE servers are not supported in this release."
        )

    # Check for environment variables
    has_env_vars = any(s.has_env_vars() for s in stdio_servers)

    # Handle server name conflicts
    stdio_servers = _resolve_server_name_conflicts(stdio_servers, detected_clients)

    # Convert to UpstreamConfig format
    upstreams = convert_detected_servers_to_upstreams(stdio_servers)

    # Create default plugins config
    plugins = create_default_plugins_config()

    # Create default logging config
    logging = create_default_logging_config()

    # Create ProxyConfig with default timeouts
    proxy_config = ProxyConfig(
        transport="stdio",
        upstreams=upstreams,
        timeouts=TimeoutConfig(),  # Use defaults (60s connection, 60s request)
        plugins=plugins,
        logging=logging,
    )

    return ConfigGenerationResult(
        config=proxy_config,
        stdio_servers=stdio_servers,
        http_servers=http_servers,
        has_env_vars=has_env_vars,
    )


def _resolve_server_name_conflicts(
    servers: List[DetectedServer],
    clients: List[DetectedClient],
) -> List[DetectedServer]:
    """Resolve server name conflicts by adding client suffixes.

    If the same server name appears in multiple clients, rename them with
    client-specific suffixes to avoid conflicts.

    Args:
        servers: List of detected servers
        clients: List of detected clients (for context)

    Returns:
        List of servers with unique names
    """
    # Build a mapping of server name -> list of (server, client_type)
    name_to_servers: Dict[str, List[Tuple[DetectedServer, str]]] = {}

    for client in clients:
        for server in client.servers:
            if server not in servers:
                continue
            client_suffix = _get_client_suffix(client.client_type.value)
            if server.name not in name_to_servers:
                name_to_servers[server.name] = []
            name_to_servers[server.name].append((server, client_suffix))

    # Check for conflicts and rename
    result_servers = []
    for _server_name, server_client_pairs in name_to_servers.items():
        if len(server_client_pairs) == 1:
            # No conflict - use original name
            result_servers.append(server_client_pairs[0][0])
        else:
            # Conflict - add suffixes
            for server, client_suffix in server_client_pairs:
                # Create a copy with renamed server
                renamed_server = DetectedServer(
                    name=f"{server.name}-{client_suffix}",
                    transport=server.transport,
                    command=server.command,
                    url=server.url,
                    env=server.env,
                    scope=server.scope,
                    raw_config=server.raw_config,
                )
                result_servers.append(renamed_server)

    return result_servers


def _mask_env_value(key: str, value: str) -> str:
    """Mask sensitive environment variable values.

    Shows last 4 characters, masks rest.

    Args:
        key: Environment variable name
        value: Environment variable value

    Returns:
        Masked value like "********abc1"
    """
    if len(value) <= 4:
        return "********"
    return f"********{value[-4:]}"


def _collect_all_env_vars(servers: List[DetectedServer]) -> Tuple[Dict[str, str], List[str]]:
    """Collect environment variables from servers.

    Detects conflicts (same key, different values).
    Last server's value wins (deterministic if servers sorted by name).

    Args:
        servers: Detected servers (should be sorted by name)

    Returns:
        (merged_env_vars, conflict_warnings)
    """
    all_env_vars = {}
    conflicts = []
    env_sources = {}

    for server in servers:
        if server.has_env_vars():
            for key, value in server.env.items():
                if key in all_env_vars and all_env_vars[key] != value:
                    # Conflict detected
                    masked_existing = _mask_env_value(key, all_env_vars[key])
                    masked_new = _mask_env_value(key, value)
                    conflicts.append(
                        f"Environment variable '{key}' has different values:\n"
                        f"  • {env_sources[key]}: {masked_existing}\n"
                        f"  • {server.name}: {masked_new}\n"
                        f"  Using value from {server.name}"
                    )

                all_env_vars[key] = value
                env_sources[key] = server.name

    return all_env_vars, conflicts


def _get_client_suffix(client_type: str) -> str:
    """Get short suffix for client type.

    Args:
        client_type: Client type value (e.g., 'claude_desktop')

    Returns:
        Short suffix (e.g., 'desktop', 'code', 'codex')
    """
    suffixes = {
        "claude_desktop": "desktop",
        "claude_code": "code",
        "codex": "codex",
    }
    return suffixes.get(client_type, client_type)


def generate_config_header(stdio_servers: List[DetectedServer]) -> str:
    """Generate header comment for guided setup config files.

    Args:
        stdio_servers: List of detected servers (for env var detection)

    Returns:
        Header string with newline at end (ready to prepend to YAML)
    """
    has_env_vars = any(s.has_env_vars() for s in stdio_servers)

    header_lines = [
        "# Gatekit Configuration",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "#",
    ]

    if has_env_vars:
        header_lines.extend([
            "# WARNING: This configuration was generated from client configs that contain",
            "# environment variables (API keys, tokens). Per Gatekit's design, these",
            "# environment variables should be set in your MCP client configuration",
            "# (e.g., Claude Desktop's claude_desktop_config.json) or in your shell",
            "# environment before launching gatekit-gateway.",
            "#",
            "# Gatekit does NOT support an 'env' field in upstream configs.",
            "# The original servers from your detected clients should retain their",
            "# environment variables in the client configs.",
            "#",
        ])

    header_lines.append("")  # Empty line before YAML content

    return "\n".join(header_lines)


def generate_yaml_config(
    config: ProxyConfig,
    stdio_servers: List[DetectedServer],
) -> str:
    """Generate YAML representation of Gatekit config with comments.

    DEPRECATED: This function is maintained for backward compatibility.
    New code should use save_config() from gatekit.config.persistence
    with generate_config_header() for the header parameter.

    Includes:
    - Warning comment about plaintext secrets if env vars present
    - Standard config structure
    - Environment variables with actual values for stdio servers

    Args:
        config: ProxyConfig to serialize
        stdio_servers: Original detected servers (for env var extraction)

    Returns:
        YAML string representation of config
    """
    # Use shared serialization with draft validation disabled (guided setup configs are valid)
    config_dict = config_to_dict(config, validate_drafts=False)

    # Generate YAML
    yaml_str = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)

    # Generate header
    header = generate_config_header(stdio_servers)

    return header + yaml_str


def _find_server_by_name(
    servers: List[DetectedServer],
    name: str,
) -> Optional[DetectedServer]:
    """Find a server by name in the list.

    Handles renamed servers by checking both original and renamed names.

    Args:
        servers: List of detected servers
        name: Server name to find

    Returns:
        DetectedServer if found, None otherwise
    """
    # Direct name match
    for server in servers:
        if server.name == name:
            return server

    # Check if this is a renamed server (name contains suffix)
    # e.g., "filesystem-desktop" -> check for "filesystem"
    if "-" in name:
        base_name = name.rsplit("-", 1)[0]
        for server in servers:
            if server.name == base_name or server.name == name:
                return server

    return None
