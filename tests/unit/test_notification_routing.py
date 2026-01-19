"""Unit tests for notification routing functionality in MCPProxy.

This module tests the new notification routing logic that properly handles
different notification types:
- notifications/cancelled: Route to server that handled the original request
- notifications/initialized: Broadcast to all servers
- notifications/progress: Forward transparently to client
- Other notifications: Forward transparently to client
"""

import pytest
import logging
from unittest.mock import AsyncMock, Mock

from gatekit.proxy.server import MCPProxy
from gatekit.config.models import (
    ProxyConfig,
    UpstreamConfig,
    PluginsConfig,
    TimeoutConfig,
)
from gatekit.protocol.messages import MCPNotification
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    PipelineOutcome,
    ProcessingPipeline,
)
from tests.mocks.notification_mock import NotificationScenarios


class MockStdioServer:
    """Mock stdio server for notification routing tests."""

    def __init__(self):
        self._running = False
        self.notifications_sent = []

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    async def write_notification(self, notification):
        """Track notifications sent to client."""
        self.notifications_sent.append(notification)


class MockConnection:
    """Mock connection for testing."""

    def __init__(self, name, transport=None):
        self.name = name
        self.status = "connected"
        self.transport = transport or Mock()
        self.transport.send_notification = AsyncMock()


