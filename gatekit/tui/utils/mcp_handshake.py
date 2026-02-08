"""Shared MCP handshake utilities for testing server connections.

This module provides reusable functions for performing MCP handshakes
and tool discovery that can be used by both the config editor and
guided setup workflows.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, Tuple

from gatekit.transport.stdio import StdioTransport
from gatekit.transport.http import StreamableHttpTransport
from gatekit.transport.base import Transport
from gatekit.protocol.messages import MCPRequest, MCPNotification
from gatekit._version import __version__
from ..debug import get_debug_logger

logger = logging.getLogger(__name__)


async def handshake_upstream(
    command: Optional[list[str]] = None,
    url: Optional[str] = None,
    tls_verify: bool = True,
    timeout: float = 30.0,
    sandbox_config: Optional[Any] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Perform a lightweight MCP handshake and fetch tool metadata.

    Supports both stdio and HTTP transports. Exactly one of `command` or `url`
    must be provided.

    Args:
        command: Command to launch the MCP server (for stdio transport)
        url: URL of the MCP server endpoint (for HTTP transport)
        tls_verify: Whether to verify TLS certificates (default True)
        timeout: Timeout in seconds for both handshake and tools fetch (default: 30.0)
        sandbox_config: Optional SandboxConfig for OS-native process isolation (stdio only)

    Returns:
        Tuple of (server_identity, tools_payload) where:
        - server_identity: Server name from initialize response, or None if failed
        - tools_payload: Dict with keys 'tools', 'status', 'message', or None if connection failed

    Raises:
        ValueError: If neither command nor url is provided, or if both are provided

    Example:
        >>> # Stdio transport
        >>> identity, tools = await handshake_upstream(command=["npx", "-y", "@modelcontextprotocol/server-everything"])
        >>> if identity:
        ...     print(f"Connected to {identity}, found {len(tools['tools'])} tools")

        >>> # HTTP transport
        >>> identity, tools = await handshake_upstream(url="https://example.com/mcp")
    """
    # Validate that exactly one of command or url is provided
    if command is None and url is None:
        raise ValueError("Either command or url must be provided for handshake")
    if command is not None and url is not None:
        raise ValueError("Only one of command or url should be provided, not both")

    debug_logger = get_debug_logger()
    transport_type = "http" if url else "stdio"
    connection_str = url if url else " ".join(command)

    # Log handshake start
    if debug_logger:
        debug_logger.log_event(
            "mcp_handshake_start",
            context={
                "transport_type": transport_type,
                "connection": connection_str,
                "timeout": timeout,
            },
        )

    # Create appropriate transport
    transport: Transport
    if url:
        transport = StreamableHttpTransport(
            url=url,
            tls_verify=tls_verify,
        )
    else:
        transport = StdioTransport(command=command, sandbox_config=sandbox_config)

    stderr_output: list[str] = []

    try:
        await transport.connect()

        # Perform MCP initialize handshake
        init_request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="gatekit-handshake",
            params={
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "gatekit", "version": __version__},
            },
        )

        try:
            response = await asyncio.wait_for(
                transport.send_and_receive(init_request), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.debug("Timeout during handshake with %s: %s", transport_type, connection_str)
            # Capture stderr before returning (only for stdio)
            if hasattr(transport, "get_stderr_output"):
                stderr_output = transport.get_stderr_output()
            if debug_logger:
                debug_logger.log_event(
                    "mcp_handshake_timeout",
                    context={
                        "transport_type": transport_type,
                        "connection": connection_str,
                        "timeout": timeout,
                        "stderr_lines": stderr_output,
                        "stderr_text": "\n".join(stderr_output) if stderr_output else None,
                    },
                )
            error_msg = f"Timeout after {timeout}s"
            if stderr_output:
                error_msg += f". Server stderr: {' | '.join(stderr_output)}"
            return None, {
                "tools": [],
                "status": "error",
                "message": error_msg,
            }

        if response and response.result:
            server_info = response.result.get("serverInfo", {})
            identity = server_info.get("name")

            if identity:
                logger.debug(
                    "Discovered server identity '%s' for %s: %s",
                    identity,
                    transport_type,
                    connection_str,
                )
                # Send initialized notification (required by MCP protocol)
                initialized_notification = MCPNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                    params={},
                )
                await transport.send_notification(initialized_notification)

                # Fetch tools list
                tools_payload = await fetch_tools_list(transport, timeout=timeout)

                # Log success
                if debug_logger:
                    debug_logger.log_event(
                        "mcp_handshake_success",
                        context={
                            "transport_type": transport_type,
                            "connection": connection_str,
                            "server_identity": identity,
                            "tools_count": len(tools_payload.get("tools", [])) if tools_payload else 0,
                        },
                    )

                return identity, tools_payload

        # Response didn't have expected result - this is an error condition
        if hasattr(transport, "get_stderr_output"):
            stderr_output = transport.get_stderr_output()
        if debug_logger:
            debug_logger.log_event(
                "mcp_handshake_failed",
                context={
                    "transport_type": transport_type,
                    "connection": connection_str,
                    "reason": "no_server_identity",
                    "response_has_result": bool(response and response.result),
                    "stderr_lines": stderr_output,
                    "stderr_text": "\n".join(stderr_output) if stderr_output else None,
                },
            )

        # Build error message based on what we received
        if not response:
            error_msg = "No response received from server."
        elif not response.result:
            error_msg = "Server response missing 'result' field. This may not be an MCP server."
        else:
            error_msg = "Server did not report an identity in its response."

        if stderr_output:
            error_msg += f" Server stderr: {' | '.join(stderr_output)}"

        return None, {
            "tools": [],
            "status": "error",
            "message": error_msg,
        }

    except Exception as exc:
        logger.debug("Handshake probe failed for %s %s: %s", transport_type, connection_str, exc)
        # Capture stderr on exception (only for stdio)
        if hasattr(transport, "get_stderr_output"):
            stderr_output = transport.get_stderr_output()
        if debug_logger:
            debug_logger.log_event(
                "mcp_handshake_exception",
                context={
                    "transport_type": transport_type,
                    "connection": connection_str,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "stderr_lines": stderr_output,
                    "stderr_text": "\n".join(stderr_output) if stderr_output else None,
                },
            )
        error_msg = str(exc)
        if stderr_output:
            error_msg += f". Server stderr: {' | '.join(stderr_output)}"
        return None, {
            "tools": [],
            "status": "error",
            "message": error_msg,
        }
    finally:
        try:
            await transport.disconnect()
        except Exception:
            pass


