"""Unit tests for MCPProxy notification handling functionality.

This module tests the proxy's ability to handle notifications from clients
and upstream servers, including plugin processing and error scenarios.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock

from gatekit.proxy.server import MCPProxy
from gatekit.config.models import (
    ProxyConfig,
    UpstreamConfig,
    PluginsConfig,
    PluginConfig,
    TimeoutConfig,
)
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    PipelineOutcome,
    ProcessingPipeline,
)
from tests.mocks.transport import MockTransport
from tests.mocks.notification_mock import NotificationCapableMock, NotificationScenarios


class MockStdioServerForNotifications:
    """Mock stdio server for notification tests."""

    def __init__(self):
        self._running = False
        self.notifications_sent = []

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False

    def is_running(self):
        return self._running

    async def handle_messages(self, request_handler, notification_handler=None):
        """Mock message handling."""
        pass

    async def write_notification(self, notification):
        """Track notifications sent to client."""
        self.notifications_sent.append(notification)


class TestProxyNotificationHandling:
    """Test MCPProxy notification handling."""

    @pytest.fixture
    def basic_config(self):
        """Create a basic proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["echo", "test"])],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(security={"_global": []}, auditing={"_global": []}),
        )

    @pytest.fixture
    def mock_stdio_server(self):
        """Create a mock stdio server."""
        return MockStdioServerForNotifications()

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport."""
        return MockTransport()

    @pytest.fixture
    def mock_server_manager(self, mock_transport):
        """Create a mock server manager with the given transport."""
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = mock_transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        return mock_server_manager

    @pytest.mark.asyncio
    async def test_handle_notification_basic(
        self, basic_config, mock_stdio_server, mock_transport, mock_server_manager
    ):
        """Test basic notification handling from client."""
        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None, pipeline_outcome=PipelineOutcome.ALLOWED
        )
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        # Connect transport
        await mock_transport.connect()

        # Create a notification
        notification = NotificationScenarios.initialized_notification()

        # Handle the notification
        await proxy.handle_notification(notification)

        # Verify notification was forwarded to upstream
        await asyncio.sleep(0.1)  # Let async operations complete

        # Check that notification was sent to transport
        sent_notification = await mock_transport.get_next_notification()
        assert sent_notification.method == "notifications/initialized"
        assert sent_notification.params == {}

        await mock_transport.disconnect()

    @pytest.mark.asyncio
    async def test_handle_notification_with_plugin_processing(
        self, basic_config, mock_stdio_server, mock_transport, mock_server_manager
    ):
        """Test notification processing through plugins."""
        # Add a security plugin to the config
        basic_config.plugins.security["_global"].append(
            PluginConfig(handler="test_security", config={"enabled": True})
        )

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None, pipeline_outcome=PipelineOutcome.ALLOWED
        )
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        await mock_transport.connect()

        # Create and handle notification
        notification = NotificationScenarios.log_message_notification(
            "info", "Test message"
        )
        await proxy.handle_notification(notification)

        # Verify plugin processing
        mock_plugin_manager.process_notification.assert_called_once_with(notification)
        mock_plugin_manager.log_notification.assert_called_once()

        # Verify notification was forwarded
        sent_notification = await mock_transport.get_next_notification()
        assert sent_notification.method == "notifications/message"

        await mock_transport.disconnect()

    @pytest.mark.asyncio
    async def test_handle_notification_blocked_by_plugin(
        self, basic_config, mock_stdio_server, mock_transport, mock_server_manager
    ):
        """Test notification blocked by security plugin."""
        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager to block notification
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None, pipeline_outcome=PipelineOutcome.BLOCKED
        )
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        await mock_transport.connect()

        # Create and handle notification
        notification = NotificationScenarios.log_message_notification(
            "error", "Password: secret123"
        )
        await proxy.handle_notification(notification)

        # Verify plugin processing
        mock_plugin_manager.process_notification.assert_called_once_with(notification)
        mock_plugin_manager.log_notification.assert_called_once()

        # Verify notification was NOT forwarded
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(mock_transport.get_next_notification(), timeout=0.5)

        await mock_transport.disconnect()

    @pytest.mark.asyncio
    async def test_handle_notification_modified_by_plugin(
        self, basic_config, mock_stdio_server, mock_transport, mock_server_manager
    ):
        """Test notification modified by security plugin."""
        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Create modified notification
        modified_notification = NotificationScenarios.log_message_notification(
            "error", "[REDACTED]"
        )

        # Mock plugin manager to modify notification
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            final_content=modified_notification,
        )
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        await mock_transport.connect()

        # Create and handle original notification
        original_notification = NotificationScenarios.log_message_notification(
            "error", "Password: secret123"
        )
        await proxy.handle_notification(original_notification)

        # Verify modified notification was forwarded
        sent_notification = await mock_transport.get_next_notification()
        assert sent_notification.method == "notifications/message"
        assert sent_notification.params["data"] == "[REDACTED]"

        await mock_transport.disconnect()

    @pytest.mark.asyncio
    async def test_handle_notification_error_handling(
        self, basic_config, mock_stdio_server, mock_transport, mock_server_manager
    ):
        """Test error handling in notification processing."""
        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager to raise an error
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.side_effect = Exception("Plugin error")
        proxy._plugin_manager = mock_plugin_manager

        await mock_transport.connect()

        # Create and handle notification - should not raise
        notification = NotificationScenarios.initialized_notification()
        await proxy.handle_notification(notification)  # Should handle error gracefully

        # Verify no notification was forwarded due to error
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(mock_transport.get_next_notification(), timeout=0.5)

        await mock_transport.disconnect()

    @pytest.mark.asyncio
    async def test_listen_for_upstream_notifications(
        self, basic_config, mock_stdio_server
    ):
        """Test the upstream notification listener background task."""
        # Create a notification-capable mock
        notification_mock = NotificationCapableMock()

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = notification_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        mock_plugin_manager.process_notification.return_value = ProcessingPipeline(
            original_content=None, pipeline_outcome=PipelineOutcome.ALLOWED
        )
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        await notification_mock.connect()

        # Start the listener task
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send some notifications from upstream
        await notification_mock.send_server_notification(
            NotificationScenarios.progress_notification("op1", 50)
        )
        await notification_mock.send_server_notification(
            NotificationScenarios.resource_change_notification("tools")
        )

        # Give listener time to process
        await asyncio.sleep(0.2)

        # Stop the proxy
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify notifications were processed
        assert mock_plugin_manager.process_notification.call_count == 2
        assert mock_plugin_manager.log_notification.call_count == 2

        # Verify notifications were forwarded to client
        assert len(mock_stdio_server.notifications_sent) == 2
        assert (
            mock_stdio_server.notifications_sent[0].method == "notifications/progress"
        )
        assert (
            mock_stdio_server.notifications_sent[1].method
            == "notifications/tools/list_changed"
        )

        await notification_mock.disconnect()

    @pytest.mark.asyncio
    async def test_upstream_notification_error_recovery(
        self, basic_config, mock_stdio_server
    ):
        """Test error recovery in upstream notification listener."""
        notification_mock = NotificationCapableMock()

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = notification_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}

        proxy = MCPProxy(
            basic_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Mock plugin manager that fails on first notification
        mock_plugin_manager = AsyncMock(spec=PluginManager)
        call_count = 0

        async def process_with_error(notification, server_name=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("First notification fails")
            return ProcessingPipeline(
                original_content=None, pipeline_outcome=PipelineOutcome.ALLOWED
            )

        mock_plugin_manager.process_notification.side_effect = process_with_error
        mock_plugin_manager.log_notification = AsyncMock()
        proxy._plugin_manager = mock_plugin_manager

        await notification_mock.connect()

        # Start the listener task
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send notifications
        await notification_mock.send_server_notification(
            NotificationScenarios.initialized_notification()  # This will fail
        )
        await notification_mock.send_server_notification(
            NotificationScenarios.progress_notification(
                "op2", 100
            )  # This should succeed
        )

        # Give listener time to process
        await asyncio.sleep(0.2)

        # Stop the proxy
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify both notifications were attempted
        assert mock_plugin_manager.process_notification.call_count == 2

        # Only the second notification should be forwarded
        assert len(mock_stdio_server.notifications_sent) == 1
        assert (
            mock_stdio_server.notifications_sent[0].method == "notifications/progress"
        )

        await notification_mock.disconnect()


# Note: NotificationScenarios.progress_notification and
# NotificationScenarios.resource_change_notification are already defined
# in tests/mocks/notification_mock.py
