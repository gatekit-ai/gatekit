"""Minimal notification-capable mock for testing Gatekit notification handling.

This module provides a lightweight mock that can send and receive notifications
for testing purposes, leveraging the existing MockTransport infrastructure.
"""

import asyncio
from typing import List, Optional, Callable, Dict, Any, Tuple
from gatekit.protocol.messages import MCPNotification
from tests.mocks.transport import MockTransport


class NotificationCapableMock:
    """Minimal mock that can send/receive notifications for testing.

    This mock simulates both client and server notification capabilities,
    allowing tests to verify Gatekit's notification processing logic
    without needing a full MCP server implementation.
    """

    def __init__(
        self,
        notification_delay: float = 0.0,
        response_handler: Optional[Callable] = None,
    ):
        """Initialize the notification-capable mock.

        Args:
            notification_delay: Delay before sending notifications (for timing tests)
            response_handler: Optional custom handler for generating responses
        """
        self.transport = MockTransport(
            response_delay=notification_delay, response_handler=response_handler
        )

        # Track notifications for verification
        self.sent_notifications: List[MCPNotification] = []
        self.received_notifications: List[MCPNotification] = []

        # Notification generators
        self._notification_tasks: List[asyncio.Task] = []
        self._running = False

    async def connect(self) -> None:
        """Connect the mock transport."""
        await self.transport.connect()
        self._running = True

    async def disconnect(self) -> None:
        """Disconnect and cleanup."""
        self._running = False

        # Cancel all notification tasks
        for task in self._notification_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.transport.disconnect()

    async def send_client_notification(self, notification: MCPNotification) -> None:
        """Simulate a client sending a notification to the server.

        Args:
            notification: The notification to send
        """
        self.sent_notifications.append(notification)
        await self.transport.send_notification(notification)

    async def send_server_notification(self, notification: MCPNotification) -> None:
        """Simulate a server sending a notification to the client.

        This queues the notification to be received by the transport.

        Args:
            notification: The notification to send
        """
        # Use the new directional method if available, fallback to legacy
        if hasattr(self.transport, "send_server_notification"):
            await self.transport.send_server_notification(notification)
        else:
            # Fallback for backward compatibility
            await self.transport._notification_queue.put(notification)

    async def receive_notification(self) -> MCPNotification:
        """Receive a notification from the transport.

        Returns:
            The next available notification
        """
        notification = await self.transport.get_next_notification()
        self.received_notifications.append(notification)
        return notification

    async def receive_client_to_server_notification(self) -> MCPNotification:
        """Receive a client->server notification from the transport.

        Returns:
            The next available client->server notification
        """
        if hasattr(self.transport, "get_client_to_server_notification"):
            notification = await self.transport.get_client_to_server_notification()
        else:
            # Fallback to legacy method
            notification = await self.transport.get_next_notification()
        self.received_notifications.append(notification)
        return notification

    async def receive_server_to_client_notification(self) -> MCPNotification:
        """Receive a server->client notification from the transport.

        Returns:
            The next available server->client notification
        """
        if hasattr(self.transport, "get_server_to_client_notification"):
            notification = await self.transport.get_server_to_client_notification()
        else:
            # Fallback to legacy method
            notification = await self.transport.get_next_notification()
        self.received_notifications.append(notification)
        return notification

    async def start_periodic_notifications(
        self, method: str, interval: float = 1.0, count: Optional[int] = None
    ) -> None:
        """Start sending periodic notifications.

        Args:
            method: The notification method name
            interval: Seconds between notifications
            count: Number of notifications to send (None for infinite)
        """

        async def send_notifications():
            sent = 0
            while self._running and (count is None or sent < count):
                notification = MCPNotification(
                    jsonrpc="2.0",
                    method=method,
                    params={
                        "sequence": sent,
                        "timestamp": asyncio.get_event_loop().time(),
                    },
                )
                await self.send_server_notification(notification)
                sent += 1
                await asyncio.sleep(interval)

        task = asyncio.create_task(send_notifications())
        self._notification_tasks.append(task)

    async def simulate_progress_notifications(
        self, operation_id: str, steps: int = 10, interval: float = 0.1
    ) -> None:
        """Simulate progress notifications for a long-running operation.

        Args:
            operation_id: Unique identifier for the operation
            steps: Number of progress steps
            interval: Time between progress updates
        """

        async def send_progress():
            for i in range(steps + 1):
                if not self._running:
                    break

                progress = int((i / steps) * 100)
                notification = MCPNotification(
                    jsonrpc="2.0",
                    method="notifications/progress",
                    params={
                        "token": operation_id,
                        "value": progress,
                        "message": f"Processing... {progress}%",
                    },
                )
                await self.send_server_notification(notification)
                if i < steps:
                    await asyncio.sleep(interval)

        task = asyncio.create_task(send_progress())
        self._notification_tasks.append(task)

    async def simulate_resource_change_notifications(
        self, resource_type: str = "tools"
    ) -> None:
        """Simulate resource change notifications.

        Args:
            resource_type: Type of resource (tools, prompts, resources)
        """
        notification = MCPNotification(
            jsonrpc="2.0",
            method=f"notifications/{resource_type}/list_changed",
            params={},
        )
        await self.send_server_notification(notification)

    async def simulate_bidirectional_flow(
        self, client_to_server_count: int = 5, server_to_client_count: int = 5
    ) -> None:
        """Simulate bidirectional notification flow.

        Args:
            client_to_server_count: Number of client notifications
            server_to_client_count: Number of server notifications
        """
        # Send client notifications
        for i in range(client_to_server_count):
            notification = MCPNotification(
                jsonrpc="2.0",
                method="client/notification",
                params={"index": i, "direction": "client_to_server"},
            )
            await self.send_client_notification(notification)

        # Send server notifications
        for i in range(server_to_client_count):
            notification = MCPNotification(
                jsonrpc="2.0",
                method="server/notification",
                params={"index": i, "direction": "server_to_client"},
            )
            await self.send_server_notification(notification)

    def clear_history(self) -> None:
        """Clear notification history for fresh test scenarios."""
        self.sent_notifications.clear()
        self.received_notifications.clear()

    async def wait_for_notifications(
        self, count: int, timeout: float = 5.0
    ) -> List[MCPNotification]:
        """Wait for a specific number of notifications to be received.

        Args:
            count: Number of notifications to wait for
            timeout: Maximum time to wait

        Returns:
            List of received notifications

        Raises:
            asyncio.TimeoutError: If timeout is reached
        """
        notifications = []

        async def collect_notifications():
            for _ in range(count):
                notification = await self.receive_notification()
                notifications.append(notification)

        await asyncio.wait_for(collect_notifications(), timeout=timeout)
        return notifications

    async def simulate_error_notification(
        self, error_type: str = "connection_lost", after_count: int = 5
    ) -> None:
        """Simulate error notifications after a certain number of successful ones.

        Args:
            error_type: Type of error to simulate
            after_count: Number of successful notifications before error
        """

        async def send_with_error():
            for i in range(after_count):
                if not self._running:
                    break
                notification = MCPNotification(
                    jsonrpc="2.0",
                    method="test/notification",
                    params={"sequence": i, "status": "ok"},
                )
                await self.send_server_notification(notification)
                await asyncio.sleep(0.1)

            # Send error notification
            error_notification = MCPNotification(
                jsonrpc="2.0",
                method="notifications/error",
                params={
                    "error": error_type,
                    "message": f"Simulated {error_type} error",
                    "fatal": True,
                },
            )
            await self.send_server_notification(error_notification)

        task = asyncio.create_task(send_with_error())
        self._notification_tasks.append(task)

    async def simulate_burst_notifications(
        self, burst_size: int = 10, burst_count: int = 3, burst_interval: float = 1.0
    ) -> None:
        """Simulate bursts of notifications.

        Args:
            burst_size: Number of notifications per burst
            burst_count: Number of bursts
            burst_interval: Time between bursts
        """

        async def send_bursts():
            for burst_idx in range(burst_count):
                if not self._running:
                    break

                # Send a burst of notifications
                for i in range(burst_size):
                    notification = MCPNotification(
                        jsonrpc="2.0",
                        method="burst/notification",
                        params={
                            "burst": burst_idx,
                            "sequence": i,
                            "timestamp": asyncio.get_event_loop().time(),
                        },
                    )
                    await self.send_server_notification(notification)
                    # No delay within burst

                # Delay between bursts
                if burst_idx < burst_count - 1:
                    await asyncio.sleep(burst_interval)

        task = asyncio.create_task(send_bursts())
        self._notification_tasks.append(task)

    async def simulate_notification_with_delays(
        self, notifications: List[Tuple[MCPNotification, float]]
    ) -> None:
        """Send notifications with specific delays between them.

        Args:
            notifications: List of (notification, delay_after) tuples
        """

        async def send_with_delays():
            for notification, delay in notifications:
                if not self._running:
                    break
                await self.send_server_notification(notification)
                if delay > 0:
                    await asyncio.sleep(delay)

        task = asyncio.create_task(send_with_delays())
        self._notification_tasks.append(task)

    async def simulate_mixed_message_flow(
        self, include_malformed: bool = False
    ) -> None:
        """Simulate a mix of requests, responses, and notifications.

        Args:
            include_malformed: Whether to include malformed messages
        """
        # This simulates a more realistic scenario where different
        # message types are interleaved
        messages = []

        # Add various notification types
        messages.append(NotificationScenarios.initialized_notification())
        messages.append(NotificationScenarios.progress_notification("op1", 25))
        messages.append(
            NotificationScenarios.log_message_notification("info", "Mixed flow test")
        )

        if include_malformed:
            # Add a malformed notification (missing required fields)
            malformed = {
                "jsonrpc": "2.0",
                # Missing method field
                "params": {"test": "malformed"},
            }
            # Send raw to transport to simulate malformed data from server
            if hasattr(self.transport, "_server_to_client_notifications"):
                await self.transport._server_to_client_notifications.put(malformed)
            else:
                await self.transport._notification_queue.put(malformed)

        # Send all valid notifications
        for notification in messages:
            await self.send_server_notification(notification)
            await asyncio.sleep(0.05)

    def get_notification_stats(self) -> Dict[str, Any]:
        """Get statistics about notifications processed.

        Returns:
            Dictionary with notification statistics
        """
        sent_methods = [n.method for n in self.sent_notifications]
        received_methods = [n.method for n in self.received_notifications]

        return {
            "total_sent": len(self.sent_notifications),
            "total_received": len(self.received_notifications),
            "unique_sent_methods": list(set(sent_methods)),
            "unique_received_methods": list(set(received_methods)),
            "sent_method_counts": {
                method: sent_methods.count(method) for method in set(sent_methods)
            },
            "received_method_counts": {
                method: received_methods.count(method)
                for method in set(received_methods)
            },
        }


