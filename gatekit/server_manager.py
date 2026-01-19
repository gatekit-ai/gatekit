"""Server Manager for handling multiple upstream MCP servers."""

from typing import Dict, List, Optional, Tuple
import asyncio
import logging
from dataclasses import dataclass

from gatekit.config.models import UpstreamConfig
from gatekit.transport.stdio import StdioTransport
from gatekit.transport.base import Transport
from gatekit.utils.namespacing import parse_namespaced_name
from gatekit._version import __version__

logger = logging.getLogger(__name__)


@dataclass
class ServerConnection:
    """Represents a connection to an upstream MCP server"""

    name: Optional[str]
    config: UpstreamConfig
    transport: Optional[Transport] = None
    status: str = "disconnected"  # connected, disconnected, reconnecting
    error: Optional[str] = None
    server_identity: Optional[str] = None  # Last known serverInfo.name from handshake
    _lock: Optional[asyncio.Lock] = None
    _reconnecting: bool = False
    _pending_requests: List = None

    def __post_init__(self):
        """Initialize connection with proper components."""
        if self._pending_requests is None:
            self._pending_requests = []

    @property
    def lock(self) -> asyncio.Lock:
        """Get or create the async lock for this connection."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock


class ServerManager:
    """Manages connections to multiple upstream MCP servers"""

    def __init__(self, configs: List[UpstreamConfig]):
        self.configs = configs
        self.connections: Dict[Optional[str], ServerConnection] = {}
        self._initialize_connections()

    def _initialize_connections(self):
        """Initialize connection tracking for all configured servers"""
        for config in self.configs:
            self.connections[config.name] = ServerConnection(
                name=config.name, config=config
            )

    def get_server_description(self, server_name: Optional[str]) -> str:
        """Get user-friendly server description for logging/errors."""
        return f"server '{server_name}'" if server_name else "unknown server"

    async def connect_all(self) -> Tuple[int, int]:
        """
        Connect to all configured servers.
        Returns: (successful_connections, failed_connections)
        """
        tasks = []
        for _name, conn in self.connections.items():
            tasks.append(self._connect_server(conn))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = sum(1 for r in results if r is True)
        failed = len(results) - successful

        # Collect error details for better error messages
        error_details = []
        for conn in self.connections.values():
            if conn.error:
                server_desc = self.get_server_description(conn.name)
                error_details.append(f"{server_desc}: {conn.error}")

        error_summary = "; ".join(error_details) if error_details else None

        if successful == 0:
            logger.warning(
                f"No upstream servers connected successfully: {error_summary}"
            )
        elif failed > 0:
            logger.warning(f"Connected to {successful} servers, {failed} failed")

        return successful, failed

    def get_connection_errors(self) -> Optional[str]:
        """Get detailed error messages from failed connections."""
        error_details = []
        for conn in self.connections.values():
            if conn.error:
                server_desc = self.get_server_description(conn.name)
                error_details.append(f"{server_desc}: {conn.error}")
        return "; ".join(error_details) if error_details else None

    async def _connect_server(self, conn: ServerConnection) -> bool:
        """Connect to a single server. Returns True if successful."""
        try:
            server_desc = self.get_server_description(conn.name)
            logger.info(f"Connecting to {server_desc}")

            # Create transport based on config
            if conn.config.transport == "stdio":
                if not conn.config.command:
                    raise ValueError("stdio transport requires command")
                transport = StdioTransport(command=conn.config.command)
            else:
                raise NotImplementedError(
                    f"Transport {conn.config.transport} not implemented"
                )

            # Connect and initialize
            await transport.connect()

            # Send initialize request to establish connection
            from gatekit.protocol.messages import MCPRequest

            init_request = MCPRequest(
                jsonrpc="2.0",
                method="initialize",
                id=1,
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "gatekit", "version": __version__},
                },
            )
            response = await transport.send_and_receive(init_request)

            if response.result is not None:
                # Initialize succeeded - connection established
                server_info = response.result.get("serverInfo", {})
                server_name = server_info.get("name", "unknown")
                server_version = server_info.get("version", "unknown")

                conn.server_identity = server_name if server_name != "unknown" else None

                conn.transport = transport
                conn.status = "connected"
                conn.error = None

                # Log successful connection
                logger.info(
                    f"Successfully connected to {server_desc} ({server_name} v{server_version})"
                )

                return True
            else:
                raise Exception(
                    f"Invalid initialize response: {response.error or 'No result'}"
                )

        except Exception as e:
            conn.status = "disconnected"
            conn.error = str(e)
            logger.exception(f"Failed to connect to {server_desc}: {e}")
            return False

    async def reconnect_server(self, server_name: Optional[str]) -> bool:
        """Attempt to reconnect to a specific server with proper locking"""
        conn = self.connections.get(server_name)
        if not conn:
            return False

        # Use connection lock to prevent concurrent reconnection attempts
        async with conn.lock:
            return await self._reconnect_server_internal(server_name)

    async def _reconnect_server_internal(self, server_name: Optional[str]) -> bool:
        """Internal reconnection method without locking (assumes lock is held)"""
        conn = self.connections.get(server_name)
        if not conn:
            return False

        # Double-check connection status under lock
        if conn.status == "connected":
            return True

        # Check if already reconnecting
        if conn._reconnecting:
            # Wait for reconnection to complete
            while conn._reconnecting:
                await asyncio.sleep(0.01)
            return conn.status == "connected"

        # Mark as reconnecting
        conn._reconnecting = True
        conn.status = "reconnecting"

        try:
            # Cleanup old transport if exists
            if conn.transport:
                await conn.transport.disconnect()
                conn.transport = None

            # Try to connect
            result = await self._connect_server(conn)
            return result
        finally:
            conn._reconnecting = False
            if conn.status == "reconnecting":
                conn.status = "disconnected"

    def get_connection(self, server_name: Optional[str]) -> Optional[ServerConnection]:
        """Get connection for a specific server"""
        return self.connections.get(server_name)

    def extract_server_name(self, namespaced_name: str) -> Tuple[Optional[str], str]:
        """
        Extract server name and original name from a namespaced identifier.
        Returns: (server_name, original_name)
        """
        return parse_namespaced_name(namespaced_name)

    async def disconnect_all(self):
        """Disconnect from all servers"""
        tasks = []
        for conn in self.connections.values():
            if conn.transport:
                tasks.append(conn.transport.disconnect())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Reset all connections
        for conn in self.connections.values():
            conn.transport = None
            conn.status = "disconnected"
            conn.capabilities = None
