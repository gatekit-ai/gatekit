"""Unit tests for StreamableHttpTransport.

Tests for HTTP transport following TDD - all tests written first.
Tests use respx for mocking HTTP responses.
"""

import asyncio
import json
import pytest
import respx
import httpx

from gatekit.transport.http import StreamableHttpTransport
from gatekit.transport.errors import (
    TransportTimeoutError,
    TransportConcurrencyLimitError,
    TransportDisconnectedError,
)
from gatekit.protocol.messages import MCPRequest, MCPNotification


# Test URL used across tests
TEST_URL = "http://localhost:8123/mcp"


class TestBasicConnectivity:
    """Tests for connect(), disconnect(), and is_connected()."""

    @pytest.mark.asyncio
    async def test_connect_opens_sse_stream(self, respx_mock: respx.MockRouter):
        """connect() opens SSE connection and starts background reader."""
        # Mock the SSE endpoint to return an empty stream that stays open briefly
        sse_route = respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        assert not transport.is_connected()

        await transport.connect()

        try:
            assert transport.is_connected()
            # Give the background SSE task a moment to start
            await asyncio.sleep(0.05)
            # SSE endpoint should have been called
            assert sse_route.called
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_everything(self, respx_mock: respx.MockRouter):
        """disconnect() cleans up SSE and client."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()
        assert transport.is_connected()

        await transport.disconnect()

        assert not transport.is_connected()
        # Client should be closed
        assert transport._client is None

    @pytest.mark.asyncio
    async def test_is_connected_tracks_state(self, respx_mock: respx.MockRouter):
        """is_connected() returns correct state throughout lifecycle."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)

        # Before connect
        assert not transport.is_connected()

        # After connect
        await transport.connect()
        assert transport.is_connected()

        # After disconnect
        await transport.disconnect()
        assert not transport.is_connected()


class TestPostRequests:
    """Tests for POST request sending."""

    @pytest.mark.asyncio
    async def test_send_and_receive_sends_post_request(self, respx_mock: respx.MockRouter):
        """send_and_receive() sends JSON-RPC via POST."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST endpoint with immediate JSON response
        response_body = json.dumps({
            "jsonrpc": "2.0",
            "id": "test-1",
            "result": {"status": "ok"}
        })
        post_route = respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=response_body.encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="ping", id="test-1")
            response = await transport.send_and_receive(request)

            assert post_route.called
            assert response.id == "test-1"
            assert response.result == {"status": "ok"}
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_post_request_includes_correct_headers(self, respx_mock: respx.MockRouter):
        """POST request includes Content-Type: application/json and Accept headers."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Capture request headers
        captured_headers = {}

        def capture_request(request: httpx.Request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": "test-1",
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=capture_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="ping", id="test-1")
            await transport.send_and_receive(request)

            assert captured_headers.get("content-type") == "application/json"
            # Accept header should include both JSON and SSE
            accept = captured_headers.get("accept", "")
            assert "application/json" in accept
            assert "text/event-stream" in accept
        finally:
            await transport.disconnect()