async def fetch_tools_list(
    transport: Transport,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Fetch tools/list metadata from a connected MCP server.

    Args:
        transport: Connected transport (StdioTransport or StreamableHttpTransport)
        timeout: Timeout in seconds for the tools/list request (default: 5.0)

    Returns:
        Dictionary with keys:
        - tools: List of tool dictionaries (empty if fetch failed)
        - status: One of 'ok', 'error', 'empty', 'invalid'
        - message: Error or status message (None if status is 'ok')

    Example:
        >>> tools_data = await fetch_tools_list(transport)
        >>> if tools_data['status'] == 'ok':
        ...     for tool in tools_data['tools']:
        ...         print(f"Found tool: {tool['name']}")
    """
    request = MCPRequest(
        jsonrpc="2.0",
        method="tools/list",
        id="gatekit-tools-probe",
        params={},
    )

    try:
        response = await asyncio.wait_for(
            transport.send_and_receive(request), timeout=timeout
        )
    except Exception as exc:
        return {
            "tools": [],
            "status": "error",
            "message": f"tools/list failed: {exc}",
        }

    if not response:
        return {
            "tools": [],
            "status": "empty",
            "message": "tools/list returned no response.",
        }

    # Check for error response from server
    if getattr(response, "error", None):
        error = response.error
        error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        return {
            "tools": [],
            "status": "error",
            "message": f"tools/list error: {error_msg}",
        }

    if not getattr(response, "result", None):
        return {
            "tools": [],
            "status": "empty",
            "message": "tools/list returned no result.",
        }

    result = response.result
    tools = result.get("tools") if isinstance(result, dict) else None

    if isinstance(tools, list):
        return {
            "tools": tools,
            "status": "ok",
            "message": None,
        }

    return {
        "tools": [],
        "status": "invalid",
        "message": "tools/list response missing 'tools' array.",
    }
