"""Unit tests for HTTP session management in StreamableHttpTransport.

Tests for MCP session protocol per MCP spec (2025-03-26):
- Session header: Mcp-Session-Id (case-insensitive)
- Server returns session ID in response headers on first request
- Client includes session ID in all subsequent requests
- Session termination: DELETE to MCP endpoint with session header
- Session expiry: Server returns 404 for request with session ID

Written using TDD - tests first, then implementation.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from gatekit.transport.http import StreamableHttpTransport
from gatekit.transport.errors import HttpSessionExpired, HttpRequestError
from gatekit.protocol.messages import MCPRequest, MCPNotification


# Test URL used across tests
TEST_URL = "http://localhost:8123/mcp"


class TestSessionIdExtraction:
    """Tests for extracting session ID from response headers."""

    @pytest.mark.asyncio
    async def test_session_id_extracted_from_response_header(
        self, respx_mock: respx.MockRouter
    ):
        """Extract Mcp-Session-Id from POST response."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST endpoint returning session ID in header
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": "session-abc-123",
                },
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": "req-1",
                    "result": {"initialized": True}
                }).encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="initialize", id="req-1")
            await transport.send_and_receive(request)

            # Session ID should be extracted and stored
            assert transport._session_id == "session-abc-123"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_session_id_case_insensitive(self, respx_mock: respx.MockRouter):
        """Works with mcp-session-id lowercase header (HTTP headers are case-insensitive)."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST endpoint with lowercase header name
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "mcp-session-id": "session-lowercase-456",
                },
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": "req-1",
                    "result": {}
                }).encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            request = MCPRequest(jsonrpc="2.0", method="initialize", id="req-1")
            await transport.send_and_receive(request)

            # Session ID should be extracted regardless of case
            assert transport._session_id == "session-lowercase-456"
        finally:
            await transport.disconnect()


class TestSessionIdPropagation:
    """Tests for sending session ID on subsequent requests."""

    @pytest.mark.asyncio
    async def test_session_id_sent_on_subsequent_requests(
        self, respx_mock: respx.MockRouter
    ):
        """After extracting session ID, send it on all future requests."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Track headers from each request
        captured_headers = []

        def capture_request(request: httpx.Request):
            captured_headers.append(dict(request.headers))
            body = json.loads(request.content)
            # Return session ID on first request only
            headers = {"Content-Type": "application/json"}
            if body["id"] == "req-1":
                headers["Mcp-Session-Id"] = "session-xyz-789"
            return httpx.Response(
                200,
                headers=headers,
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=capture_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # First request - should NOT have session ID header
            request1 = MCPRequest(jsonrpc="2.0", method="initialize", id="req-1")
            await transport.send_and_receive(request1)

            # Second request - should have session ID header
            request2 = MCPRequest(jsonrpc="2.0", method="ping", id="req-2")
            await transport.send_and_receive(request2)

            # Third request - should also have session ID header
            request3 = MCPRequest(jsonrpc="2.0", method="ping", id="req-3")
            await transport.send_and_receive(request3)

            # Verify first request did NOT have session header
            assert "mcp-session-id" not in captured_headers[0]

            # Verify second and third requests HAVE session header
            assert captured_headers[1].get("mcp-session-id") == "session-xyz-789"
            assert captured_headers[2].get("mcp-session-id") == "session-xyz-789"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_no_session_header_when_server_stateless(
        self, respx_mock: respx.MockRouter
    ):
        """No session ID in response = no header sent on subsequent requests."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Track headers from each request
        captured_headers = []

        def capture_request(request: httpx.Request):
            captured_headers.append(dict(request.headers))
            body = json.loads(request.content)
            # Never return session ID
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=capture_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Multiple requests to a stateless server
            for i in range(3):
                request = MCPRequest(jsonrpc="2.0", method="ping", id=f"req-{i}")
                await transport.send_and_receive(request)

            # Verify NO requests have session header
            for headers in captured_headers:
                assert "mcp-session-id" not in headers

            # Verify transport has no session ID
            assert transport._session_id is None
        finally:
            await transport.disconnect()


class TestSessionIdOnSseAndNotifications:
    """Tests for session ID propagation to SSE and notifications."""

    @pytest.mark.asyncio
    async def test_sse_reconnect_includes_session_id(
        self, respx_mock: respx.MockRouter
    ):
        """SSE reconnect includes Mcp-Session-Id after session is acquired."""
        captured_headers = []
        sse_call_count = {"count": 0}

        def handle_sse(request: httpx.Request):
            headers_copy = dict(request.headers)
            captured_headers.append(headers_copy)
            sse_call_count["count"] += 1
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b": keep-alive\n\n",  # Use simple content instead of streaming
            )

        respx_mock.get(TEST_URL).mock(side_effect=handle_sse)

        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": "session-sse-123",
                },
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": "req-1",
                    "result": {"initialized": True}
                }).encode(),
            )
        )

        transport = StreamableHttpTransport(url=TEST_URL)

        # Verify transport has no session ID initially
        assert transport._session_id is None

        await transport.connect()

        # Wait for SSE reader background task to start
        for _ in range(10):
            if sse_call_count["count"] >= 1:
                break
            await asyncio.sleep(0.05)

        try:
            # First SSE call should have been made by connect(), without session ID
            assert len(captured_headers) >= 1, f"Expected SSE call during connect(), got {len(captured_headers)}"
            first_sse_session_id = captured_headers[0].get("mcp-session-id")
            assert first_sse_session_id is None, f"First SSE call should not have session ID, got: {first_sse_session_id}"

            request = MCPRequest(jsonrpc="2.0", method="initialize", id="req-1")
            await transport.send_and_receive(request)

            # Allow restart to occur - retry up to 10 times
            for _ in range(10):
                if sse_call_count["count"] >= 2:
                    break
                await asyncio.sleep(0.1)

            assert len(captured_headers) >= 2, f"Expected at least 2 SSE calls, got {len(captured_headers)}"
            assert captured_headers[1].get("mcp-session-id") == "session-sse-123"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_notification_includes_session_id(
        self, respx_mock: respx.MockRouter
    ):
        """Notifications include Mcp-Session-Id once session is established."""
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        captured_headers = {}

        def capture_notification(request: httpx.Request):
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, content=b"")

        respx_mock.post(TEST_URL).mock(side_effect=capture_notification)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            transport._session_id = "session-notify-456"
            await transport.send_notification(
                MCPNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                    params={"ready": True},
                )
            )

            assert captured_headers.get("mcp-session-id") == "session-notify-456"
        finally:
            await transport.disconnect()


class TestConcurrentRequestsWithSession:
    """Tests for concurrent request handling within a session."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_include_session_id(
        self, respx_mock: respx.MockRouter
    ):
        """All concurrent requests include same session ID."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Track headers from each request
        captured_headers = []
        request_order = []

        async def capture_request(request: httpx.Request):
            headers_copy = dict(request.headers)
            captured_headers.append(headers_copy)
            body = json.loads(request.content)
            request_order.append(body["id"])
            # Small delay to allow concurrency
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=capture_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Manually set session ID to simulate already having one
            transport._session_id = "session-concurrent-test"

            # Send multiple concurrent requests
            requests = [
                MCPRequest(jsonrpc="2.0", method="test", id=f"concurrent-{i}")
                for i in range(5)
            ]

            await asyncio.gather(*[
                transport.send_and_receive(req) for req in requests
            ])

            # All requests should have the same session ID
            for headers in captured_headers:
                assert headers.get("mcp-session-id") == "session-concurrent-test"
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_concurrent_requests_dont_block_each_other(
        self, respx_mock: respx.MockRouter
    ):
        """Requests don't serialize, run in parallel."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Track timing and order
        request_timestamps = {}
        response_timestamps = {}

        async def handle_request(request: httpx.Request):
            body = json.loads(request.content)
            req_id = body["id"]
            request_timestamps[req_id] = asyncio.get_event_loop().time()
            # Simulate processing time
            await asyncio.sleep(0.05)
            response_timestamps[req_id] = asyncio.get_event_loop().time()
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=handle_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            start_time = asyncio.get_event_loop().time()

            # Send 3 concurrent requests (each takes 0.05s)
            requests = [
                MCPRequest(jsonrpc="2.0", method="test", id=f"parallel-{i}")
                for i in range(3)
            ]

            await asyncio.gather(*[
                transport.send_and_receive(req) for req in requests
            ])

            end_time = asyncio.get_event_loop().time()
            total_time = end_time - start_time

            # If running in parallel, should take ~0.05s (not 0.15s)
            # Allow some overhead, but should be less than serial time
            assert total_time < 0.12, (
                f"Requests appear to run serially (took {total_time:.3f}s, "
                "expected ~0.05s for parallel execution)"
            )

            # All requests should have started before any finished
            min_start = min(request_timestamps.values())
            max_start = max(request_timestamps.values())
            min_end = min(response_timestamps.values())

            # All requests should start before the first one finishes
            assert max_start < min_end, "Requests did not overlap - running serially"
        finally:
            await transport.disconnect()