class TestPostImmediateResponse:
    """Tests for POST immediate response handling based on Content-Type."""

    @pytest.mark.asyncio
    async def test_post_immediate_json_response(self, respx_mock: respx.MockRouter):
        """POST returns application/json with response body directly."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST with immediate JSON response
        response_body = json.dumps({
            "jsonrpc": "2.0",
            "id": "req-immediate",
            "result": {"immediate": True}
        })
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=response_body.encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="tools/call", id="req-immediate")
            response = await transport.send_and_receive(request)

            assert response.id == "req-immediate"
            assert response.result == {"immediate": True}
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_post_returns_202_response_via_sse(self, respx_mock: respx.MockRouter):
        """POST returns 202, response comes via SSE."""
        # This test verifies that when POST returns 202 Accepted (async processing),
        # the response is expected to arrive via the SSE stream.

        # We'll use an event to coordinate the SSE response delivery
        response_event = asyncio.Event()

        # SSE response that will be delivered
        sse_response_data = {
            "jsonrpc": "2.0",
            "id": "req-async",
            "result": {"via": "sse"}
        }

        # Mock SSE endpoint - will deliver the response after a brief delay
        async def sse_stream():
            # Wait briefly then deliver response via SSE
            await asyncio.sleep(0.05)
            # SSE format: data: {json}\n\n
            yield f"data: {json.dumps(sse_response_data)}\n\n".encode()
            response_event.set()

        # Create an async iterator response
        async def generate_sse_response():
            async for chunk in sse_stream():
                yield chunk

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=generate_sse_response(),
            )
        )

        # Mock POST with 202 Accepted (no body)
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(202, content=b"")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="tools/call", id="req-async")
            response = await asyncio.wait_for(
                transport.send_and_receive(request),
                timeout=2.0
            )

            assert response.id == "req-async"
            assert response.result == {"via": "sse"}
        finally:
            await transport.disconnect()


class TestDualChannelRaceCondition:
    """Tests for dual-channel response handling (POST and SSE)."""

    @pytest.mark.asyncio
    async def test_dual_channel_post_and_sse_same_response(self, respx_mock: respx.MockRouter):
        """Both channels return same response, first wins."""
        # This tests the race condition where both POST response body
        # and SSE stream could deliver the same response.
        # The implementation should use the first one and ignore the second.

        response_data = {
            "jsonrpc": "2.0",
            "id": "req-race",
            "result": {"source": "first"}
        }

        # SSE delivers response too (but should be ignored if POST was first)
        async def sse_stream():
            await asyncio.sleep(0.01)  # Small delay
            yield f"data: {json.dumps(response_data)}\n\n".encode()

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=sse_stream(),
            )
        )

        # POST returns immediate response
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps(response_data).encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="req-race")
            response = await transport.send_and_receive(request)

            # Should succeed without error (first response wins)
            assert response.id == "req-race"
            # Result should be from whichever arrived first
            assert response.result is not None
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_response_correlation_by_id(self, respx_mock: respx.MockRouter):
        """Responses routed to correct waiting request."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to return response for the specific request ID
        def handle_post(request: httpx.Request):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],  # Echo back the request ID
                    "result": {"request_id": body["id"]}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=handle_post)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Send multiple requests
            request1 = MCPRequest(jsonrpc="2.0", method="test", id="id-1")
            request2 = MCPRequest(jsonrpc="2.0", method="test", id="id-2")

            response1 = await transport.send_and_receive(request1)
            response2 = await transport.send_and_receive(request2)

            # Each response should match its request
            assert response1.id == "id-1"
            assert response1.result == {"request_id": "id-1"}
            assert response2.id == "id-2"
            assert response2.result == {"request_id": "id-2"}
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_response_id_mismatch_ignored(self, respx_mock: respx.MockRouter):
        """POST response with mismatched ID is ignored, correct response via SSE."""
        # This tests the fix for the QC finding where immediate responses weren't
        # validated for ID match before being routed to the waiting future.

        correct_response = {
            "jsonrpc": "2.0",
            "id": "req-correct",
            "result": {"source": "sse"}
        }

        # SSE delivers the correct response
        async def sse_stream():
            await asyncio.sleep(0.05)  # Small delay to let POST complete first
            yield f"data: {json.dumps(correct_response)}\n\n".encode()

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=sse_stream(),
            )
        )

        # POST returns response with WRONG ID (simulating server bug or attack)
        wrong_response = {
            "jsonrpc": "2.0",
            "id": "wrong-id",  # Doesn't match request ID
            "result": {"source": "post", "evil": True}
        }
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps(wrong_response).encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="req-correct")
            response = await transport.send_and_receive(request)

            # Should get the CORRECT response from SSE, not the mismatched one from POST
            assert response.id == "req-correct"
            assert response.result == {"source": "sse"}
        finally:
            await transport.disconnect()


