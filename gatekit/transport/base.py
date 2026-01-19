# filepath: /Users/dbright/mcp/gatekit/gatekit/transport/base.py
"""Abstract base class for MCP transport implementations.

This module defines the Transport interface that all MCP transport
implementations must follow.
"""

from abc import ABC, abstractmethod

from ..protocol.messages import MCPRequest, MCPResponse, MCPNotification


class Transport(ABC):
    """Abstract base class for MCP transport implementations.

    Transport classes handle the communication layer between the MCP gateway
    and upstream MCP servers. This includes connection management, message
    serialization/deserialization, and error handling.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the MCP server.

        Raises:
            RuntimeError: If connection fails or already connected
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the MCP server.

        Should be safe to call even if not connected.
        Performs cleanup of any resources (processes, sockets, etc.).
        """
        pass

    @abstractmethod
    async def send_message(self, message: MCPRequest) -> None:
        """Send a message to the MCP server.

        Args:
            message: The MCP request message to send

        Raises:
            RuntimeError: If not connected or send fails
        """
        pass

    @abstractmethod
    async def send_notification(self, notification: MCPNotification) -> None:
        """Send a notification to the MCP server.

        Args:
            notification: The MCP notification message to send

        Raises:
            RuntimeError: If not connected or send fails
        """
        pass

    @abstractmethod
    async def receive_message(self) -> MCPResponse:
        """Receive a message from the MCP server.

        Returns:
            The received MCP response message (may contain error field)

        Raises:
            RuntimeError: If not connected, receive fails, or message is invalid
        """
        pass

    @abstractmethod
    async def get_next_notification(self) -> MCPNotification:
        """Get next notification from the notification queue.

        Returns:
            The next available notification from the upstream server

        Raises:
            RuntimeError: If not connected or transport stopped
        """
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is currently connected.

        Returns:
            True if connected, False otherwise
        """
        pass

    @abstractmethod
    async def send_and_receive(self, request: MCPRequest) -> MCPResponse:
        """Send a request and wait for its specific response.

        This method ensures correct request/response correlation for concurrent requests.
        Each implementation MUST ensure the returned response corresponds to the
        specific request ID, not just any available response.

        Args:
            request: The MCP request to send

        Returns:
            The specific response for this request

        Raises:
            RuntimeError: If not connected or request fails
            asyncio.TimeoutError: If response timeout occurs
        """
        pass

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()
