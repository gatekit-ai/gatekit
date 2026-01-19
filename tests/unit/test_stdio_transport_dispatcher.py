"""Tests for the StdioTransport message dispatcher architecture.

This module tests the new message dispatcher that solves the race condition
between request/response handling and notification handling.
"""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from gatekit.transport.stdio import StdioTransport
from gatekit.transport.errors import (
    TransportTimeoutError,
    TransportDisconnectedError,
    TransportConnectionError,
    TransportProtocolError,
)
from gatekit.protocol.messages import MCPRequest


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


class TestStdioTransportDispatcher:
    """Test the message dispatcher functionality."""

    @pytest_asyncio.fixture
    async def transport(self):
        """Create a StdioTransport instance for testing with automatic cleanup."""
        transport = StdioTransport(command=["echo", "test"])
        yield transport
        # Ensure cleanup happens even if test fails
        if transport.is_connected():
            await transport.disconnect()

    @pytest.fixture
    def mock_process(self):
        """Create a mock process for testing."""
        process = MagicMock()
        process.returncode = None
        process.pid = 1234
        process.stdin = create_mock_stream("stdin")
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        return process

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_dispatcher_routes_responses_correctly(self, transport, mock_process):
        """Test that responses are delivered to correct waiting requests."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Mock readline to return responses out of order
            response_1 = {
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {"data": "response-1"},
            }
            response_2 = {
                "jsonrpc": "2.0",
                "id": "req-2",
                "result": {"data": "response-2"},
            }

            # Use an async generator to provide responses in reverse order
            responses = [
                (json.dumps(response_2) + "\n").encode("utf-8"),
                (json.dumps(response_1) + "\n").encode("utf-8"),
            ]
            response_iter = iter(responses)

            async def mock_readline():
                try:
                    return next(response_iter)
                except StopIteration:
                    # Hang forever to prevent reading more
                    await asyncio.sleep(10)
                    return b""

            mock_process.stdout.readline.side_effect = mock_readline

            # Send two requests
            request_1 = MCPRequest(jsonrpc="2.0", method="test", id="req-1")
            request_2 = MCPRequest(jsonrpc="2.0", method="test", id="req-2")

            # Send requests and receive responses
            await transport.send_message(request_1)
            await transport.send_message(request_2)

            # Give dispatcher a moment to process the responses
            await asyncio.sleep(0.1)

            # Each request should get its matching response despite order
            response_1_received = await transport.receive_message()
            response_2_received = await transport.receive_message()

            # Verify correct correlation - each response has correct data for its ID
            # The order may vary, but each ID should have its correct data
            responses_by_id = {
                response_1_received.id: response_1_received,
                response_2_received.id: response_2_received,
            }

            # Verify we got both expected responses
            assert "req-1" in responses_by_id
            assert "req-2" in responses_by_id

            # Verify correct data correlation
            assert responses_by_id["req-1"].result == {"data": "response-1"}
            assert responses_by_id["req-2"].result == {"data": "response-2"}

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_dispatcher_queues_notifications(self, transport, mock_process):
        """Test that notifications are queued, not lost."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Mock readline to return multiple notifications
            notification_1 = {
                "jsonrpc": "2.0",
                "method": "notification/test",
                "params": {"msg": "notif-1"},
            }
            notification_2 = {
                "jsonrpc": "2.0",
                "method": "notification/test",
                "params": {"msg": "notif-2"},
            }

            mock_process.stdout.readline.side_effect = [
                (json.dumps(notification_1) + "\n").encode("utf-8"),
                (json.dumps(notification_2) + "\n").encode("utf-8"),
                b"",  # EOF to stop dispatcher
            ]

            # Give dispatcher time to process notifications
            await asyncio.sleep(0.1)

            # Verify both notifications are queued and can be consumed in order
            notif_1 = await transport.get_next_notification()
            assert notif_1.method == "notification/test"
            assert notif_1.params == {"msg": "notif-1"}

            notif_2 = await transport.get_next_notification()
            assert notif_2.method == "notification/test"
            assert notif_2.params == {"msg": "notif-2"}

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_concurrent_requests_no_race_condition(self, transport, mock_process):
        """Test multiple concurrent requests don't interfere."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Prepare 5 requests and responses
            requests = []
            responses = []
            for i in range(5):
                req_id = f"req-{i}"
                requests.append(MCPRequest(jsonrpc="2.0", method="test", id=req_id))
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"data": f"response-{i}"},
                    }
                )

            # Return responses in random order
            import random

            random.shuffle(responses)

            # Use an async iterator to control response timing
            response_iter = iter(responses)
            response_ready = asyncio.Event()

            async def mock_readline():
                # Wait for signal that responses should be available
                await response_ready.wait()
                try:
                    result = (json.dumps(next(response_iter)) + "\n").encode("utf-8")
                    # Small delay to ensure deterministic ordering
                    await asyncio.sleep(0.01)
                    return result
                except StopIteration:
                    # Hang forever when no more responses
                    await asyncio.sleep(10)
                    return b""

            mock_process.stdout.readline.side_effect = mock_readline

            # Send all requests first
            send_tasks = [transport.send_message(req) for req in requests]
            await asyncio.gather(*send_tasks)

            # Now signal that responses can be delivered
            response_ready.set()

            # Give dispatcher time to process responses
            await asyncio.sleep(0.1)

            # Receive all responses
            received_responses = []
            for _ in range(5):
                resp = await transport.receive_message()
                received_responses.append(resp)

            # Verify all requests got correct responses (order may vary)
            received_by_id = {resp.id: resp for resp in received_responses}

            for i in range(5):
                expected_id = f"req-{i}"
                assert expected_id in received_by_id
                assert received_by_id[expected_id].result == {"data": f"response-{i}"}

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_request_timeout_handling(self, transport, mock_process):
        """Test requests timeout if no response received."""
        # Use a very short timeout for testing
        transport.request_timeout = 0.1

        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Mock readline to hang forever (simulate no response)
            async def never_returns():
                await asyncio.sleep(10)  # Sleep longer than test timeout
                return b""

            mock_process.stdout.readline.side_effect = never_returns

            # Send request
            request = MCPRequest(jsonrpc="2.0", method="test", id="timeout-test")
            await transport.send_message(request)

            # Verify timeout exception after configured time
            with pytest.raises(TransportTimeoutError):
                await transport.receive_message()

            # With the fix, we no longer clear all requests on timeout
            # The request should still be pending (to allow retries or later responses)
            assert "timeout-test" in transport._pending_requests

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_dispatcher_error_propagation(self, transport, mock_process):
        """Test connection errors propagate to all waiting requests."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Mock readline to raise an error after first call
            mock_process.stdout.readline.side_effect = [
                b"",  # EOF to simulate connection loss
            ]

            # Send multiple requests
            requests = []
            for i in range(3):
                req = MCPRequest(jsonrpc="2.0", method="test", id=f"req-{i}")
                requests.append(req)
                await transport.send_message(req)

            # All pending requests should receive the error
            with pytest.raises(TransportConnectionError, match="Connection closed"):
                await transport.receive_message()

            # Verify all requests are cleaned up
            assert len(transport._pending_requests) == 0

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_get_next_notification_timeout(self, transport, mock_process):
        """Test get_next_notification blocks until cancelled when queue is empty."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Empty notification queue - method should block indefinitely
            transport._notification_queue = asyncio.Queue()

            # Should block and raise TimeoutError when using asyncio.wait_for with timeout
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    transport.get_next_notification(), timeout=0.1
                )

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings(
        "ignore::RuntimeWarning"
    )  # AsyncMock creates internal coroutines
    async def test_dispatcher_validation_errors(self, transport, mock_process):
        """Test dispatcher handles validation errors properly."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            # Mock readline to return invalid JSON
            mock_process.stdout.readline.side_effect = [
                b"invalid json\n",
                b"",  # EOF
            ]

            # Send a request
            request = MCPRequest(jsonrpc="2.0", method="test", id="test")
            await transport.send_message(request)

            # Should propagate JSON parsing error to waiting request
            with pytest.raises(TransportProtocolError):
                await transport.receive_message()

    @pytest.mark.asyncio
    async def test_dispatcher_lifecycle(self, transport, mock_process):
        """Test dispatcher starts and stops properly."""
        # Setup mock process
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            # Connect should start dispatcher
            await transport.connect()
            assert transport._running is True
            assert transport._message_dispatcher_task is not None
            assert not transport._message_dispatcher_task.done()

            # Disconnect should stop dispatcher
            await transport.disconnect()
            assert transport._running is False
            assert transport._message_dispatcher_task.done()