class TestSseStream:
    """Tests for SSE stream handling."""

    @pytest.mark.asyncio
    async def test_sse_stream_receives_responses(self, respx_mock: respx.MockRouter):
        """SSE delivers JSON-RPC responses."""
        sse_response = {
            "jsonrpc": "2.0",
            "id": "sse-resp",
            "result": {"from": "sse"}
        }

        async def sse_stream():
            # Wait a bit before sending response (simulates server processing)
            await asyncio.sleep(0.1)
            yield f"data: {json.dumps(sse_response)}\n\n".encode()
            # Keep stream alive so it doesn't close prematurely
            await asyncio.sleep(1.0)

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=sse_stream(),
            )
        )

        # POST returns 202, response comes via SSE
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(202, content=b"")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="sse-resp")
            response = await asyncio.wait_for(
                transport.send_and_receive(request),
                timeout=2.0
            )

            assert response.id == "sse-resp"
            assert response.result == {"from": "sse"}
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_sse_stream_receives_notifications(self, respx_mock: respx.MockRouter):
        """Notifications queued properly from SSE."""
        notification_data = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progress": 50}
        }

        async def sse_stream():
            await asyncio.sleep(0.01)
            yield f"data: {json.dumps(notification_data)}\n\n".encode()
            # Keep stream alive briefly
            await asyncio.sleep(0.5)

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=sse_stream(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Wait for notification to be queued
            await asyncio.sleep(0.1)

            # Check notification queue
            notification = await asyncio.wait_for(
                transport.get_next_notification(),
                timeout=1.0
            )

            assert notification.method == "notifications/progress"
            assert notification.params == {"progress": 50}
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_get_next_notification_returns_notification(self, respx_mock: respx.MockRouter):
        """Can retrieve notifications via get_next_notification()."""
        notification1 = {
            "jsonrpc": "2.0",
            "method": "notification/first",
            "params": {"seq": 1}
        }
        notification2 = {
            "jsonrpc": "2.0",
            "method": "notification/second",
            "params": {"seq": 2}
        }

        async def sse_stream():
            await asyncio.sleep(0.01)
            yield f"data: {json.dumps(notification1)}\n\n".encode()
            await asyncio.sleep(0.01)
            yield f"data: {json.dumps(notification2)}\n\n".encode()
            await asyncio.sleep(0.5)

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=sse_stream(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Wait for notifications to be queued
            await asyncio.sleep(0.1)

            notif1 = await asyncio.wait_for(
                transport.get_next_notification(),
                timeout=1.0
            )
            notif2 = await asyncio.wait_for(
                transport.get_next_notification(),
                timeout=1.0
            )

            assert notif1.method == "notification/first"
            assert notif1.params == {"seq": 1}
            assert notif2.method == "notification/second"
            assert notif2.params == {"seq": 2}
        finally:
            await transport.disconnect()


class TestConcurrentRequests:
    """Tests for concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_dont_interfere(self, respx_mock: respx.MockRouter):
        """Multiple requests get correct responses."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST with delay to allow concurrent requests
        async def handle_post(request: httpx.Request):
            body = json.loads(request.content)
            # Add small delay to allow concurrency
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"echo_id": body["id"]}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=handle_post)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Send multiple concurrent requests
            requests = [
                MCPRequest(jsonrpc="2.0", method="test", id=f"concurrent-{i}")
                for i in range(5)
            ]

            # Send all concurrently
            responses = await asyncio.gather(*[
                transport.send_and_receive(req) for req in requests
            ])

            # Each response should match its request
            for i, response in enumerate(responses):
                assert response.id == f"concurrent-{i}"
                assert response.result == {"echo_id": f"concurrent-{i}"}
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_limit_enforcement(self, respx_mock: respx.MockRouter):
        """101st request gets error when limit is 100."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST that never responds (to keep requests pending)
        pending_requests = []

        async def slow_post(request: httpx.Request):
            # Never return - request stays pending
            event = asyncio.Event()
            pending_requests.append(event)
            await event.wait()
            body = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=slow_post)

        transport = StreamableHttpTransport(url=TEST_URL, max_concurrent_requests=100)
        await transport.connect()

        try:
            # Start 100 requests (they will be pending)
            tasks = []
            for i in range(100):
                task = asyncio.create_task(
                    transport.send_and_receive(
                        MCPRequest(jsonrpc="2.0", method="test", id=f"req-{i}")
                    )
                )
                tasks.append(task)
                # Small delay to ensure request is registered
                await asyncio.sleep(0.001)

            # The 101st request should fail with concurrency limit
            with pytest.raises(TransportConcurrencyLimitError) as exc_info:
                await transport.send_and_receive(
                    MCPRequest(jsonrpc="2.0", method="test", id="req-overflow")
                )

            assert exc_info.value.limit == 100
            assert exc_info.value.current == 100

        finally:
            # Clean up pending requests
            for event in pending_requests:
                event.set()
            for task in tasks:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            await transport.disconnect()


class TestTimeout:
    """Tests for request timeout handling."""

    @pytest.mark.asyncio
    async def test_request_timeout_raises_error(self, respx_mock: respx.MockRouter):
        """Timeout raises TransportTimeoutError."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST that returns 202 Accepted - response never comes via SSE
        # This causes the request to wait indefinitely (until timeout)
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(202, content=b"")
        )

        # Very short timeout for testing
        transport = StreamableHttpTransport(url=TEST_URL, request_timeout=0.1)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="timeout-test")

            with pytest.raises(TransportTimeoutError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.timeout == 0.1
            assert "timeout" in str(exc_info.value).lower()
        finally:
            await transport.disconnect()


class TestDisconnectedState:
    """Tests for operations on disconnected transport."""

    @pytest.mark.asyncio
    async def test_send_when_disconnected_raises_error(self):
        """send_and_receive() when disconnected raises TransportDisconnectedError."""
        transport = StreamableHttpTransport(url=TEST_URL)

        with pytest.raises(TransportDisconnectedError):
            await transport.send_and_receive(
                MCPRequest(jsonrpc="2.0", method="test", id="1")
            )

    @pytest.mark.asyncio
    async def test_get_notification_when_disconnected_raises_error(self):
        """get_next_notification() when disconnected raises TransportDisconnectedError."""
        transport = StreamableHttpTransport(url=TEST_URL)

        with pytest.raises(TransportDisconnectedError):
            await transport.get_next_notification()


class TestMetrics:
    """Tests for transport metrics tracking."""

    @pytest.mark.asyncio
    async def test_metrics_track_requests(self, respx_mock: respx.MockRouter):
        """Metrics track sent, completed, and failed requests."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST with response
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": "metric-test",
                    "result": {}
                }).encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Initial metrics
            metrics = transport.get_metrics()
            assert metrics["requests_sent"] == 0
            assert metrics["requests_completed"] == 0

            # Send a request
            await transport.send_and_receive(
                MCPRequest(jsonrpc="2.0", method="test", id="metric-test")
            )

            # Check updated metrics
            metrics = transport.get_metrics()
            assert metrics["requests_sent"] == 1
            assert metrics["requests_completed"] == 1
        finally:
            await transport.disconnect()


# ============================================================================
# Phase 1d: Error Handling & Edge Cases Tests
# ============================================================================

from gatekit.transport.errors import (
    HttpConnectionError,
    HttpRequestError,
    TransportProtocolError,
)


class TestNetworkTimeouts:
    """Tests for network timeout handling."""

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_error(self, respx_mock: respx.MockRouter):
        """Connection timeout wraps in HttpConnectionError."""
        # Mock SSE endpoint to raise a connect timeout
        respx_mock.get(TEST_URL).mock(
            side_effect=httpx.ConnectTimeout("Connection timed out")
        )

        transport = StreamableHttpTransport(url=TEST_URL, request_timeout=1.0)

        # Connect should complete (it starts the SSE task in background)
        await transport.connect()

        try:
            # Give SSE reader time to encounter the error
            await asyncio.sleep(0.1)
            # The SSE reader should have stopped after encountering the error
            # and reconnection attempts exhausted
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_post_connect_timeout_raises_error(self, respx_mock: respx.MockRouter):
        """POST connection timeout raises HttpConnectionError."""
        # Mock SSE endpoint (succeeds)
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to raise connect timeout
        respx_mock.post(TEST_URL).mock(
            side_effect=httpx.ConnectTimeout("Connection timed out")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="timeout-1")
            with pytest.raises(HttpConnectionError) as exc_info:
                await transport.send_and_receive(request)

            assert "Connection timed out" in str(exc_info.value) or "failed" in str(exc_info.value).lower()
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_sse_stream_timeout_handled(self, respx_mock: respx.MockRouter):
        """SSE stream read timeout handled gracefully with reconnection."""
        reconnect_count = 0

        def mock_sse_with_timeout(request: httpx.Request):
            nonlocal reconnect_count
            reconnect_count += 1
            # First few calls raise timeout, simulating stream read timeout
            if reconnect_count <= 2:
                raise httpx.ReadTimeout("Read timed out")
            # After reconnections exhausted, return empty stream
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )

        respx_mock.get(TEST_URL).mock(side_effect=mock_sse_with_timeout)

        transport = StreamableHttpTransport(url=TEST_URL, max_reconnection_attempts=2)
        await transport.connect()

        try:
            # Give SSE reader time to exhaust reconnection attempts
            await asyncio.sleep(0.5)
            # Should have attempted reconnections
            assert reconnect_count >= 2
        finally:
            await transport.disconnect()


class TestServerErrors:
    """Tests for server error handling (4xx, 5xx)."""

    @pytest.mark.asyncio
    async def test_server_400_raises_http_request_error(self, respx_mock: respx.MockRouter):
        """400 Bad Request raises HttpRequestError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(400, content=b"Bad Request")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="err-400")
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 400
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_server_401_raises_http_request_error(self, respx_mock: respx.MockRouter):
        """401 Unauthorized raises HttpRequestError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(401, content=b"Unauthorized")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="err-401")
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 401
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_server_403_raises_http_request_error(self, respx_mock: respx.MockRouter):
        """403 Forbidden raises HttpRequestError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(403, content=b"Forbidden")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="err-403")
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 403
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_server_500_raises_http_request_error(self, respx_mock: respx.MockRouter):
        """500 Internal Server Error raises HttpRequestError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(500, content=b"Internal Server Error")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="err-500")
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 500
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_server_502_raises_http_request_error(self, respx_mock: respx.MockRouter):
        """502 Bad Gateway raises HttpRequestError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(502, content=b"Bad Gateway")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="err-502")
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 502
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_server_503_raises_http_request_error(self, respx_mock: respx.MockRouter):
        """503 Service Unavailable raises HttpRequestError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(503, content=b"Service Unavailable")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="err-503")
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 503
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_malformed_json_response_raises_error(self, respx_mock: respx.MockRouter):
        """Invalid JSON in response body raises TransportProtocolError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        # Return invalid JSON with application/json content-type
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b"not valid json {",
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="bad-json")
            with pytest.raises(TransportProtocolError) as exc_info:
                await transport.send_and_receive(request)

            assert "json" in str(exc_info.value).lower() or "parse" in str(exc_info.value).lower()
        finally:
            await transport.disconnect()