class TestSessionExpiry:
    """Tests for session expiry detection."""

    @pytest.mark.asyncio
    async def test_session_expiry_404_raises_http_session_expired(
        self, respx_mock: respx.MockRouter
    ):
        """404 response with session ID raises HttpSessionExpired."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to return 404
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(404, content=b"Session not found")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Set session ID to simulate having an active session
            transport._session_id = "session-expired-test"

            request = MCPRequest(jsonrpc="2.0", method="ping", id="req-1")

            with pytest.raises(HttpSessionExpired) as exc_info:
                await transport.send_and_receive(request)

            assert "session" in str(exc_info.value).lower()
            assert "expired" in str(exc_info.value).lower()
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_session_expiry_clears_session_id(
        self, respx_mock: respx.MockRouter
    ):
        """Session expiry clears _session_id so next request can establish fresh session."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to return 404
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(404, content=b"Session not found")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Set session ID to simulate having an active session
            transport._session_id = "session-to-be-cleared"

            request = MCPRequest(jsonrpc="2.0", method="ping", id="req-1")

            with pytest.raises(HttpSessionExpired):
                await transport.send_and_receive(request)

            # Session ID should be cleared after expiry
            assert transport._session_id is None
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_send_notification_session_expiry_raises_http_session_expired(
        self, respx_mock: respx.MockRouter
    ):
        """404 response on send_notification with session ID raises HttpSessionExpired."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to return 404
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(404, content=b"Session not found")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Set session ID to simulate having an active session
            transport._session_id = "session-notify-expired"

            notification = MCPNotification(
                jsonrpc="2.0",
                method="notifications/progress",
                params={"progress": 50},
            )

            with pytest.raises(HttpSessionExpired) as exc_info:
                await transport.send_notification(notification)

            assert "session" in str(exc_info.value).lower()
            # Session ID should be cleared
            assert transport._session_id is None
        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_404_without_session_is_regular_error(
        self, respx_mock: respx.MockRouter
    ):
        """404 without session ID is just HttpRequestError."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST to return 404
        respx_mock.post(TEST_URL).mock(
            return_value=httpx.Response(404, content=b"Not found")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # No session ID - stateless server
            assert transport._session_id is None

            request = MCPRequest(jsonrpc="2.0", method="ping", id="req-1")

            # Should raise HttpRequestError, NOT HttpSessionExpired
            with pytest.raises(HttpRequestError) as exc_info:
                await transport.send_and_receive(request)

            assert exc_info.value.status_code == 404
            # Should NOT be HttpSessionExpired
            assert not isinstance(exc_info.value, HttpSessionExpired)
        finally:
            await transport.disconnect()


class TestSessionTermination:
    """Tests for session termination on disconnect."""

    @pytest.mark.asyncio
    async def test_disconnect_sends_delete_for_session(
        self, respx_mock: respx.MockRouter
    ):
        """disconnect() sends DELETE with session header."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Track DELETE request
        delete_requests = []

        def capture_delete(request: httpx.Request):
            delete_requests.append({
                "method": request.method,
                "headers": dict(request.headers),
            })
            return httpx.Response(204)  # No Content

        respx_mock.delete(TEST_URL).mock(side_effect=capture_delete)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        # Set session ID
        transport._session_id = "session-to-terminate"

        await transport.disconnect()

        # Should have sent DELETE request with session header
        assert len(delete_requests) == 1
        assert delete_requests[0]["headers"].get("mcp-session-id") == "session-to-terminate"

    @pytest.mark.asyncio
    async def test_disconnect_handles_delete_405_gracefully(
        self, respx_mock: respx.MockRouter
    ):
        """Server responding 405 doesn't raise error."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Server doesn't support DELETE
        respx_mock.delete(TEST_URL).mock(
            return_value=httpx.Response(405, content=b"Method Not Allowed")
        )

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        # Set session ID
        transport._session_id = "session-delete-not-supported"

        # disconnect() should complete without error
        await transport.disconnect()

        # Transport should be properly disconnected
        assert not transport.is_connected()

    @pytest.mark.asyncio
    async def test_disconnect_handles_delete_timeout_gracefully(
        self, respx_mock: respx.MockRouter
    ):
        """DELETE timeout doesn't block disconnect."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # DELETE hangs forever (will be cancelled by timeout)
        async def slow_delete(request: httpx.Request):
            await asyncio.sleep(100)  # "Forever"
            return httpx.Response(204)

        respx_mock.delete(TEST_URL).mock(side_effect=slow_delete)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        # Set session ID
        transport._session_id = "session-slow-delete"

        start_time = asyncio.get_event_loop().time()

        # disconnect() should complete within reasonable time (5s timeout + overhead)
        await transport.disconnect()

        end_time = asyncio.get_event_loop().time()
        elapsed = end_time - start_time

        # Should complete much faster than the 100s hang
        assert elapsed < 10, f"disconnect() took too long: {elapsed:.2f}s"

        # Transport should be properly disconnected
        assert not transport.is_connected()

    @pytest.mark.asyncio
    async def test_no_delete_sent_for_stateless_server(
        self, respx_mock: respx.MockRouter
    ):
        """No DELETE if no session ID was received."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Track any DELETE requests
        delete_called = {"count": 0}

        def capture_delete(request: httpx.Request):
            delete_called["count"] += 1
            return httpx.Response(204)

        respx_mock.delete(TEST_URL).mock(side_effect=capture_delete)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        # No session ID (stateless server)
        assert transport._session_id is None

        await transport.disconnect()

        # Should NOT have sent DELETE request
        assert delete_called["count"] == 0


class TestSessionIdNotOverwritten:
    """Tests to ensure session ID is only set once."""

    @pytest.mark.asyncio
    async def test_session_id_not_overwritten_by_subsequent_responses(
        self, respx_mock: respx.MockRouter
    ):
        """Session ID from first response is kept, even if later responses have different IDs."""
        # Mock SSE endpoint
        respx_mock.get(TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Return different session IDs on each request
        request_count = {"count": 0}

        def handle_request(request: httpx.Request):
            request_count["count"] += 1
            body = json.loads(request.content)
            return httpx.Response(
                200,
                headers={
                    "Content-Type": "application/json",
                    # Each response has a different session ID
                    "Mcp-Session-Id": f"session-{request_count['count']}",
                },
                content=json.dumps({
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {}
                }).encode(),
            )

        respx_mock.post(TEST_URL).mock(side_effect=handle_request)

        transport = StreamableHttpTransport(url=TEST_URL)
        await transport.connect()

        try:
            # Send multiple requests
            for i in range(3):
                request = MCPRequest(jsonrpc="2.0", method="ping", id=f"req-{i}")
                await transport.send_and_receive(request)

            # Session ID should still be from the first response
            assert transport._session_id == "session-1"
        finally:
            await transport.disconnect()
