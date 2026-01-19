"""Mock transport implementation for testing concurrent requests."""

import asyncio
from typing import Dict, List, Optional, Union, Callable
from gatekit.transport.base import Transport
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class MockTransport(Transport):
    """Mock transport for testing that simulates concurrent behavior.

    This transport allows tests to simulate various concurrent scenarios
    without the complexity of real subprocess management.
    """

    def __init__(
        self, response_delay: float = 0.0, response_handler: Optional[Callable] = None
    ):
        """Initialize mock transport.

        Args:
            response_delay: Simulated delay for responses (seconds)
            response_handler: Optional custom handler for generating responses
        """
        self.response_delay = response_delay
        self.response_handler = response_handler
        self._connected = False
        self._pending_requests: Dict[Union[str, int], asyncio.Future] = {}
        self._request_queue: asyncio.Queue = asyncio.Queue()

        # Separate queues for tracking notification direction
        self._client_to_server_notifications: asyncio.Queue = asyncio.Queue()
        self._server_to_client_notifications: asyncio.Queue = asyncio.Queue()

        # Legacy queue for backward compatibility
        self._notification_queue: asyncio.Queue = self._client_to_server_notifications

        self._response_processor_task: Optional[asyncio.Task] = None
        self._request_lock = asyncio.Lock()
        self._is_mock = True  # Flag to identify this as a mock transport

        # Track request processing for testing
        self.request_count = 0
        self.active_requests = 0
        self.max_concurrent = 0
        self.processed_requests: List[Dict] = []
        self._max_concurrent_requests = 100  # Default limit matching StdioTransport

    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._connected

    async def connect(self) -> None:
        """Simulate connection establishment."""
        if self._connected:
            raise RuntimeError("Already connected")

        self._connected = True
        self._response_processor_task = asyncio.create_task(self._process_requests())

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        if not self._connected:
            return

        self._connected = False

        # Cancel response processor
        if self._response_processor_task and not self._response_processor_task.done():
            self._response_processor_task.cancel()
            try:
                await self._response_processor_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass  # Ignore other exceptions during cleanup

        # Notify pending requests
        async with self._request_lock:
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(RuntimeError("Transport disconnected"))
            self._pending_requests.clear()

    async def send_message(self, message: MCPRequest) -> None:
        """Send a request message."""
        if not self._connected:
            raise RuntimeError("Not connected")

        # Register pending request
        async with self._request_lock:
            future = asyncio.Future()
            self._pending_requests[message.id] = future

        # Queue request for processing
        await self._request_queue.put(message)

    async def send_notification(self, notification: MCPNotification) -> None:
        """Send a notification from client to server."""
        if not self._connected:
            raise RuntimeError("Not connected")

        # Queue in client->server direction
        await self._client_to_server_notifications.put(notification)

    async def receive_message(self) -> MCPResponse:
        """Receive a response message."""
        if not self._connected:
            raise RuntimeError("Not connected")

        # Wait for any pending response
        async with self._request_lock:
            if not self._pending_requests:
                raise RuntimeError("No pending requests")
            pending_futures = list(self._pending_requests.values())

        # Wait for first completed response with a timeout
        try:
            done, pending = await asyncio.wait(
                pending_futures,
                timeout=60.0,  # Long timeout to avoid premature timeouts
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.TimeoutError:
            raise RuntimeError("Timeout waiting for response")

        if not done:
            raise RuntimeError("No responses available")

        # Get completed response
        completed_future = done.pop()
        response = completed_future.result()

        # Don't clean up here - let the caller do it
        # This matches the stdio transport behavior

        return response

    async def send_and_receive(self, request: MCPRequest) -> MCPResponse:
        """Send request and wait for its specific response."""
        if not self._connected:
            raise RuntimeError("Not connected")

        # Check concurrent request limit first
        async with self._request_lock:
            if self.active_requests >= self._max_concurrent_requests:
                raise RuntimeError(
                    f"Maximum concurrent requests ({self._max_concurrent_requests}) exceeded"
                )

        # Register pending request and increment counter
        request_registered = False
        async with self._request_lock:
            future = asyncio.Future()
            self._pending_requests[request.id] = future
            self.active_requests += 1
            self.max_concurrent = max(self.max_concurrent, self.active_requests)
            request_registered = True

        # Queue request for processing
        await self._request_queue.put(request)

        try:
            # Wait for specific response
            response = await asyncio.wait_for(future, timeout=10.0)
            return response
        except asyncio.TimeoutError:
            raise RuntimeError(f"Request {request.id} timed out")
        finally:
            # Only decrement if we actually incremented
            if request_registered:
                async with self._request_lock:
                    self._pending_requests.pop(request.id, None)
                    self.active_requests -= 1

    async def get_next_notification(self) -> MCPNotification:
        """Get next notification (legacy method, client->server)."""
        return await self.get_client_to_server_notification()

    async def send_server_notification(self, notification: MCPNotification) -> None:
        """Send a notification from server to client."""
        if not self._connected:
            raise RuntimeError("Not connected")

        # Queue in server->client direction
        await self._server_to_client_notifications.put(notification)

    async def get_client_to_server_notification(self) -> MCPNotification:
        """Get next client->server notification."""
        if not self._connected:
            raise RuntimeError("Not connected")

        try:
            notification = await asyncio.wait_for(
                self._client_to_server_notifications.get(), timeout=1.0
            )
            return notification
        except asyncio.TimeoutError:
            raise RuntimeError("No client->server notifications available")

    async def get_server_to_client_notification(self) -> MCPNotification:
        """Get next server->client notification."""
        if not self._connected:
            raise RuntimeError("Not connected")

        try:
            notification = await asyncio.wait_for(
                self._server_to_client_notifications.get(), timeout=1.0
            )
            return notification
        except asyncio.TimeoutError:
            raise RuntimeError("No server->client notifications available")

    def has_client_to_server_notifications(self) -> bool:
        """Check if there are pending client->server notifications."""
        return not self._client_to_server_notifications.empty()

    def has_server_to_client_notifications(self) -> bool:
        """Check if there are pending server->client notifications."""
        return not self._server_to_client_notifications.empty()

    async def _process_requests(self):
        """Process requests and generate responses."""
        while self._connected:
            try:
                # Get next request
                request = await asyncio.wait_for(self._request_queue.get(), timeout=0.1)

                # Track request
                self.request_count += 1
                self.processed_requests.append(
                    {
                        "id": request.id,
                        "method": request.method,
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                )

                # Process request asynchronously for true concurrency
                asyncio.create_task(self._generate_response(request))

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in mock request processor: {e}")

    async def _generate_response(self, request: MCPRequest):
        """Generate a response for a request."""
        try:
            # Simulate processing delay
            if self.response_delay > 0:
                await asyncio.sleep(self.response_delay)

            # Generate response
            if self.response_handler:
                response = await self.response_handler(request)
            else:
                # Default response
                response = MCPResponse(
                    jsonrpc="2.0",
                    id=request.id,
                    result={"status": "ok", "echo": request.method},
                )

            # Deliver response to waiting future
            async with self._request_lock:
                if request.id in self._pending_requests:
                    future = self._pending_requests.pop(request.id)
                    if not future.done():
                        future.set_result(response)

        except Exception as e:
            print(f"Error generating response for {request.id}: {e}")
            # Deliver error response
            async with self._request_lock:
                if request.id in self._pending_requests:
                    future = self._pending_requests.pop(request.id)
                    if not future.done():
                        future.set_exception(RuntimeError(f"Mock response error: {e}"))


class SequentialMockTransport(MockTransport):
    """Mock transport that processes requests sequentially."""

    async def _process_requests(self):
        """Process requests sequentially."""
        while self._connected:
            try:
                # Get next request
                request = await asyncio.wait_for(self._request_queue.get(), timeout=0.1)

                # Process synchronously
                self.request_count += 1
                self.active_requests = 1  # Always 1 for sequential
                self.max_concurrent = 1

                # Record request
                self.processed_requests.append(
                    {
                        "id": request.id,
                        "method": request.method,
                        "timestamp": asyncio.get_event_loop().time(),
                    }
                )

                # Generate response synchronously
                await self._generate_response(request)

            except asyncio.TimeoutError:
                continue
            except Exception:
                break