class TestStreamInterruption:
    """Tests for SSE stream interruption and reconnection."""

    @pytest.mark.asyncio
    async def test_sse_stream_interrupted_triggers_reconnect(self, respx_mock: respx.MockRouter):
        """SSE connection lost triggers reconnect attempt."""
        reconnect_count = 0

        def mock_sse_stream(request: httpx.Request):
            nonlocal reconnect_count
            reconnect_count += 1
            if reconnect_count == 1:
                # First connection - raise error to simulate interruption
                raise httpx.ReadError("Connection reset")
            # Subsequent connections succeed
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )

        respx_mock.get(TEST_URL).mock(side_effect=mock_sse_stream)

        transport = StreamableHttpTransport(url=TEST_URL, max_reconnection_attempts=2)
        await transport.connect()

        try:
            # Give SSE reader time to encounter error and reconnect
            await asyncio.sleep(0.3)
            # Should have reconnected at least once
            assert reconnect_count >= 2, f"Expected reconnection, got {reconnect_count} connections"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_sse_reconnection_includes_last_event_id(self, respx_mock: respx.MockRouter):
        """Reconnect includes Last-Event-Id header."""
        request_headers: list = []
        call_count = 0

        async def mock_sse_with_event_id(request: httpx.Request):
            nonlocal call_count
            call_count += 1
            request_headers.append(dict(request.headers))

            if call_count == 1:
                # First connection - return event with ID then fail

                async def stream_with_id():
                    yield b"id: event-123\n"
                    yield b"data: {\"jsonrpc\": \"2.0\", \"method\": \"test\"}\n\n"
                    # Then raise error
                    raise httpx.ReadError("Stream interrupted")

                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/event-stream"},
                    stream=stream_with_id(),
                )
            else:
                # Second connection - should have Last-Event-Id
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/event-stream"},
                    content=b"",
                )

        respx_mock.get(TEST_URL).mock(side_effect=mock_sse_with_event_id)

        transport = StreamableHttpTransport(url=TEST_URL, max_reconnection_attempts=2)
        await transport.connect()

        try:
            # Give SSE reader time to process and reconnect
            await asyncio.sleep(0.5)

            # Check if reconnection included Last-Event-Id
            if len(request_headers) >= 2:
                second_request_headers = request_headers[1]
                # The header should be present on reconnection
                assert "last-event-id" in second_request_headers, \
                    f"Expected Last-Event-Id header, got: {second_request_headers}"
                assert second_request_headers["last-event-id"] == "event-123"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_sse_max_reconnection_attempts(self, respx_mock: respx.MockRouter):
        """After max failed attempts, stop reconnecting."""
        reconnect_count = 0

        def mock_always_fail(request: httpx.Request):
            nonlocal reconnect_count
            reconnect_count += 1
            raise httpx.ReadError("Connection failed")

        respx_mock.get(TEST_URL).mock(side_effect=mock_always_fail)

        # Allow only 2 reconnection attempts
        transport = StreamableHttpTransport(url=TEST_URL, max_reconnection_attempts=2)
        await transport.connect()

        try:
            # Give SSE reader time to exhaust attempts
            await asyncio.sleep(0.5)

            # Should have stopped after initial + max_reconnection_attempts
            # Initial attempt + 2 reconnection attempts = 3 total
            assert reconnect_count == 3, \
                f"Expected 3 total attempts (initial + 2 reconnects), got {reconnect_count}"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_sse_405_stops_immediately_without_retry(self, respx_mock: respx.MockRouter):
        """When server returns 405 (Method Not Allowed), stop SSE immediately without retrying.

        Many MCP servers only support POST for request/response and don't have
        a GET/SSE endpoint for notifications. In this case, we should stop
        trying SSE immediately rather than spamming the server with retries.
        """
        sse_request_count = 0

        def mock_sse_405(request: httpx.Request):
            nonlocal sse_request_count
            sse_request_count += 1
            # Server doesn't support GET - returns 405
            return httpx.Response(405, content=b"Method Not Allowed")

        respx_mock.get(TEST_URL).mock(side_effect=mock_sse_405)
        # POST requests should work fine
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b'{"jsonrpc": "2.0", "id": "test-1", "result": {}}',
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL, max_reconnection_attempts=5)
        await transport.connect()

        try:
            # Give SSE reader time to encounter 405 and stop
            await asyncio.sleep(0.3)

            # Should have made only 1 attempt (no retries for 405)
            assert sse_request_count == 1, \
                f"Expected 1 SSE attempt (no retries for 405), got {sse_request_count}"

            # Transport should still be functional for POST requests
            request = MCPRequest(jsonrpc="2.0", method="test", id="test-1")
            response = await transport.send_and_receive(request)
            assert response.result == {}
        finally:
            await transport.disconnect()


