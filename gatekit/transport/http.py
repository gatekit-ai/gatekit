"""HTTP-based transport implementation for MCP servers using Streamable HTTP.

This module provides a transport implementation that communicates with
MCP servers via HTTP using the Streamable HTTP protocol (POST for requests,
GET+SSE for responses and notifications).
"""

import asyncio
import json
import logging
import ssl
import threading
from typing import Dict, Optional, Union

import httpx
from httpx_sse import aconnect_sse

from .base import Transport
from .errors import (
    TransportDisconnectedError,
    TransportTimeoutError,
    TransportConcurrencyLimitError,
    TransportProtocolError,
    TransportDuplicateRequestError,
    HttpConnectionError,
    HttpRequestError,
    HttpSessionExpired,
)
from ..protocol.messages import MCPRequest, MCPResponse, MCPNotification


logger = logging.getLogger(__name__)


class StreamableHttpTransport(Transport):
    """Transport implementation using HTTP Streamable protocol.

    This transport communicates with MCP servers via:
    - POST requests to send JSON-RPC requests
    - GET+SSE stream to receive responses and notifications

    Responses can arrive via POST response body (immediate) OR via SSE stream (async).
    The transport handles both channels and correlates responses by ID.

    Attributes:
        url: The MCP server endpoint URL
    """

    def __init__(
        self,
        url: str,
        request_timeout: float = 30.0,
        max_concurrent_requests: int = 100,
        max_reconnection_attempts: int = 2,
        tls_verify: bool = True,
    ):
        """Initialize the HTTP transport.

        Args:
            url: The MCP server endpoint URL (e.g., "http://localhost:8123/mcp")
            request_timeout: Timeout for individual requests in seconds (default 30s)
            max_concurrent_requests: Maximum number of concurrent requests allowed
            max_reconnection_attempts: Maximum SSE reconnection attempts (default 2)
            tls_verify: Whether to verify TLS certificates (default True).
                Set to False to disable verification (insecure, for testing only).

        Raises:
            ValueError: If URL is invalid or empty
            TypeError: If tls_verify is not a boolean
        """
        # Validate URL
        self._validate_url(url)

        # Validate tls_verify is boolean (custom CA paths are not supported)
        if not isinstance(tls_verify, bool):
            raise TypeError(
                f"tls_verify must be a boolean, got {type(tls_verify).__name__}. "
                "Custom CA certificate paths are not supported."
            )

        self.url = url
        self.request_timeout = request_timeout
        self._max_concurrent_requests = max_concurrent_requests
        self._max_reconnection_attempts = max_reconnection_attempts
        self._tls_verify = tls_verify

        # HTTP client
        self._client: Optional[httpx.AsyncClient] = None

        # Connection state
        self._connected = False
        self._running = False

        # SSE stream management
        self._sse_task: Optional[asyncio.Task] = None
        self._sse_restart_lock = asyncio.Lock()

        # Request/response correlation
        self._pending_requests: Dict[Union[str, int], asyncio.Future] = {}
        self._request_lock = asyncio.Lock()
        self._concurrent_request_count = 0

        # Notification queue
        self._notification_queue: asyncio.Queue = asyncio.Queue()

        # Session management
        self._session_id: Optional[str] = None

        # Metrics
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "requests_sent": 0,
            "requests_completed": 0,
            "requests_failed": 0,
            "notifications_received": 0,
        }

        # SSE resumption tracking
        self._last_event_id: Optional[str] = None

        # SSE support flag - set to False when server returns 405 or wrong content-type
        self._sse_supported: bool = True

    @staticmethod
    def _validate_url(url: str) -> None:
        """Validate URL format.

        Args:
            url: The URL to validate

        Raises:
            ValueError: If URL is invalid or empty
        """
        if not url or not url.strip():
            raise ValueError("URL is required")

        try:
            parsed = httpx.URL(url)
            if not parsed.host:
                raise ValueError("Invalid URL: missing host")
        except httpx.InvalidURL as e:
            raise ValueError(f"Invalid URL: {e}") from e

    def is_connected(self) -> bool:
        """Check if transport is currently connected.

        Returns:
            True if connected to the HTTP server, False otherwise
        """
        return self._connected and self._client is not None

    def _validate_tls_config(self) -> None:
        """Validate TLS configuration before connecting."""
        # Log warning if TLS verification is disabled
        if self._tls_verify is False:
            logger.warning(
                "TLS verification disabled - connection is insecure",
                extra={"url": self.url, "operation": "tls_config"},
            )

    async def connect(self) -> None:
        """Establish connection to the MCP server.

        Creates the HTTP client and starts the SSE reader task.

        Raises:
            HttpConnectionError: If connection fails
        """
        if self.is_connected():
            raise HttpConnectionError("Already connected")

        try:
            # Validate TLS configuration first
            self._validate_tls_config()

            # Create HTTP client with permissive timeout for SSE streaming
            # POST requests use explicit per-request timeout instead
            self._client = httpx.AsyncClient(
                verify=self._tls_verify,
                timeout=httpx.Timeout(
                    connect=self.request_timeout,
                    read=None,  # No read timeout - SSE streams can be idle
                    write=self.request_timeout,
                    pool=self.request_timeout,
                ),
            )

            logger.info(
                "Connecting to MCP server",
                extra={"url": self.url, "operation": "connect"},
            )

            # Start SSE reader background task
            # Note: Connection failures (DNS, refused, etc.) will surface on first
            # request rather than during connect(). This is intentional - the SSE
            # reader handles reconnection and we don't want to block connect() on
            # network verification.
            self._running = True
            self._connected = True
            self._sse_task = asyncio.create_task(self._sse_reader())

            logger.info(
                "Connected to MCP server",
                extra={"url": self.url, "operation": "connect"},
            )

        except HttpConnectionError:
            # Re-raise our own errors without wrapping
            raise
        except ssl.SSLError as e:
            logger.exception(
                "TLS certificate error",
                extra={"url": self.url, "error": str(e), "operation": "connect"},
            )
            self._connected = False
            if self._client:
                await self._client.aclose()
                self._client = None
            raise HttpConnectionError(
                f"TLS certificate verification failed: {e}"
            ) from e
        except Exception as e:
            logger.exception(
                "Failed to connect to MCP server",
                extra={"url": self.url, "error": str(e), "operation": "connect"},
            )
            self._connected = False
            if self._client:
                await self._client.aclose()
                self._client = None
            raise HttpConnectionError(f"Failed to connect: {e}") from e

    async def _terminate_session(self) -> None:
        """Send DELETE to terminate session (fire-and-forget).

        Per MCP spec, session termination is optional and servers may respond 405.
        This method catches all errors to ensure it never blocks disconnect.
        """
        if not self._session_id or not self._client:
            return

        try:
            headers = {"Mcp-Session-Id": self._session_id}
            response = await self._client.delete(self.url, headers=headers)
            logger.debug(
                f"Session termination response: {response.status_code}",
                extra={"session_id": self._session_id},
            )
        except Exception as e:
            logger.debug(f"Session termination failed (may be normal): {e}")

    async def disconnect(self) -> None:
        """Close connection to the MCP server.

        Cancels the SSE reader, cleans up pending requests, and closes the HTTP client.
        Safe to call even if not connected.
        """
        if not self._client:
            return

        logger.info(
            "Disconnecting from MCP server",
            extra={"url": self.url, "operation": "disconnect"},
        )

        # Terminate session if we have one (fire-and-forget with timeout)
        if self._session_id:
            try:
                await asyncio.wait_for(self._terminate_session(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.debug("Session termination timed out")

        # Stop SSE reader
        self._running = False
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await asyncio.wait_for(self._sse_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as e:
                logger.debug(f"Error during SSE reader cleanup: {e}")

        # Notify pending requests
        async with self._request_lock:
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(TransportDisconnectedError("receive"))
                    try:
                        future.exception()
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        pass
            self._pending_requests.clear()
            self._concurrent_request_count = 0

        # Signal notification consumers and drain queue
        # Push sentinel (None) to unblock waiting consumers
        try:
            self._notification_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass  # Queue is full, consumers will see disconnected state

        # Drain remaining items from notification queue
        while not self._notification_queue.empty():
            try:
                self._notification_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Close HTTP client
        if self._client:
            await self._client.aclose()
            self._client = None

        self._connected = False
        self._session_id = None  # Clear session ID
        logger.info("Disconnected from MCP server")

    async def _sse_reader(self) -> None:
        """Background task to read SSE stream for responses and notifications.

        This task opens a GET request with SSE and routes incoming messages
        to either pending requests (responses) or notification queue.
        Implements SSE resumption with Last-Event-Id header on reconnection.

        If the server returns 405 (Method Not Allowed) on GET, it means the
        server doesn't support SSE notifications. We stop permanently in that
        case - the server can still handle request/response via POST.
        """
        reconnection_attempts = 0

        while self._running and reconnection_attempts <= self._max_reconnection_attempts:
            try:
                # Build headers for SSE connection
                headers = {
                    "Accept": "text/event-stream",
                    "Cache-Control": "no-store",
                }
                if self._session_id:
                    headers["Mcp-Session-Id"] = self._session_id
                # Include Last-Event-Id on reconnection for resumption
                if self._last_event_id:
                    headers["Last-Event-Id"] = self._last_event_id

                async with aconnect_sse(
                    self._client, "GET", self.url, headers=headers
                ) as event_source:
                    reconnection_attempts = 0  # Reset on successful connection
                    logger.debug("SSE stream connected")

                    async for sse_event in event_source.aiter_sse():
                        if not self._running:
                            break

                        # Track event ID for resumption
                        if sse_event.id:
                            self._last_event_id = sse_event.id

                        if sse_event.data:
                            try:
                                message_dict = json.loads(sse_event.data)
                                await self._route_sse_message(message_dict)
                            except json.JSONDecodeError as e:
                                logger.warning(
                                    f"Failed to parse SSE data: {e}",
                                    extra={"data": sse_event.data[:100]},
                                )

            except asyncio.CancelledError:
                logger.debug("SSE reader cancelled")
                break
            except httpx.HTTPStatusError as e:
                # 405 means server doesn't support GET/SSE - stop permanently
                if e.response.status_code == 405:
                    logger.info(
                        "Server does not support SSE notifications (HTTP 405), "
                        "disabling notification listener"
                    )
                    self._sse_supported = False
                    break
                logger.warning(f"SSE stream HTTP error: {e.response.status_code}")
                reconnection_attempts += 1
            except httpx.HTTPError as e:
                # Check if error message indicates 405 or content-type mismatch
                # httpx-sse converts HTTP errors to content-type errors in some cases
                error_str = str(e).lower()
                if "405" in error_str or "method not allowed" in error_str:
                    logger.info(
                        "Server does not support SSE notifications (HTTP 405), "
                        "disabling notification listener"
                    )
                    self._sse_supported = False
                    break
                # Content-Type mismatch means server doesn't support SSE
                if "text/event-stream" in error_str and "content-type" in error_str:
                    logger.info(
                        "Server does not support SSE notifications (wrong Content-Type), "
                        "disabling notification listener"
                    )
                    self._sse_supported = False
                    break
                logger.warning(f"SSE stream error: {e}")
                reconnection_attempts += 1
            except Exception as e:
                # Check for Content-Type mismatch which indicates no SSE support
                error_str = str(e).lower()
                if "text/event-stream" in error_str and "content-type" in error_str:
                    logger.info(
                        "Server does not support SSE notifications (wrong Content-Type), "
                        "disabling notification listener"
                    )
                    self._sse_supported = False
                    break
                if self._running:
                    logger.exception(f"SSE reader error: {e}")
                reconnection_attempts += 1

            if self._running and reconnection_attempts <= self._max_reconnection_attempts:
                logger.debug(
                    f"Attempting SSE reconnection ({reconnection_attempts}/{self._max_reconnection_attempts})"
                )
                await asyncio.sleep(0.1)  # Brief delay before reconnect

        logger.debug("SSE reader stopped")

    async def _route_sse_message(self, message_dict: dict) -> None:
        """Route an SSE message to the appropriate handler.

        Args:
            message_dict: Parsed JSON-RPC message
        """
        if "id" in message_dict:
            # Response - deliver to waiting request
            await self._route_response(message_dict)
        else:
            # Notification - queue for processing
            await self._route_notification(message_dict)

    async def _route_response(self, message_dict: dict) -> None:
        """Route a response message to the waiting request.

        Uses Future.set_result() which is idempotent - if the response
        was already delivered via POST, this is a no-op.

        Args:
            message_dict: The JSON-RPC response
        """
        request_id = message_dict.get("id")
        if request_id is None:
            return

        async with self._request_lock:
            if request_id in self._pending_requests:
                future = self._pending_requests[request_id]
                if not future.done():
                    future.set_result(message_dict)
                    logger.debug(
                        f"Response routed to request {request_id}",
                        extra={"request_id": request_id, "source": "sse"},
                    )
                # If future is already done, response was delivered via POST - ignore duplicate
            else:
                logger.debug(
                    f"Received response for unknown request ID: {request_id}"
                )

    async def _route_notification(self, message_dict: dict) -> None:
        """Route a notification message to the notification queue.

        Args:
            message_dict: The JSON-RPC notification
        """
        try:
            notification = MCPNotification(
                jsonrpc=message_dict.get("jsonrpc", "2.0"),
                method=message_dict["method"],
                params=message_dict.get("params"),
            )
            await self._notification_queue.put(notification)
            with self._metrics_lock:
                self._metrics["notifications_received"] += 1
            logger.debug(
                f"Notification queued: {notification.method}",
                extra={"method": notification.method},
            )
        except KeyError as e:
            logger.warning(f"Invalid notification (missing {e}): {message_dict}")

    async def _send_post_request(
        self, request: MCPRequest, handle_response: bool = False
    ) -> Optional[dict]:
        """Send POST request to MCP server.

        Args:
            request: The MCP request to send
            handle_response: If True, handle immediate JSON response

        Returns:
            Response dict if handle_response=True and immediate response received,
            None otherwise
        """
        # Serialize request
        request_dict = {
            "jsonrpc": request.jsonrpc,
            "method": request.method,
            "id": request.id,
        }
        if request.params is not None:
            request_dict["params"] = request.params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # Add session ID header if we have one
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        logger.debug(
            f"Sending POST request: {request.method}",
            extra={"request_id": request.id, "method": request.method},
        )

        with self._metrics_lock:
            self._metrics["requests_sent"] += 1

        try:
            async with self._client.stream(
                "POST",
                self.url,
                json=request_dict,
                headers=headers,
                timeout=self.request_timeout,  # Explicit timeout for POST
            ) as response:
                # Check for session expiry: 404 with session ID
                if response.status_code == 404 and self._session_id:
                    with self._metrics_lock:
                        self._metrics["requests_failed"] += 1
                    # Clear stale session state so next request can establish fresh session
                    self._session_id = None
                    self._last_event_id = None  # Old event IDs invalid for new session
                    raise HttpSessionExpired("Session has expired")

                if response.status_code >= 400:
                    with self._metrics_lock:
                        self._metrics["requests_failed"] += 1
                    # Provide helpful error messages for common HTTP errors
                    error_details = {
                        400: "Bad Request",
                        401: "Unauthorized",
                        403: "Forbidden",
                        404: "Not Found",
                        405: "Method Not Allowed",
                        500: "Internal Server Error",
                        502: "Bad Gateway",
                        503: "Service Unavailable",
                    }
                    detail = error_details.get(response.status_code, "")
                    error_msg = f"HTTP {response.status_code}"
                    if detail:
                        error_msg += f" {detail}"
                    raise HttpRequestError(
                        error_msg,
                        status_code=response.status_code,
                    )

                # Extract session ID from response headers (only set once)
                # httpx headers are case-insensitive
                session_id = response.headers.get("mcp-session-id")
                if session_id and not self._session_id:
                    self._session_id = session_id
                    logger.debug(f"Session ID acquired: {session_id}")
                    await self._restart_sse_stream()

                # Handle response based on Content-Type
                if handle_response:
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        try:
                            body = await response.aread()
                            response_data = json.loads(body.decode("utf-8"))
                            return response_data
                        except (json.JSONDecodeError, UnicodeDecodeError) as e:
                            with self._metrics_lock:
                                self._metrics["requests_failed"] += 1
                            raise TransportProtocolError(
                                f"Malformed JSON in response: {e}",
                                data=body[:200] if "body" in locals() else None,
                            ) from e
                    elif "text/event-stream" in content_type:
                        # SSE response in POST body - parse SSE events from body
                        return await self._parse_sse_post_response(response, request.id)
                    elif response.status_code == 202:
                        # 202 Accepted - response comes via SSE stream
                        return None
                    else:
                        # Unexpected content type
                        with self._metrics_lock:
                            self._metrics["requests_failed"] += 1
                        raise TransportProtocolError(
                            f"Unexpected content type: {content_type}",
                            data=content_type,
                        )

                content_type = response.headers.get("content-type", "")
                if "text/event-stream" not in content_type:
                    await response.aread()

                return None

        except HttpSessionExpired:
            raise
        except httpx.HTTPError as e:
            with self._metrics_lock:
                self._metrics["requests_failed"] += 1
            raise HttpConnectionError(f"HTTP request failed: {e}") from e

    async def _parse_sse_post_response(
        self, response: httpx.Response, request_id: Union[str, int]
    ) -> Optional[dict]:
        """Parse SSE response from POST body.

        When a POST returns text/event-stream, the response body contains
        SSE-formatted events. This method parses those events and returns
        the matching response.

        Note:
            This method applies request_timeout to prevent blocking indefinitely
            on slow/stalled streams. In the rare case where the POST body stalls
            and the response then arrives via SSE stream, the total wait time
            could approach 2× request_timeout. This is acceptable as it requires
            pathological server behavior (sending SSE content-type then stalling).

        Args:
            response: The HTTP response with SSE body
            request_id: The request ID to match

        Returns:
            Response dict if found, None otherwise
        """
        try:
            # Use timeout to prevent blocking indefinitely on slow/stalled streams
            return await asyncio.wait_for(
                self._parse_sse_post_response_inner(response, request_id),
                timeout=self.request_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout parsing SSE POST body for request {request_id} "
                f"after {self.request_timeout}s"
            )
            return None
        except Exception as e:
            logger.warning(f"Error parsing SSE POST body: {e}")
            return None

    async def _parse_sse_post_response_inner(
        self, response: httpx.Response, request_id: Union[str, int]
    ) -> Optional[dict]:
        """Inner method for parsing SSE POST response body.

        Separated to allow timeout wrapper in _parse_sse_post_response.

        Note:
            This parser assumes single-line JSON per data: event, which is the
            standard format for MCP JSON-RPC messages. Multi-line SSE data fields
            (per the full SSE spec) are not supported as MCP doesn't use them.
        """
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_part = line[5:].strip()
            if not data_part:
                continue
            try:
                message_dict = json.loads(data_part)
                # Check if this is the response we're looking for
                if message_dict.get("id") == request_id:
                    return message_dict
                # Also route other messages (responses/notifications)
                await self._route_sse_message(message_dict)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in SSE body: {data_part[:100]}")

        # Response not found in body - will come via SSE stream
        return None

    async def send_notification(self, notification: MCPNotification) -> None:
        """Send a notification to the MCP server via POST.

        Args:
            notification: The MCP notification message to send

        Raises:
            TransportDisconnectedError: If not connected
            HttpRequestError: If HTTP request fails
        """
        if not self.is_connected():
            raise TransportDisconnectedError("send_notification")

        # Serialize notification
        notification_dict = {
            "jsonrpc": notification.jsonrpc,
            "method": notification.method,
        }
        if notification.params is not None:
            notification_dict["params"] = notification.params

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            response = await self._client.post(
                self.url,
                json=notification_dict,
                headers=headers,
                timeout=self.request_timeout,  # Explicit timeout for POST
            )
            # Check for session expiry: 404 with session ID
            if response.status_code == 404 and self._session_id:
                # Clear stale session state so next request can establish fresh session
                self._session_id = None
                self._last_event_id = None  # Old event IDs invalid for new session
                raise HttpSessionExpired("Session has expired")

            # Notifications may return 202 Accepted or 200 OK
            # Only raise for actual errors (4xx, 5xx except protocol-valid ones)
            if response.status_code >= 400:
                raise HttpRequestError(
                    f"Failed to send notification: {response.status_code}",
                    status_code=response.status_code,
                )
        except (HttpRequestError, HttpSessionExpired):
            raise
        except httpx.HTTPError as e:
            raise HttpConnectionError(f"Failed to send notification: {e}") from e

    async def send_and_receive(self, request: MCPRequest) -> MCPResponse:
        """Send a request and wait for its specific response.

        This method handles dual-channel response delivery:
        - Immediate response via POST body (Content-Type: application/json)
        - Async response via SSE stream (202 Accepted)

        First response wins - if both channels deliver, the second is ignored.

        Args:
            request: The MCP request to send

        Returns:
            The specific response for this request

        Raises:
            TransportDisconnectedError: If not connected
            TransportConcurrencyLimitError: If concurrent request limit exceeded
            TransportTimeoutError: If response timeout occurs
            HttpRequestError: If HTTP request fails
        """
        if not self.is_connected():
            raise TransportDisconnectedError("send_and_receive")

        # Check concurrent request limit
        async with self._request_lock:
            if self._concurrent_request_count >= self._max_concurrent_requests:
                raise TransportConcurrencyLimitError(
                    limit=self._max_concurrent_requests,
                    current=self._concurrent_request_count,
                )
            self._concurrent_request_count += 1

        try:
            # Register for response correlation
            async with self._request_lock:
                # Check for duplicate request ID
                if request.id in self._pending_requests:
                    raise TransportDuplicateRequestError(request.id)
                future = asyncio.Future()
                self._pending_requests[request.id] = future

            try:
                # Send POST request and check for immediate response
                immediate_response = await self._send_post_request(
                    request, handle_response=True
                )

                if immediate_response:
                    # Validate response ID matches request ID before routing
                    response_id = immediate_response.get("id")
                    if response_id != request.id:
                        logger.warning(
                            f"Response ID mismatch: expected {request.id}, got {response_id}",
                            extra={
                                "expected_id": request.id,
                                "received_id": response_id,
                                "source": "post",
                            },
                        )
                        # Don't route mismatched response - wait for correct one via SSE
                    else:
                        # Route immediate response to future (may already be set by SSE)
                        async with self._request_lock:
                            if request.id in self._pending_requests:
                                pending_future = self._pending_requests[request.id]
                                if not pending_future.done():
                                    pending_future.set_result(immediate_response)
                                    logger.debug(
                                        f"Immediate response for {request.id}",
                                        extra={"request_id": request.id, "source": "post"},
                                    )

                # Wait for response (from either channel)
                try:
                    response_dict = await asyncio.wait_for(
                        future, timeout=self.request_timeout
                    )

                    with self._metrics_lock:
                        self._metrics["requests_completed"] += 1

                    return self._parse_response(response_dict)

                except asyncio.TimeoutError as e:
                    with self._metrics_lock:
                        self._metrics["requests_failed"] += 1
                    raise TransportTimeoutError(
                        f"Request {request.id} timed out after {self.request_timeout} seconds",
                        timeout=self.request_timeout,
                        operation="send_and_receive",
                    ) from e

            finally:
                # Clean up pending request
                async with self._request_lock:
                    self._pending_requests.pop(request.id, None)

        finally:
            async with self._request_lock:
                self._concurrent_request_count -= 1

    async def _restart_sse_stream(self) -> None:
        """Restart the SSE stream to include updated session headers.

        Called when a session ID is acquired from the server. Clears the
        last event ID since the new session context invalidates old event IDs.

        Note: This is NOT for mid-session reconnects - those are handled
        by _sse_reader's internal retry loop which preserves _last_event_id.
        """
        if not self._running:
            return

        # Don't restart if server doesn't support SSE
        if not self._sse_supported:
            logger.debug("Skipping SSE restart - server does not support SSE")
            return

        async with self._sse_restart_lock:
            if not self._running:
                return
            if self._sse_task and not self._sse_task.done():
                self._sse_task.cancel()
                try:
                    await asyncio.wait_for(self._sse_task, timeout=1.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:
                    logger.debug(f"Error during SSE restart cleanup: {e}")
            # Clear event ID since we're starting a new session context
            self._last_event_id = None
            self._sse_task = asyncio.create_task(self._sse_reader())

    def _parse_response(self, response_dict: dict) -> MCPResponse:
        """Parse a response dictionary into MCPResponse.

        Args:
            response_dict: The JSON-RPC response dictionary

        Returns:
            Parsed MCPResponse
        """
        if "error" in response_dict and response_dict["error"] is not None:
            return MCPResponse(
                jsonrpc=response_dict.get("jsonrpc", "2.0"),
                id=response_dict.get("id"),
                error=response_dict["error"],
            )
        else:
            return MCPResponse(
                jsonrpc=response_dict.get("jsonrpc", "2.0"),
                id=response_dict.get("id"),
                result=response_dict.get("result"),
            )

    async def get_next_notification(self) -> MCPNotification:
        """Get next notification from the queue.

        Blocks until a notification is available.

        Note:
            This method is designed for single-consumer use. If multiple
            consumers call this method concurrently, only one will receive
            each notification. For multiple consumers, use a single consumer
            that fans out to others.

        Returns:
            The next available notification from the server

        Raises:
            TransportDisconnectedError: If not connected or transport disconnects
                while waiting
        """
        if not self.is_connected():
            raise TransportDisconnectedError("get_next_notification")

        notification = await self._notification_queue.get()

        # Check for sentinel (None) indicating disconnection
        if notification is None:
            raise TransportDisconnectedError("get_next_notification")

        return notification

    async def notifications(self):
        """Async iterator for receiving notifications.

        Yields:
            MCPNotification: The next notification from the server

        Stops iteration when:
        - Transport is disconnected
        - A sentinel value (None) is received indicating shutdown
        - An error occurs
        """
        while self.is_connected() and self._running:
            try:
                notification = await self._notification_queue.get()
                # Check for sentinel (None) indicating disconnection
                if notification is None:
                    break
                yield notification
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in notification iterator: {e}")
                break

    def get_metrics(self) -> Dict[str, int]:
        """Get current transport metrics.

        Returns:
            Dictionary of metric counters
        """
        with self._metrics_lock:
            return self._metrics.copy()
