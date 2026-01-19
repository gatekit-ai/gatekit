"""Integration tests for end-to-end notification flow.

This module tests the complete notification flow through Gatekit,
including client→proxy→server and server→proxy→client scenarios.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from gatekit.proxy.server import MCPProxy
from gatekit.config.models import (
    ProxyConfig,
    UpstreamConfig,
    TimeoutConfig,
    PluginsConfig,
    PluginConfig,
    LoggingConfig,
)
from gatekit.protocol.messages import MCPNotification
from tests.mocks.notification_mock import NotificationCapableMock, NotificationScenarios


class TestNotificationFlowIntegration:
    """Integration tests for notification flow through Gatekit."""

    @pytest.fixture
    def proxy_config(self):
        """Create proxy configuration with plugins."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["echo", "test"])],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(
                middleware={
                    "_global": [
                        PluginConfig(
                            handler="tool_manager",
                            config={"enabled": True, "tools": [{"tool": "read_file"}]},
                        )
                    ]
                },
                auditing={
                    "_global": [
                        PluginConfig(
                            handler="audit_jsonl",
                            config={
                                "enabled": True,
                                "output_file": "/tmp/test_audit.log",
                                "format": "json",
                                "include_notifications": True,
                                "critical": False,  # Allow /tmp path for testing
                            },
                        )
                    ]
                },
            ),
            logging=LoggingConfig(level="DEBUG"),
        )

    @pytest.mark.asyncio
    async def test_client_to_server_notification_flow(self, proxy_config):
        """Test notification flow from client to upstream server."""
        # Create notification mock as upstream
        upstream_mock = NotificationCapableMock()

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        # Create proxy with mock upstream transport
        proxy = MCPProxy(proxy_config, server_manager=mock_server_manager)

        # Start proxy
        proxy._is_running = True
        await upstream_mock.connect()

        # Simulate client sending notification
        client_notification = NotificationScenarios.initialized_notification()

        # Process through proxy
        await proxy.handle_notification(client_notification)

        # Give time for async processing
        await asyncio.sleep(0.1)

        # Verify upstream received the notification
        received = await upstream_mock.receive_notification()
        assert received.method == "notifications/initialized"
        assert received.params == {}

        # Cleanup
        await upstream_mock.disconnect()

    @pytest.mark.asyncio
    async def test_server_to_client_notification_flow(self, proxy_config):
        """Test notification flow from upstream server to client."""
        # Create notification mock as upstream
        upstream_mock = NotificationCapableMock()

        # Create mock stdio server to capture client notifications
        mock_stdio_server = MagicMock()
        mock_stdio_server.write_notification = AsyncMock()
        mock_stdio_server.is_running = MagicMock(return_value=True)

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        # Create proxy
        proxy = MCPProxy(
            proxy_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        await upstream_mock.connect()

        # Start upstream notification listener
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send notifications from upstream server
        await upstream_mock.send_server_notification(
            NotificationScenarios.progress_notification("operation1", 25)
        )
        await upstream_mock.send_server_notification(
            NotificationScenarios.progress_notification("operation1", 50)
        )
        await upstream_mock.send_server_notification(
            NotificationScenarios.progress_notification("operation1", 100)
        )

        # Give time for processing
        await asyncio.sleep(0.2)

        # Stop listener
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify client received all notifications
        assert mock_stdio_server.write_notification.call_count == 3

        # Check notification content
        calls = mock_stdio_server.write_notification.call_args_list
        assert calls[0][0][0].params["value"] == 25
        assert calls[1][0][0].params["value"] == 50
        assert calls[2][0][0].params["value"] == 100

        await upstream_mock.disconnect()

    @pytest.mark.asyncio
    async def test_bidirectional_notification_flow(self, proxy_config):
        """Test simultaneous bidirectional notification flow."""
        # Create notification mock as upstream
        upstream_mock = NotificationCapableMock()

        # Track notifications
        client_to_server_notifications = []
        server_to_client_notifications = []

        # Mock stdio server
        mock_stdio_server = MagicMock()

        async def capture_client_notification(notification):
            server_to_client_notifications.append(notification)

        mock_stdio_server.write_notification = AsyncMock(
            side_effect=capture_client_notification
        )
        mock_stdio_server.is_running = MagicMock(return_value=True)

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        # Create proxy
        proxy = MCPProxy(
            proxy_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Load plugins
        await proxy._plugin_manager.load_plugins()

        await upstream_mock.connect()

        # Start upstream listener
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send notifications in both directions simultaneously
        async def send_client_notifications():
            for i in range(5):
                notification = NotificationScenarios.log_message_notification(
                    "info", f"Client message {i}"
                )
                await proxy.handle_notification(notification)
                await asyncio.sleep(0.05)

        async def send_server_notifications():
            for i in range(5):
                notification = NotificationScenarios.log_message_notification(
                    "debug", f"Server message {i}"
                )
                await upstream_mock.send_server_notification(notification)
                await asyncio.sleep(0.05)

        # Run both directions concurrently
        await asyncio.gather(send_client_notifications(), send_server_notifications())

        # Give time for processing
        await asyncio.sleep(0.3)

        # Get the notifications that were sent to upstream from the proxy
        for _ in range(5):
            try:
                notif = await asyncio.wait_for(
                    upstream_mock.receive_client_to_server_notification(), timeout=0.1
                )
                client_to_server_notifications.append(notif)
            except (asyncio.TimeoutError, RuntimeError):
                break

        # Stop listener
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify both directions worked
        assert len(client_to_server_notifications) == 5
        assert len(server_to_client_notifications) == 5

        # Verify content integrity
        for i in range(5):
            assert (
                f"Client message {i}"
                in client_to_server_notifications[i].params["data"]
            )
            assert (
                f"Server message {i}"
                in server_to_client_notifications[i].params["data"]
            )

        await upstream_mock.disconnect()

    @pytest.mark.asyncio
    async def test_notification_filtering_by_security_plugin(self, proxy_config):
        """Test security plugin filtering notifications."""
        # Initialize security dict if not present
        if proxy_config.plugins.security is None:
            proxy_config.plugins.security = {}
        if "_global" not in proxy_config.plugins.security:
            proxy_config.plugins.security["_global"] = []

        # Add a custom security plugin that blocks certain notifications
        proxy_config.plugins.security["_global"].append(
            PluginConfig(
                handler="basic_secrets_filter",
                config={
                    "enabled": True,
                    "action": "block",
                    "secret_types": {"aws_access_keys": {"enabled": True}},
                },
            )
        )

        upstream_mock = NotificationCapableMock()

        mock_stdio_server = MagicMock()
        mock_stdio_server.write_notification = AsyncMock()
        mock_stdio_server.is_running = MagicMock(return_value=True)

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        proxy = MCPProxy(
            proxy_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        # Load plugins
        await proxy._plugin_manager.load_plugins()

        await upstream_mock.connect()

        # Send notifications with and without sensitive content
        safe_notification = NotificationScenarios.log_message_notification(
            "info", "This is a safe message"
        )
        sensitive_notification = NotificationScenarios.log_message_notification(
            "error", "AWS key: AKIAIOSFODNN7EXAMPLE"
        )

        # Process notifications
        await proxy.handle_notification(safe_notification)
        await proxy.handle_notification(sensitive_notification)

        await asyncio.sleep(0.1)

        # Only safe notification should reach upstream
        received_notifications = []
        try:
            while True:
                notif = await asyncio.wait_for(
                    upstream_mock.receive_notification(), timeout=0.1
                )
                received_notifications.append(notif)
        except asyncio.TimeoutError:
            pass

        assert len(received_notifications) == 1
        assert "safe message" in received_notifications[0].params["data"]

        await upstream_mock.disconnect()

    @pytest.mark.asyncio
    async def test_high_volume_notification_handling(self, proxy_config):
        """Test proxy handling high volume of notifications."""
        upstream_mock = NotificationCapableMock()

        received_count = 0

        async def count_notifications(notification):
            nonlocal received_count
            received_count += 1

        mock_stdio_server = MagicMock()
        mock_stdio_server.write_notification = count_notifications
        mock_stdio_server.is_running = MagicMock(return_value=True)

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        proxy = MCPProxy(
            proxy_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        await upstream_mock.connect()

        # Start listener
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send many notifications rapidly
        notification_count = 100
        await upstream_mock.start_periodic_notifications(
            "stress/test", interval=0.01, count=notification_count
        )

        # Wait for all notifications to be processed (with timeout and polling)
        # Under parallel test execution, we need to wait dynamically rather than fixed sleep
        timeout = 5.0  # Maximum wait time
        poll_interval = 0.1
        elapsed = 0.0
        while received_count < notification_count and elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Stop everything
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify all notifications were processed
        assert received_count == notification_count, (
            f"Expected {notification_count} notifications, got {received_count} "
            f"(waited {elapsed:.1f}s)"
        )

        await upstream_mock.disconnect()

    @pytest.mark.asyncio
    async def test_notification_ordering_preservation(self, proxy_config):
        """Test that notification order is preserved through the proxy."""
        upstream_mock = NotificationCapableMock()

        received_notifications = []

        async def capture_notification(notification):
            received_notifications.append(notification)

        mock_stdio_server = MagicMock()
        mock_stdio_server.write_notification = capture_notification
        mock_stdio_server.is_running = MagicMock(return_value=True)

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        proxy = MCPProxy(
            proxy_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        await upstream_mock.connect()

        # Start listener
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send numbered notifications
        for i in range(20):
            notification = MCPNotification(
                jsonrpc="2.0", method="test/ordered", params={"sequence": i}
            )
            await upstream_mock.send_server_notification(notification)

        # Wait for processing
        await asyncio.sleep(0.5)

        # Stop listener
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify order preservation
        assert len(received_notifications) == 20
        for i, notification in enumerate(received_notifications):
            assert notification.params["sequence"] == i

        await upstream_mock.disconnect()

    @pytest.mark.asyncio
    async def test_notification_error_recovery(self, proxy_config):
        """Test proxy recovery from notification processing errors."""
        upstream_mock = NotificationCapableMock()

        notification_count = 0

        async def sometimes_fail(notification):
            nonlocal notification_count
            notification_count += 1
            # Fail on every 3rd notification
            if notification_count % 3 == 0:
                raise Exception("Simulated write error")

        mock_stdio_server = MagicMock()
        mock_stdio_server.write_notification = sometimes_fail
        mock_stdio_server.is_running = MagicMock(return_value=True)

        # Create mock server manager with connected transport
        from gatekit.server_manager import ServerManager
        from unittest.mock import Mock

        mock_server_manager = Mock(spec=ServerManager)

        # Create mock connection with our notification-capable transport
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = upstream_mock.transport

        # Set up the connections dict
        mock_server_manager.connections = {"default": mock_connection}
        mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))
        mock_server_manager.get_connection = Mock(return_value=mock_connection)

        proxy = MCPProxy(
            proxy_config,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )
        proxy._is_running = True

        await upstream_mock.connect()

        # Start listener
        listener_task = asyncio.create_task(proxy._listen_for_upstream_notifications())

        # Send notifications
        for i in range(10):
            notification = NotificationScenarios.progress_notification(f"op{i}", i * 10)
            await upstream_mock.send_server_notification(notification)

        # Wait for processing
        await asyncio.sleep(0.5)

        # Stop listener
        proxy._is_running = False
        listener_task.cancel()
        try:
            await listener_task
        except asyncio.CancelledError:
            pass

        # Verify proxy continued processing despite errors
        # Should have attempted all 10 notifications
        assert notification_count == 10

        await upstream_mock.disconnect()