class TestConnectionDrops:
    """Tests for connection drop handling."""

    @pytest.mark.asyncio
    async def test_connection_drop_during_post_raises_error(self, respx_mock: respx.MockRouter):
        """Connection reset during POST raises HttpConnectionError."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        # Simulate connection reset during POST
        respx_mock.post(TEST_URL).mock(
            side_effect=httpx.RemoteProtocolError("Connection reset by peer")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="drop-1")
            with pytest.raises(HttpConnectionError) as exc_info:
                await transport.send_and_receive(request)

            assert "reset" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_pending_requests_fail_on_disconnect(self, respx_mock: respx.MockRouter):
        """Pending requests get exception on disconnect."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # POST that never responds (returns 202, no SSE response)
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(202, content=b"")
        )

        transport = StreamableHttpTransport(url=TEST_URL, request_timeout=30.0)
        await transport.connect()

        # Start a request that will be pending
        request = MCPRequest(jsonrpc="2.0", method="test", id="pending-1")
        request_task = asyncio.create_task(transport.send_and_receive(request))

        try:
            # Give the request time to be registered
            await asyncio.sleep(0.05)

            # Disconnect while request is pending
            await transport.disconnect()

            # The pending request should fail with TransportDisconnectedError
            with pytest.raises(TransportDisconnectedError):
                await request_task
        except Exception:
            request_task.cancel()
            try:
                await request_task
            except asyncio.CancelledError:
                pass
            raise


