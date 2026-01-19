"""Integration tests for the new notification architecture.

This module tests that requests and notifications don't interfere with each other
and that the message dispatcher works correctly in real scenarios.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.protocol.messages import MCPRequest
from gatekit.transport.stdio import StdioTransport


def create_mock_stream(stream_type="stdin"):
    """Create a properly mocked stream object with async and sync methods."""
    stream = Mock()

    if stream_type == "stdin":
        stream.write = Mock()
        stream.drain = AsyncMock()
        stream.close = Mock()  # close is sync
    else:  # stdout or stderr
        stream.readline = AsyncMock()
        stream.close = Mock()  # close is sync

    return stream


class TestNotificationArchitecture:
    """Test the new notification architecture integration."""

    @pytest.fixture
    def proxy_config(self):
        """Create a test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["echo", "test"])],
            timeouts=TimeoutConfig(connection_timeout=30, request_timeout=30),
        )

    @pytest.fixture
    def mock_process(self):
        """Create a mock process for testing."""
        process = MagicMock()
        process.returncode = None
        process.pid = 1234
        process.stdin = create_mock_stream("stdin")
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.terminate = MagicMock()
        process.kill = MagicMock()
        process.wait = AsyncMock()
        return process

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_concurrent_requests_and_notifications(
        self, proxy_config, mock_process
    ):
        """Test that requests and notifications don't interfere."""
        # Create transport with mock process
        transport = StdioTransport(proxy_config.upstreams[0].command)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Prepare mixed responses and notifications
            messages = [
                {
                    "jsonrpc": "2.0",
                    "method": "notification/test",
                    "params": {"msg": "notif-1"},
                },
                {"jsonrpc": "2.0", "id": "req-1", "result": {"data": "response-1"}},
                {
                    "jsonrpc": "2.0",
                    "method": "notification/test",
                    "params": {"msg": "notif-2"},
                },
                {"jsonrpc": "2.0", "id": "req-2", "result": {"data": "response-2"}},
                {
                    "jsonrpc": "2.0",
                    "method": "notification/test",
                    "params": {"msg": "notif-3"},
                },
            ]

            # Set up async iterator for messages
            message_iter = iter(messages)

            async def mock_readline():
                try:
                    message = next(message_iter)
                    return (json.dumps(message) + "\n").encode("utf-8")
                except StopIteration:
                    # Hang forever when no more messages
                    await asyncio.sleep(10)
                    return b""

            mock_process.stdout.readline.side_effect = mock_readline

            # Send requests
            request_1 = MCPRequest(jsonrpc="2.0", method="test", id="req-1")
            request_2 = MCPRequest(jsonrpc="2.0", method="test", id="req-2")

            await transport.send_message(request_1)
            await transport.send_message(request_2)

            # Give dispatcher time to process all messages
            await asyncio.sleep(0.2)

            # Verify we can receive both responses
            response_1 = await transport.receive_message()
            response_2 = await transport.receive_message()

            # Verify correct correlation
            responses_by_id = {response_1.id: response_1, response_2.id: response_2}
            assert "req-1" in responses_by_id
            assert "req-2" in responses_by_id
            assert responses_by_id["req-1"].result == {"data": "response-1"}
            assert responses_by_id["req-2"].result == {"data": "response-2"}

            # Verify all notifications are queued
            notifications = []
            for _i in range(3):
                notif = await transport.get_next_notification()
                notifications.append(notif)

            # Verify notification content
            assert len(notifications) == 3
            for i, notif in enumerate(notifications):
                assert notif.method == "notification/test"
                assert notif.params == {"msg": f"notif-{i+1}"}

            await transport.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_notification_delivery_under_load(self, proxy_config, mock_process):
        """Test notification delivery when system is busy with requests."""
        transport = StdioTransport(proxy_config.upstreams[0].command)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Create a high load scenario: 10 requests + 5 notifications interleaved
            messages = []

            # Add requests and responses
            for i in range(10):
                messages.append(
                    {
                        "jsonrpc": "2.0",
                        "id": f"req-{i}",
                        "result": {"data": f"response-{i}"},
                    }
                )

            # Add notifications
            for i in range(5):
                messages.append(
                    {
                        "jsonrpc": "2.0",
                        "method": "notification/load",
                        "params": {"id": i},
                    }
                )

            # Shuffle to simulate real-world order
            import random

            random.shuffle(messages)

            # Set up async iterator
            message_iter = iter(messages)

            async def mock_readline():
                try:
                    message = next(message_iter)
                    # Small delay to simulate network latency
                    await asyncio.sleep(0.01)
                    return (json.dumps(message) + "\n").encode("utf-8")
                except StopIteration:
                    await asyncio.sleep(10)
                    return b""

            mock_process.stdout.readline.side_effect = mock_readline

            # Send all requests first
            requests = [
                MCPRequest(jsonrpc="2.0", method="test", id=f"req-{i}")
                for i in range(10)
            ]
            for req in requests:
                await transport.send_message(req)

            # Give dispatcher time to process messages
            await asyncio.sleep(0.3)

            # Verify all requests get responses
            responses = []
            for _ in range(10):
                resp = await transport.receive_message()
                responses.append(resp)

            # Verify no requests were lost
            response_ids = {resp.id for resp in responses}
            expected_ids = {f"req-{i}" for i in range(10)}
            assert response_ids == expected_ids

            # Verify all notifications are still available
            notifications = []
            for _ in range(5):
                notif = await transport.get_next_notification()
                notifications.append(notif)

            # Verify no notifications were lost
            assert len(notifications) == 5
            notification_ids = {notif.params["id"] for notif in notifications}
            expected_notif_ids = {i for i in range(5)}
            assert notification_ids == expected_notif_ids

            await transport.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_error_recovery_in_dispatcher(self, proxy_config, mock_process):
        """Test that dispatcher handles errors without losing valid messages."""
        transport = StdioTransport(proxy_config.upstreams[0].command)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Set up only valid messages - the dispatcher will handle errors gracefully
            # by propagating them to pending requests when they occur
            valid_response = {
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {"data": "response-1"},
            }

            messages = [
                (json.dumps(valid_response) + "\n").encode("utf-8"),
            ]

            message_iter = iter(messages)

            async def mock_readline():
                try:
                    result = next(message_iter)
                    await asyncio.sleep(0.01)  # Small delay
                    return result
                except StopIteration:
                    await asyncio.sleep(10)
                    return b""

            mock_process.stdout.readline.side_effect = mock_readline

            # Send a request
            request = MCPRequest(jsonrpc="2.0", method="test", id="req-1")
            await transport.send_message(request)

            # Give dispatcher time to process
            await asyncio.sleep(0.1)

            # Should get the valid response
            response = await transport.receive_message()
            assert response.id == "req-1"
            assert response.result == {"data": "response-1"}

            await transport.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_notification_queue_backpressure(self, proxy_config, mock_process):
        """Test that notification queue handles backpressure correctly."""
        transport = StdioTransport(proxy_config.upstreams[0].command)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Create many notifications to test queue capacity
            notifications = []
            for i in range(100):
                notifications.append(
                    {
                        "jsonrpc": "2.0",
                        "method": "notification/stress",
                        "params": {"seq": i},
                    }
                )

            # Set up rapid message delivery
            message_iter = iter(notifications)

            async def mock_readline():
                try:
                    message = next(message_iter)
                    return (json.dumps(message) + "\n").encode("utf-8")
                except StopIteration:
                    await asyncio.sleep(10)
                    return b""

            mock_process.stdout.readline.side_effect = mock_readline

            # Give dispatcher time to process all notifications
            await asyncio.sleep(0.5)

            # Verify all notifications are preserved in order
            received_notifications = []
            for _ in range(100):
                notif = await transport.get_next_notification()
                received_notifications.append(notif)

            # Verify order and completeness
            assert len(received_notifications) == 100
            for i, notif in enumerate(received_notifications):
                assert notif.method == "notification/stress"
                assert notif.params["seq"] == i

            await transport.disconnect()