class NotificationScenarios:
    """Common notification scenarios for testing."""

    @staticmethod
    def initialized_notification() -> MCPNotification:
        """Create an initialized notification."""
        return MCPNotification(
            jsonrpc="2.0", method="notifications/initialized", params={}
        )

    @staticmethod
    def cancelled_notification(
        request_id: str, reason: str = "User cancelled"
    ) -> MCPNotification:
        """Create a cancellation notification."""
        return MCPNotification(
            jsonrpc="2.0",
            method="notifications/cancelled",
            params={"requestId": request_id, "reason": reason},
        )

    @staticmethod
    def log_message_notification(level: str, message: str) -> MCPNotification:
        """Create a log message notification."""
        return MCPNotification(
            jsonrpc="2.0",
            method="notifications/message",
            params={"level": level, "logger": "test", "data": message},
        )

    @staticmethod
    def error_notification(
        error: str, details: Optional[Dict[str, Any]] = None
    ) -> MCPNotification:
        """Create an error notification."""
        return MCPNotification(
            jsonrpc="2.0",
            method="notifications/error",
            params={"error": error, "details": details or {}},
        )

    @staticmethod
    def progress_notification(operation_id: str, progress: int) -> MCPNotification:
        """Create a progress notification."""
        return MCPNotification(
            jsonrpc="2.0",
            method="notifications/progress",
            params={"token": operation_id, "value": progress},
        )

    @staticmethod
    def resource_change_notification(resource_type: str) -> MCPNotification:
        """Create a resource change notification."""
        return MCPNotification(
            jsonrpc="2.0",
            method=f"notifications/{resource_type}/list_changed",
            params={},
        )
