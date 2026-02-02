"""Server Manager for handling multiple upstream MCP servers."""

from typing import Dict, List, Optional, Tuple
import asyncio
import logging
from dataclasses import dataclass

from gatekit.config.models import UpstreamConfig
from gatekit.transport.stdio import StdioTransport
from gatekit.transport.http import StreamableHttpTransport
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

    def __init__(
        self,
        configs: List[UpstreamConfig],
        request_timeout: int = 60,
    ):
        """Initialize server manager.

        Args:
            configs: List of upstream server configurations
            request_timeout: Timeout for individual requests in seconds (default 60)
        """
        self.configs = configs
        self.connections: Dict[Optional[str], ServerConnection] = {}
        self._request_timeout = request_timeout
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
        Connect to all enabled servers.
        Disabled servers are kept in connections but not connected.
        Returns: (successful_connections, failed_connections)
        """
        tasks = []
        enabled_conns = []
        disabled_count = 0

        for _name, conn in self.connections.items():
            if conn.config.enabled:
                tasks.append(self._connect_server(conn))
                enabled_conns.append(conn)
            else:
                disabled_count += 1

        if disabled_count > 0:
            logger.debug(f"Skipping {disabled_count} disabled server(s) during connect_all")

        if not tasks:
            logger.warning("No enabled servers to connect")
            return 0, 0

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = sum(1 for r in results if r is True)
        failed = len(results) - successful

        # Collect error details for better error messages
        error_details = []
        for conn in enabled_conns:
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

    def _create_transport(self, config: UpstreamConfig) -> Transport:
        """Create transport based on upstream configuration.

        Args:
            config: Upstream server configuration

        Returns:
            Configured transport instance

        Raises:
            ValueError: If transport configuration is invalid
            NotImplementedError: If transport type is not supported
        """
        if config.transport == "http":
            if not config.url:
                raise ValueError("http transport requires url")
            return StreamableHttpTransport(
                url=config.url,
                tls_verify=config.tls_verify,
                request_timeout=float(self._request_timeout),
            )
        elif config.transport == "stdio":
            if not config.command:
                raise ValueError("stdio transport requires command")
            return StdioTransport(
                command=config.command,
                request_timeout=self._request_timeout,
            )
        else:
            raise NotImplementedError(f"Transport {config.transport} not implemented")

    async def _connect_server(self, conn: ServerConnection) -> bool:
        """Connect to a single server. Returns True if successful."""
        try:
            server_desc = self.get_server_description(conn.name)
            logger.info(f"Connecting to {server_desc}")

            # Create transport based on config
            transport = self._create_transport(conn.config)

            # Connect and initialize
            await transport.connect()

            # Send initialize request to establish connection
            from gatekit.protocol.messages import MCPRequest, MCPNotification

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
                # Initialize succeeded - send notifications/initialized to complete handshake
                initialized_notification = MCPNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                    params={},
                )
                await transport.send_notification(initialized_notification)

                # Extract server info
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

        # Don't reconnect disabled servers
        if not conn.config.enabled:
            logger.debug(f"Server '{server_name}' is disabled, not reconnecting")
            return False

        # Double-check connection status under lock
        if conn.status == "connected":
            return True

        # Check if already reconnecting
        if conn._reconnecting:
            # Wait for reconnection to complete (with timeout to prevent deadlock)
            max_wait = 30.0  # 30 seconds max wait
            wait_time = 0.0
            while conn._reconnecting and wait_time < max_wait:
                await asyncio.sleep(0.01)
                wait_time += 0.01
            if wait_time >= max_wait:
                logger.warning(f"Timed out waiting for reconnection of server '{server_name}'")
                return False
            return conn.status == "connected"

        # Mark as reconnecting
        conn._reconnecting = True
        conn.status = "reconnecting"

        try:
            # Cleanup old transport if exists (always clear reference even on error)
            if conn.transport:
                try:
                    await conn.transport.disconnect()
                except Exception as e:
                    logger.warning(f"Error disconnecting old transport for '{server_name}': {e}")
                conn.transport = None  # Always clear to prevent leak

            # Try to connect
            result = await self._connect_server(conn)
            return result
        finally:
            conn._reconnecting = False
            if conn.status == "reconnecting":
                conn.status = "disconnected"

    def is_server_enabled(self, server_name: str) -> bool:
        """Check if a server is enabled in its config."""
        conn = self.connections.get(server_name)
        if conn:
            return conn.config.enabled
        return False

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
            conn.error = None

    # --- Hot-Reload Server Lifecycle Methods ---

    async def add_server(self, config: UpstreamConfig, connect: bool = True) -> bool:
        """Add a new server dynamically. Optionally connect if enabled.

        Args:
            config: Server configuration
            connect: If True and config.enabled, connect immediately

        Returns:
            True if server was added (and connected if requested)
        """
        if config.name in self.connections:
            return False  # Already exists

        conn = ServerConnection(name=config.name, config=config)
        self.connections[config.name] = conn

        # Only connect if requested AND enabled
        if connect and config.enabled:
            return await self._connect_server(conn)
        return True  # Added successfully (but not connected)

    async def remove_server(self, name: str) -> None:
        """Disconnect and remove a server. Waits for in-flight requests."""
        conn = self.connections.get(name)
        if conn:
            async with conn.lock:  # Wait for in-flight requests to complete
                if conn.transport:
                    try:
                        await conn.transport.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting server '{name}': {e}")
                    conn.transport = None
                    conn.status = "disconnected"
            self.connections.pop(name, None)

    async def disconnect_server(self, name: str) -> None:
        """Disconnect but keep server in connections (for enable/disable)."""
        conn = self.connections.get(name)
        if conn:
            async with conn.lock:  # Wait for in-flight requests
                if conn.transport:
                    try:
                        await conn.transport.disconnect()
                    except Exception as e:
                        logger.warning(f"Error disconnecting server '{name}': {e}")
                    conn.transport = None
                    conn.status = "disconnected"

    async def connect_server(self, name: str) -> bool:
        """Connect a previously disconnected server.

        If already connected, this is a no-op and returns True.
        """
        conn = self.connections.get(name)
        if not conn:
            return False

        # Guard against double-connect - don't leak transports
        if conn.status == "connected" and conn.transport:
            logger.debug(f"Server '{name}' already connected, skipping connect")
            return True

        return await self._connect_server(conn)

    async def update_server(self, config: UpstreamConfig) -> bool:
        """Update server config (reconnects if connection settings changed).

        Always updates conn.config. Reconnects only if transport/command/url/tls changed.
        """
        conn = self.connections.get(config.name)
        if not conn:
            return False

        # Check if reconnect needed (compare relevant fields)
        if self._needs_reconnect(conn.config, config):
            await self.remove_server(config.name)
            return await self.add_server(config)

        # ALWAYS update config reference (even if no reconnect needed)
        # This ensures non-connection settings (like enabled flag) are updated
        conn.config = config
        return True

    def _needs_reconnect(self, old: UpstreamConfig, new: UpstreamConfig) -> bool:
        """Check if config change requires reconnection."""
        return (
            old.transport != new.transport
            or old.command != new.command
            or old.url != new.url
            or old.tls_verify != new.tls_verify
        )