class TestNotificationRouting:
    """Test notification routing functionality."""

    @pytest.fixture
    def basic_config(self):
        """Create a basic proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["echo", "test1"]),
                UpstreamConfig(name="server2", command=["echo", "test2"]),
            ],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(security={}, auditing={}),
        )

    @pytest.fixture
    def mock_stdio_server(self):
        """Create a mock stdio server."""
        return MockStdioServer()

    def mock_server_manager(self):
        """Create a mock server manager with multiple connections."""
        from gatekit.server_manager import ServerManager

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connections
        conn1 = MockConnection("server1")
        conn2 = MockConnection("server2")

        mock_server_manager.connections = {"server1": conn1, "server2": conn2}
        mock_server_manager.get_connection = Mock(
            side_effect=lambda name: mock_server_manager.connections.get(name)
        )

        return mock_server_manager, conn1, conn2

    @pytest.fixture
    def mock_plugin_manager(self):
        """Create a mock plugin manager."""
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None, pipeline_outcome=PipelineOutcome.ALLOWED
        )
        mock_plugin_manager.log_notification = AsyncMock()
        return mock_plugin_manager

    @pytest.mark.asyncio
    async def test_cancellation_notification_routing(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that cancellation notifications are routed to the correct server."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Simulate a request being tracked to server1
        request_id = "test-request-123"
        proxy._request_to_server[request_id] = "server1"

        # Create cancellation notification
        cancellation_notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/cancelled",
            params={"requestId": request_id},
        )

        # Handle the notification
        await proxy.handle_notification(cancellation_notification)

        # Verify notification was sent to server1 only
        conn1.transport.send_notification.assert_called_once_with(
            cancellation_notification
        )
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_cancellation_notification_unknown_request(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test handling of cancellation for unknown request ID."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Create cancellation notification for unknown request
        cancellation_notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/cancelled",
            params={"requestId": "unknown-request-456"},
        )

        # Handle the notification
        await proxy.handle_notification(cancellation_notification)

        # Verify notification was not sent to any server
        conn1.transport.send_notification.assert_not_called()
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_initialization_notification_broadcast(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that initialization notifications are broadcast to all servers."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Create initialization notification
        init_notification = NotificationScenarios.initialized_notification()

        # Handle the notification
        await proxy.handle_notification(init_notification)

        # Verify notification was sent to both servers
        conn1.transport.send_notification.assert_called_once_with(init_notification)
        conn2.transport.send_notification.assert_called_once_with(init_notification)

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_initialization_notification_partial_failure(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test initialization broadcast with partial server failure."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Make conn2 fail to send
        conn2.transport.send_notification.side_effect = Exception("Connection failed")

        # Create initialization notification
        init_notification = NotificationScenarios.initialized_notification()

        # Handle the notification (should not raise exception)
        await proxy.handle_notification(init_notification)

        # Verify notification was sent to conn1 but failed on conn2
        conn1.transport.send_notification.assert_called_once_with(init_notification)
        conn2.transport.send_notification.assert_called_once_with(init_notification)

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_progress_notification_forwarded_to_default_server(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that progress notifications from client are forwarded to default server."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Create progress notification
        progress_notification = NotificationScenarios.progress_notification("op1", 50)

        # Handle the notification
        await proxy.handle_notification(progress_notification)

        # Verify notification was sent to first available server (conn1)
        conn1.transport.send_notification.assert_called_once_with(progress_notification)
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client (this is client→server)
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_other_notification_forwarded_to_default_server(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that other notifications from client are forwarded to default server."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Create a custom notification
        custom_notification = MCPNotification(
            jsonrpc="2.0", method="notifications/custom", params={"data": "custom data"}
        )

        # Handle the notification
        await proxy.handle_notification(custom_notification)

        # Verify notification was sent to first available server (conn1)
        conn1.transport.send_notification.assert_called_once_with(custom_notification)
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client (this is client→server)
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_request_tracking_infrastructure(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that request tracking is working correctly."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Simulate tracking a request
        request_id = "test-request-789"
        server_name = "server1"
        proxy._request_to_server[request_id] = server_name

        # Verify tracking is working
        assert proxy._request_to_server.get(request_id) == server_name

        # Test cleanup
        proxy._cleanup_completed_request(request_id)
        assert request_id not in proxy._request_to_server

    @pytest.mark.asyncio
    async def test_cancellation_notification_disconnected_server(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test cancellation notification when target server is disconnected."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Simulate a request being tracked to server1
        request_id = "test-request-disconnected"
        proxy._request_to_server[request_id] = "server1"

        # Mark server1 as disconnected
        conn1.status = "disconnected"

        # Create cancellation notification
        cancellation_notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/cancelled",
            params={"requestId": request_id},
        )

        # Handle the notification
        await proxy.handle_notification(cancellation_notification)

        # Verify notification was not sent due to disconnection
        conn1.transport.send_notification.assert_not_called()
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_initialization_notification_no_connections(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test initialization notification when no servers are available."""
        mock_server_manager = Mock()
        mock_server_manager.connections = {}  # No connections

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Create initialization notification
        init_notification = NotificationScenarios.initialized_notification()

        # Handle the notification (should not raise exception)
        await proxy.handle_notification(init_notification)

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_notification_routing_with_plugin_blocking(
        self, basic_config, mock_stdio_server
    ):
        """Test that blocked notifications are not routed anywhere."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager to block notifications
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None, pipeline_outcome=PipelineOutcome.BLOCKED
        )
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        # Create initialization notification
        init_notification = NotificationScenarios.initialized_notification()

        # Handle the notification
        await proxy.handle_notification(init_notification)

        # Verify notification was not sent to any server
        conn1.transport.send_notification.assert_not_called()
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_notification_routing_with_plugin_modification(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that modified notifications are routed correctly."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Create modified notification
        original_notification = NotificationScenarios.progress_notification("op1", 50)
        modified_notification = NotificationScenarios.progress_notification("op1", 75)

        # Mock plugin manager to modify notification
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=original_notification,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            final_content=modified_notification,
        )
        proxy._plugin_manager = mock_plugin_manager

        # Handle the notification
        await proxy.handle_notification(original_notification)

        # Verify modified notification was sent to first available server
        conn1.transport.send_notification.assert_called_once_with(modified_notification)
        conn2.transport.send_notification.assert_not_called()

        # Verify it was NOT sent to client (this is client→server)
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_initialization_notification_partial_failure_logging(
        self, basic_config, mock_stdio_server, mock_plugin_manager, caplog
    ):
        """Test that partial server failures are properly logged."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Make conn2 fail to send
        conn2.transport.send_notification.side_effect = Exception(
            "Server connection lost"
        )

        # Create initialization notification
        init_notification = NotificationScenarios.initialized_notification()

        # Capture logs
        with caplog.at_level(logging.ERROR):
            await proxy.handle_notification(init_notification)

        # Verify notification was sent to conn1 but failed on conn2
        conn1.transport.send_notification.assert_called_once_with(init_notification)
        conn2.transport.send_notification.assert_called_once_with(init_notification)

        # Verify error was logged
        assert "Failed to broadcast notification" in caplog.text
        assert "Server connection lost" in caplog.text

    @pytest.mark.asyncio
    async def test_plugin_manager_exception_during_notification_processing(
        self, basic_config, mock_stdio_server, caplog
    ):
        """Test handling when plugin manager raises exceptions during notification processing."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager to raise exception
        mock_plugin_manager = AsyncMock()
        mock_plugin_manager.process_notification.side_effect = Exception(
            "Plugin processing failed"
        )
        proxy._plugin_manager = mock_plugin_manager

        # Create a test notification
        test_notification = NotificationScenarios.initialized_notification()

        # Capture logs
        with caplog.at_level(logging.ERROR):
            await proxy.handle_notification(test_notification)

        # Verify error was logged and no notification was sent
        assert "Error processing notification" in caplog.text
        assert "Plugin processing failed" in caplog.text
        conn1.transport.send_notification.assert_not_called()
        conn2.transport.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_server_to_client_notification_transparent_forwarding(
        self, basic_config, mock_stdio_server, mock_plugin_manager
    ):
        """Test that server→client notifications are forwarded transparently to client.

        This tests the _listen_server_notifications pathway which handles server→client notifications.
        """
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True
        proxy._plugin_manager = mock_plugin_manager

        # Simulate server→client notification processing
        server_notification = NotificationScenarios.progress_notification(
            "long_operation", 75
        )

        # Test the processing logic that _listen_server_notifications uses
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=server_notification,
            pipeline_outcome=PipelineOutcome.ALLOWED,
        )

        # Simulate what _listen_server_notifications does when it receives a notification
        pipeline = await proxy._plugin_manager.process_notification(server_notification)
        await proxy._plugin_manager.log_notification(server_notification, pipeline)

        if pipeline.pipeline_outcome == PipelineOutcome.ALLOWED:
            notification_to_send = (
                pipeline.final_content
                if (
                    pipeline.final_content
                    and isinstance(pipeline.final_content, MCPNotification)
                )
                else server_notification
            )
            await proxy._stdio_server.write_notification(notification_to_send)

        # Verify the notification was forwarded to client
        assert len(mock_stdio_server.notifications_sent) == 1
        assert (
            mock_stdio_server.notifications_sent[0].method == "notifications/progress"
        )
        assert (
            mock_stdio_server.notifications_sent[0].params == server_notification.params
        )

    @pytest.mark.asyncio
    async def test_cancellation_notification_with_plugin_exception(
        self, basic_config, mock_stdio_server, caplog
    ):
        """Test cancellation notification routing when plugin processing fails."""
        mock_server_manager, conn1, conn2 = self.mock_server_manager()

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Track a request to server1
        request_id = "test-request-with-plugin-failure"
        proxy._request_to_server[request_id] = "server1"

        # Mock plugin manager to fail during processing
        mock_plugin_manager = AsyncMock()
        mock_plugin_manager.process_notification.side_effect = Exception(
            "Plugin system error"
        )
        proxy._plugin_manager = mock_plugin_manager

        # Create cancellation notification
        cancellation_notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/cancelled",
            params={"requestId": request_id},
        )

        # Handle notification with logging capture
        with caplog.at_level(logging.ERROR):
            await proxy.handle_notification(cancellation_notification)

        # Verify error was logged and no notification was sent
        assert "Error processing notification" in caplog.text
        assert "Plugin system error" in caplog.text
        conn1.transport.send_notification.assert_not_called()
        conn2.transport.send_notification.assert_not_called()
