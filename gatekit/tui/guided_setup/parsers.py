"""Config file parsers for MCP clients (JSON and TOML formats)."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Fallback for Python 3.10

from .models import DetectedServer, TransportType, ServerScope


class ParserError(Exception):
    """Base exception for parser errors."""

    pass


class JSONConfigParser:
    """Parser for JSON-based MCP client configs (Claude Desktop, Claude Code, Cursor, Windsurf).

    Uses "mcpServers" key in JSON.
    """

    @staticmethod
    def parse_file(config_path: Path) -> Tuple[List[DetectedServer], List[str]]:
        """Parse JSON config file and extract MCP servers.

        Args:
            config_path: Path to JSON config file

        Returns:
            Tuple of (servers, errors):
                - servers: List of successfully parsed servers
                - errors: List of error messages for failed parsing attempts
        """
        servers = []
        errors = []

        try:
            # Use utf-8-sig to handle files with BOM (common on Windows)
            with open(config_path, "r", encoding="utf-8-sig") as f:
                config = json.load(f)
        except FileNotFoundError:
            errors.append(f"Config file not found: {config_path}")
            return servers, errors
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {config_path}: {e}")
            return servers, errors
        except Exception as e:
            errors.append(f"Failed to read {config_path}: {e}")
            return servers, errors

        # Extract mcpServers section
        mcp_servers = config.get("mcpServers", {})
        if not mcp_servers:
            # Not an error - just no servers configured
            return servers, errors

        if not isinstance(mcp_servers, dict):
            errors.append(f"mcpServers section is not a dict in {config_path}")
            return servers, errors

        # Parse each server
        for server_name, server_config in mcp_servers.items():
            try:
                server = JSONConfigParser._parse_server(server_name, server_config)
                servers.append(server)
            except Exception as e:
                errors.append(f"Failed to parse server '{server_name}': {e}")

        return servers, errors

    @staticmethod
    def _parse_server(server_name: str, config: Dict) -> DetectedServer:
        """Parse a single server entry from JSON config.

        Args:
            server_name: Name/identifier of the server
            config: Server configuration dict

        Returns:
            DetectedServer instance

        Raises:
            ParserError: If server config is invalid or unsupported
        """
        if not isinstance(config, dict):
            raise ParserError(f"Server config must be a dict, got {type(config)}")

        # Determine transport type
        has_command = "command" in config
        has_url = "url" in config

        if has_url:
            # HTTP/SSE transport (future support)
            # NOTE: Don't populate env{} for HTTP servers to avoid false "plaintext secrets" warnings.
            # Any env configuration is preserved in raw_config if needed later.
            return DetectedServer(
                name=server_name,
                transport=TransportType.HTTP,
                url=config.get("url"),
                env={},  # No actual secret values for HTTP servers
                raw_config=config,
            )
        elif has_command:
            # stdio transport
            command = config.get("command")
            args = config.get("args", [])

            if not isinstance(command, str):
                raise ParserError(f"command must be a string, got {type(command)}")
            if not isinstance(args, list):
                raise ParserError(f"args must be a list, got {type(args)}")

            # Build full command list [command, arg1, arg2, ...]
            full_command = [command] + args

            # Extract env vars (with actual values)
            env = config.get("env", {})
            if env and not isinstance(env, dict):
                raise ParserError(f"env must be a dict, got {type(env)}")

            return DetectedServer(
                name=server_name,
                transport=TransportType.STDIO,
                command=full_command,
                env=env,
                raw_config=config,
            )
        else:
            raise ParserError("Server must have either 'command' or 'url'")


class TOMLConfigParser:
    """Parser for TOML-based MCP client configs (Codex)."""

    @staticmethod
    def parse_file(config_path: Path) -> Tuple[List[DetectedServer], List[str]]:
        """Parse TOML config file and extract MCP servers.

        Args:
            config_path: Path to TOML config file

        Returns:
            Tuple of (servers, errors):
                - servers: List of successfully parsed servers
                - errors: List of error messages for failed parsing attempts
        """
        servers = []
        errors = []

        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
        except FileNotFoundError:
            errors.append(f"Config file not found: {config_path}")
            return servers, errors
        except Exception as e:
            errors.append(f"Failed to parse TOML in {config_path}: {e}")
            return servers, errors

        # Extract mcp_servers section (note: underscore, not hyphen)
        mcp_servers = config.get("mcp_servers", {})
        if not mcp_servers:
            # Not an error - just no servers configured
            return servers, errors

        if not isinstance(mcp_servers, dict):
            errors.append(f"mcp_servers section is not a dict in {config_path}")
            return servers, errors

        # Parse each server
        for server_name, server_config in mcp_servers.items():
            try:
                server = TOMLConfigParser._parse_server(server_name, server_config)
                servers.append(server)
            except Exception as e:
                errors.append(f"Failed to parse server '{server_name}': {e}")

        return servers, errors

    @staticmethod
    def _parse_server(server_name: str, config: Dict) -> DetectedServer:
        """Parse a single server entry from TOML config.

        Args:
            server_name: Name/identifier of the server
            config: Server configuration dict

        Returns:
            DetectedServer instance

        Raises:
            ParserError: If server config is invalid or unsupported
        """
        if not isinstance(config, dict):
            raise ParserError(f"Server config must be a dict, got {type(config)}")

        # Determine transport type
        has_command = "command" in config
        has_url = "url" in config

        if has_url:
            # HTTP/SSE transport (future support)
            # NOTE: bearer_token_env_var is the NAME of an env variable, not the actual secret.
            # We don't populate env{} to avoid false "plaintext secrets" warnings.
            # The bearer_token_env_var name is preserved in raw_config if needed later.
            return DetectedServer(
                name=server_name,
                transport=TransportType.HTTP,
                url=config.get("url"),
                env={},  # No actual secret values for HTTP servers
                raw_config=config,
            )
        elif has_command:
            # stdio transport
            command = config.get("command")
            args = config.get("args", [])

            if not isinstance(command, str):
                raise ParserError(f"command must be a string, got {type(command)}")
            if not isinstance(args, list):
                raise ParserError(f"args must be a list, got {type(args)}")

            # Build full command list [command, arg1, arg2, ...]
            full_command = [command] + args

            # Extract env vars (TOML inline table format)
            env = config.get("env", {})
            if env and not isinstance(env, dict):
                raise ParserError(f"env must be a dict, got {type(env)}")

            return DetectedServer(
                name=server_name,
                transport=TransportType.STDIO,
                command=full_command,
                env=env,
                raw_config=config,
            )
        else:
            raise ParserError("Server must have either 'command' or 'url'")


def detect_scope_from_path(config_path: Path) -> Optional[ServerScope]:
    """Detect Claude Code scope from config file path.

    Args:
        config_path: Path to the config file

    Returns:
        ServerScope if this is a Claude Code config, None otherwise
    """
    config_name = config_path.name

    if config_name == ".claude.json":
        # User-level config in home directory
        return ServerScope.USER
    elif config_name == ".mcp.json":
        # Project-level config
        return ServerScope.PROJECT

    return None