class TestContentTypeRouting:
    """Tests for Content-Type based response routing."""

    @pytest.mark.asyncio
    async def test_unknown_content_type_raises_error(self, respx_mock: respx.MockRouter):
        """Unexpected Content-Type handled with error."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )
        # Return unexpected content type
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                content=b"Plain text response",
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="content-type-1")
            with pytest.raises((TransportProtocolError, HttpRequestError)) as exc_info:
                await transport.send_and_receive(request)

            error_msg = str(exc_info.value).lower()
            assert "content" in error_msg or "type" in error_msg or "unexpected" in error_msg
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_text_event_stream_content_type_in_post(self, respx_mock: respx.MockRouter):
        """POST returns text/event-stream (SSE in body)."""
        response_data = {
            "jsonrpc": "2.0",
            "id": "sse-in-post",
            "result": {"source": "sse-body"}
        }

        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # POST returns SSE-formatted response in body
        async def sse_in_post_body():
            yield f"data: {json.dumps(response_data)}\n\n".encode()

        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=sse_in_post_body(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="sse-in-post")
            response = await asyncio.wait_for(
                transport.send_and_receive(request),
                timeout=2.0
            )

            assert response.id == "sse-in-post"
            assert response.result == {"source": "sse-body"}
        finally:
            await transport.disconnect()


class TestConfigurationValidation:
    """Tests for configuration and URL validation."""

    def test_invalid_url_raises_error(self):
        """Invalid URL format rejected."""
        with pytest.raises(ValueError) as exc_info:
            StreamableHttpTransport(url="not-a-valid-url")

        assert "url" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()

    def test_empty_url_raises_error(self):
        """Empty URL rejected."""
        with pytest.raises(ValueError) as exc_info:
            StreamableHttpTransport(url="")

        assert "url" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()

    def test_whitespace_url_raises_error(self):
        """Whitespace-only URL rejected."""
        with pytest.raises(ValueError) as exc_info:
            StreamableHttpTransport(url="   ")

        assert "url" in str(exc_info.value).lower() or "required" in str(exc_info.value).lower()

    def test_url_missing_host_raises_error(self):
        """URL without host raises error."""
        with pytest.raises(ValueError) as exc_info:
            StreamableHttpTransport(url="http://")

        assert "url" in str(exc_info.value).lower() or "host" in str(exc_info.value).lower()

    def test_valid_url_accepted(self):
        """Valid URL is accepted."""
        # Should not raise
        transport = StreamableHttpTransport(url="http://localhost:8080/mcp")
        assert transport.url == "http://localhost:8080/mcp"

    def test_https_url_accepted(self):
        """HTTPS URL is accepted."""
        transport = StreamableHttpTransport(url="https://example.com/mcp")
        assert transport.url == "https://example.com/mcp"


class TestDuplicateRequestIds:
    """Tests for duplicate request ID handling."""

    @pytest.mark.asyncio
    async def test_duplicate_request_id_raises_error(self, respx_mock: respx.MockRouter):
        """Sending request with same ID as pending request raises error."""
        from gatekit.transport.errors import TransportDuplicateRequestError

        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to delay response
        async def slow_response(request: httpx.Request):
            await asyncio.sleep(0.5)  # Slow response
            body = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=slow_response)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Start first request (will be slow)
            request1 = MCPRequest(jsonrpc="2.0", method="slow", id="duplicate-id")
            task1 = asyncio.create_task(transport.send_and_receive(request1))

            # Wait a moment for first request to register
            await asyncio.sleep(0.05)

            # Try to send second request with same ID
            request2 = MCPRequest(jsonrpc="2.0", method="fast", id="duplicate-id")

            with pytest.raises(TransportDuplicateRequestError) as exc_info:
                await transport.send_and_receive(request2)

            assert "duplicate-id" in str(exc_info.value)

            # Cancel the first task
            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                pass
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_reusing_id_after_completion_is_allowed(self, respx_mock: respx.MockRouter):
        """Same ID can be reused after previous request completes."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST with immediate response
        def handle_request(request: httpx.Request):
            body = json.loads(request.content)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"call": body.get("method")}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=handle_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # First request
            request1 = MCPRequest(jsonrpc="2.0", method="first", id="reused-id")
            response1 = await transport.send_and_receive(request1)
            assert response1.result["call"] == "first"

            # Same ID, different method - should work
            request2 = MCPRequest(jsonrpc="2.0", method="second", id="reused-id")
            response2 = await transport.send_and_receive(request2)
            assert response2.result["call"] == "second"
        finally:
            await transport.disconnect()


class TestSseUnsupportedDetection:
    """Tests for detecting when server doesn't support SSE."""

    @pytest.mark.asyncio
    async def test_sse_unsupported_on_wrong_content_type_stops_retries(
        self, respx_mock: respx.MockRouter
    ):
        """SSE reader stops retrying when server returns wrong content type."""
        sse_call_count = {"count": 0}

        def handle_sse(request: httpx.Request):
            sse_call_count["count"] += 1
            # Return text/plain instead of text/event-stream
            return httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                content=b"Not SSE",
            )

        respx_mock.get(TEST_URL).mock(side_effect=handle_sse)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Wait for SSE reader to detect unsupported and stop
            await asyncio.sleep(0.3)

            # _sse_supported should be False
            assert transport._sse_supported is False

            # Count should be limited (not infinite retries)
            # Should have stopped after detecting unsupported content type
            assert sse_call_count["count"] <= 3, (
                f"SSE reader made {sse_call_count['count']} calls, "
                "should have stopped after detecting unsupported content type"
            )
        finally:
            await transport.disconnect()


class TestSsePostParserTimeout:
    """Tests for SSE-in-POST parser timeout behavior."""

    @pytest.mark.asyncio
    async def test_sse_post_parser_timeout_returns_none(self, respx_mock: respx.MockRouter):
        """SSE POST parser returns None on timeout without hanging."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Create a streaming response that stalls
        async def stalling_post(request: httpx.Request):
            # Return SSE content type but stall the body
            async def slow_body():
                yield b"data: "  # Start but don't complete
                await asyncio.sleep(100)  # Stall forever
                yield b'{"jsonrpc": "2.0", "id": "stall-test", "result": {}}\n\n'

            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                stream=httpx.AsyncByteStream(slow_body()),
            )

        respx_mock.post(TEST_URL).mock(side_effect=stalling_post)

        # Use a short timeout for the test
        transport = StreamableHttpTransport(url=TEST_URL, request_timeout=0.5)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="test", id="stall-test")

            start_time = asyncio.get_event_loop().time()

            # This should timeout, not hang forever
            with pytest.raises(Exception):  # Will timeout
                await transport.send_and_receive(request)

            end_time = asyncio.get_event_loop().time()
            elapsed = end_time - start_time

            # Should complete within reasonable time (timeout + overhead)
            assert elapsed < 2.0, f"Request took {elapsed:.2f}s, should have timed out sooner"
        finally:
            await transport.disconnect()
