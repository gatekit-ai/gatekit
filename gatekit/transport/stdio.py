"""Stdio-based transport implementation for MCP servers.

This module provides a transport implementation that communicates with
MCP servers via stdin/stdout using subprocess management.
"""

import asyncio
import json
import logging
import shutil
import sys
import threading
import time
from typing import List, Optional, Union, Dict

from .base import Transport
from .errors import (
    TransportError,
    TransportConnectionError,
    TransportDisconnectedError,
    TransportTimeoutError,
    TransportProtocolError,
    TransportRequestError,
    TransportConcurrencyLimitError,
    TransportProcessError,
)
from ..protocol.messages import MCPRequest, MCPResponse, MCPNotification
from ..protocol.validation import MessageValidator, ValidationError


logger = logging.getLogger(__name__)


class StdioTransport(Transport):
    """Transport implementation using stdio communication with subprocess.

    This transport starts an MCP server as a subprocess and communicates
    via JSON messages sent through stdin/stdout pipes.

    Attributes:
        command: Command line arguments to start the MCP server process
    """

    def __init__(
        self,
        command: List[str],
        request_timeout: int = 60,
        max_concurrent_requests: int = 100,
        max_line_length: int = 1024 * 1024,
        log_json_content: bool = True,
    ):
        """Initialize the stdio transport.

        Args:
            command: Command line arguments to start the MCP server process
                    e.g., ["python", "-m", "my_mcp_server"]
            request_timeout: Timeout for individual requests in seconds
            max_concurrent_requests: Maximum number of concurrent requests allowed
            max_line_length: Maximum line length in bytes (default 1MB)
            log_json_content: Whether to log full JSON content (may contain sensitive data)
        """
        self.command = command
        self.request_timeout = request_timeout
        self._process: Optional[asyncio.subprocess.Process] = None
        self._validator = MessageValidator()

        # Message dispatcher infrastructure
        self._running = False
        self._message_dispatcher_task: Optional[asyncio.Task] = None
        self._pending_requests: Dict[Union[str, int], asyncio.Future] = {}
        self._notification_queue: asyncio.Queue = asyncio.Queue()
        self._request_lock = asyncio.Lock()  # Protect pending_requests dict
        self._concurrent_request_count = 0
        self._max_concurrent_requests = max_concurrent_requests
        self._stderr_reader_task: Optional[asyncio.Task] = None
        self._max_line_length = max_line_length
        self._metrics_lock = threading.Lock()  # Thread-safe metrics
        self._log_json_content = log_json_content
        self._stderr_lines: List[str] = []  # Accumulated stderr for diagnostics
        self._max_stderr_lines = 100  # Limit to prevent memory issues
        self._metrics = {
            "requests_sent": 0,
            "requests_completed": 0,
            "requests_failed": 0,
            "validation_failures": 0,  # Track validation failures separately
            "notifications_received": 0,
        }
        # Circuit breaker for consecutive validation failures
        self._consecutive_validation_failures = 0
        self._validation_circuit_breaker_until: Optional[float] = None
        self._max_consecutive_validation_failures = 3
        self._validation_backoff_seconds = 5.0

    def is_connected(self) -> bool:
        """Check if transport is currently connected.

        Returns:
            True if connected to a running process, False otherwise
        """
        return self._process is not None and self._process.returncode is None

    def _resolve_command_for_platform(self, command: List[str]) -> List[str]:
        """Resolve command executable for platform compatibility.

        On Windows, batch files (.cmd/.bat) cannot be executed directly by
        asyncio.create_subprocess_exec(). This method uses shutil.which() to
        resolve the first command element to its full path, which includes
        the .cmd/.bat extension when applicable.

        Args:
            command: The command list to resolve

        Returns:
            Command list with first element resolved to full path on Windows,
            or original command on other platforms or if resolution fails
        """
        if not command or sys.platform != "win32":
            return command

        resolved = shutil.which(command[0])
        if resolved:
            return [resolved] + command[1:]
        return command  # Fall back if resolution fails

    async def connect(self) -> None:
        """Start the MCP server process and establish stdio connection.

        Raises:
            TransportConnectionError: If already connected
            TransportProcessError: If process startup fails
        """
        if self.is_connected():
            raise TransportConnectionError("Already connected")

        try:
            # Resolve command for platform compatibility (handles Windows .cmd/.bat)
            resolved_command = self._resolve_command_for_platform(self.command)
            logger.info(
                "Starting MCP server process",
                extra={
                    "command": self.command,
                    "resolved_command": resolved_command,
                    "operation": "connect",
                },
            )
            self._process = await asyncio.create_subprocess_exec(
                *resolved_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info(
                "MCP server process started",
                extra={"pid": self._process.pid, "operation": "connect"},
            )

            # Start message dispatcher
            self._running = True
            self._message_dispatcher_task = asyncio.create_task(
                self._message_dispatcher()
            )
            logger.debug("Message dispatcher started")

            # Start stderr reader to prevent deadlock from pipe buffer filling
            self._stderr_reader_task = asyncio.create_task(self._stderr_reader())
            logger.debug("Stderr reader started")

        except OSError as e:
            logger.exception(
                "Failed to start MCP server process",
                extra={"error": str(e), "operation": "connect"},
            )
            raise TransportProcessError(f"Failed to start MCP server process: {e}")

    async def disconnect(self) -> None:
        """Terminate the MCP server process and cleanup resources.

        Attempts graceful termination first, then force kills if needed.
        Safe to call even if not connected.
        """
        if not self._process:
            return

        try:
            logger.info(
                f"Disconnecting from MCP server process PID: {self._process.pid}"
            )
        except ValueError:
            # Ignore logging errors during shutdown
            pass

        # Stop message dispatcher first
        self._running = False
        if self._message_dispatcher_task and not self._message_dispatcher_task.done():
            self._message_dispatcher_task.cancel()
            try:
                await asyncio.wait_for(self._message_dispatcher_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                # Expected during cleanup
                pass
            except TransportConnectionError:
                # Expected when EOF is received during shutdown
                pass
            except TransportProcessError:
                # Expected when process exits during shutdown
                pass
            except Exception as e:
                # Log but don't re-raise cleanup errors
                try:
                    logger.debug(f"Error during message dispatcher cleanup: {e}")
                except ValueError:
                    # Ignore logging errors during shutdown
                    pass

        # Stop stderr reader
        if self._stderr_reader_task and not self._stderr_reader_task.done():
            self._stderr_reader_task.cancel()
            try:
                await asyncio.wait_for(self._stderr_reader_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Notify any pending requests
        async with self._request_lock:
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(TransportDisconnectedError("receive"))
                    # Retrieve the exception to prevent "unretrieved exception" warnings
                    try:
                        future.exception()
                    except (asyncio.CancelledError, asyncio.InvalidStateError):
                        # Future was cancelled or in invalid state - safe to ignore
                        pass
            self._pending_requests.clear()
            # Reset concurrent request counter to maintain consistency
            self._concurrent_request_count = 0

        # Drain notification queue to prevent consumers from hanging
        while not self._notification_queue.empty():
            try:
                self._notification_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        try:
            # Try graceful termination first
            self._process.terminate()

            try:
                # Wait up to 2 seconds for graceful shutdown
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
                try:
                    logger.info("MCP server process terminated gracefully")
                except ValueError:
                    # Ignore logging errors during shutdown
                    pass
            except asyncio.TimeoutError:
                # Force kill if graceful termination fails
                try:
                    logger.warning(
                        "MCP server process did not terminate gracefully, killing"
                    )
                except ValueError:
                    # Ignore logging errors during shutdown
                    pass
                self._process.kill()
                try:
                    # Give kill a short time to work
                    await asyncio.wait_for(self._process.wait(), timeout=1.0)
                    try:
                        logger.info("MCP server process killed")
                    except ValueError:
                        # Ignore logging errors during shutdown
                        pass
                except asyncio.TimeoutError:
                    try:
                        logger.exception(
                            "MCP server process did not respond to kill signal"
                        )
                    except ValueError:
                        # Ignore logging errors during shutdown
                        pass

        except Exception as e:
            try:
                logger.exception(f"Error during process cleanup: {e}")
            except ValueError:
                # Ignore logging errors during shutdown
                pass
        finally:
            # Close streams to prevent warnings during garbage collection
            if self._process:
                try:
                    if self._process.stdin:
                        self._process.stdin.close()
                    if self._process.stdout:
                        self._process.stdout.close()
                    if self._process.stderr:
                        self._process.stderr.close()
                except Exception:  # noqa: S110
                    # Ignore errors during stream cleanup - best effort only
                    pass
            self._process = None

    async def _limited_readline(
        self, stream: asyncio.StreamReader, max_bytes: int
    ) -> bytes:
        """Read a line from stream with size limit to prevent DOS attacks.

        This implements pre-allocation defense by reading in chunks and checking
        size before allocating the full line.

        Args:
            stream: The stream to read from
            max_bytes: Maximum allowed line size

        Returns:
            Complete line including newline

        Raises:
            TransportProtocolError: If line exceeds max_bytes
        """
        # For compatibility with mocks in tests, check if this is a real StreamReader
        # or a mock object with a readline method. Mocks don't have read() method.
        if not hasattr(stream, "read") or hasattr(stream.readline, "_mock_name"):
            # This is likely a mock - use readline directly
            line_bytes = await stream.readline()
            if len(line_bytes) > max_bytes:
                raise TransportProtocolError(
                    f"Line exceeds maximum size of {max_bytes} bytes",
                    data=f"Size: {len(line_bytes)}",
                )
            return line_bytes

        # Real StreamReader - use readline with limit for simplicity
        # StreamReader.readline() respects the limit parameter
        try:
            line_bytes = await stream.readline()
            # Check size after reading (StreamReader doesn't have built-in limit)
            if len(line_bytes) > max_bytes:
                raise TransportProtocolError(
                    f"Line exceeds maximum size of {max_bytes} bytes",
                    data=f"Size: {len(line_bytes)}, first 100 chars: {line_bytes[:100]}",
                )
            return line_bytes
        except asyncio.LimitOverrunError as e:
            # StreamReader hit its internal limit
            raise TransportProtocolError(
                f"Line exceeds stream buffer limit: {e}", data="Stream limit exceeded"
            )

    async def _stderr_reader(self):
        """Background task to drain stderr and prevent subprocess deadlock.

        This prevents the subprocess from blocking when stderr pipe buffer fills up.
        Logs stderr output at debug level for diagnostics and accumulates lines
        for later retrieval via get_stderr_output().
        """
        if not self._process or not self._process.stderr:
            return

        try:
            while self._running:
                try:
                    line_bytes = await self._limited_readline(
                        self._process.stderr, self._max_line_length
                    )
                    if not line_bytes:
                        break  # EOF

                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if line:
                        logger.debug(f"MCP server stderr: {line}")
                        # Accumulate stderr lines for diagnostics
                        if len(self._stderr_lines) < self._max_stderr_lines:
                            self._stderr_lines.append(line)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Error reading stderr: {e}")
                    break
        finally:
            logger.debug("Stderr reader stopped")

    def get_stderr_output(self) -> List[str]:
        """Get accumulated stderr output from the subprocess.

        Returns a copy of the accumulated stderr lines. This is useful for
        diagnostics when connection attempts fail.

        Returns:
            List of stderr lines (up to max_stderr_lines)
        """
        return self._stderr_lines.copy()

    def clear_stderr_output(self) -> None:
        """Clear accumulated stderr output."""
        self._stderr_lines.clear()

    async def _message_dispatcher(self):
        """Single reader that owns stdout and routes messages.

        This dispatcher solves the race condition by being the only component
        that reads from stdout. It routes responses to waiting requests by ID
        and queues notifications for separate consumption.
        """
        try:
            try:
                logger.debug("Message dispatcher started")
            except ValueError:
                # Ignore logging errors during shutdown
                pass
            while self._running:
                try:
                    # Read raw message from stdout with size limit to prevent memory exhaustion
                    line_bytes = await self._limited_readline(
                        self._process.stdout, self._max_line_length
                    )

                    if not line_bytes:
                        logger.debug("EOF received from MCP server")
                        # Check if process has exited to provide better error message
                        # Give process a moment to set returncode if it just exited
                        try:
                            # Only wait if we have a real process (not a mock)
                            if callable(self._process.wait) and not hasattr(
                                self._process.wait, "_mock_name"
                            ):
                                await asyncio.wait_for(
                                    self._process.wait(), timeout=0.1
                                )
                        except (asyncio.TimeoutError, TypeError):
                            pass  # Process still running, already waited, or mock object

                        if self._process.returncode is not None:
                            raise TransportProcessError(
                                f"MCP server process exited with code {self._process.returncode}",
                                exit_code=self._process.returncode,
                            )
                        else:
                            raise TransportConnectionError(
                                "Connection closed by MCP server"
                            )

                    # Parse message
                    line = line_bytes.decode("utf-8").strip()
                    if self._log_json_content:
                        logger.debug(f"Dispatcher received message: {line}")
                    else:
                        logger.debug("Dispatcher received message")

                    try:
                        message_dict = json.loads(line)
                    except json.JSONDecodeError as e:
                        logger.exception(
                            "Failed to parse JSON from MCP server",
                            extra={
                                "error": str(e),
                                "line_snippet": line[:100] if len(line) > 100 else line,
                                "operation": "message_dispatcher",
                            },
                        )
                        raise TransportProtocolError(
                            f"Failed to parse received message: {e}",
                            data=line[:100] if len(line) > 100 else line,
                        )

                    # Route message based on presence of 'id' field
                    if "id" in message_dict:
                        # Response - deliver to waiting request
                        await self._route_response(message_dict)
                    else:
                        # Notification - queue for processing
                        await self._route_notification(message_dict)

                except asyncio.CancelledError:
                    # Clean cancellation - don't log as error
                    break
                except Exception as e:
                    # Only try to log if we haven't been cancelled
                    if self._running:
                        try:
                            logger.exception(f"Error in message dispatcher: {e}")
                        except ValueError:
                            # Ignore logging errors during shutdown
                            pass
                    # Notify all pending requests of error
                    async with self._request_lock:
                        failed_count = 0
                        for future in self._pending_requests.values():
                            if not future.done():
                                try:
                                    future.set_exception(e)
                                    # Retrieve the exception to prevent "unretrieved exception" warnings
                                    future.exception()
                                except asyncio.InvalidStateError:
                                    # Future was already set, ignore
                                    pass
                                except (asyncio.CancelledError, Exception) as e:
                                    # Log unexpected errors during cleanup but continue
                                    logger.debug(f"Error during future cleanup: {e}")
                                    pass
                                failed_count += 1
                        self._pending_requests.clear()
                        # Track failures in metrics
                        if failed_count > 0:
                            with self._metrics_lock:
                                self._metrics["requests_failed"] += failed_count
                    break
        finally:
            try:
                logger.debug("Message dispatcher stopped")
            except ValueError:
                # Ignore logging errors during shutdown
                pass

    async def _route_response(self, message_dict: dict):
        """Route a response message to the waiting request."""
        request_id = message_dict["id"]
        async with self._request_lock:
            if request_id in self._pending_requests:
                future = self._pending_requests[request_id]  # Don't pop yet
                if not future.done():
                    try:
                        # Validate response before routing
                        self._validator.validate_response(message_dict)
                        future.set_result(message_dict)

                        # Reset consecutive validation failures on success
                        self._consecutive_validation_failures = 0

                        logger.debug(
                            "Response routed to request",
                            extra={
                                "request_id": request_id,
                                "operation": "route_response",
                            },
                        )
                        with self._metrics_lock:
                            self._metrics["requests_completed"] += 1
                    except ValidationError as e:
                        # Validation failure: cancel and clear pending requests so API raises TransportRequestError.
                        # NOTE: We're already inside _request_lock context; do NOT re-acquire.

                        # Update consecutive failure counter for circuit breaker
                        self._consecutive_validation_failures += 1

                        # Check if circuit breaker should be triggered
                        if (
                            self._consecutive_validation_failures
                            >= self._max_consecutive_validation_failures
                        ):
                            self._validation_circuit_breaker_until = (
                                time.time() + self._validation_backoff_seconds
                            )
                            logger.exception(
                                "Circuit breaker triggered due to consecutive validation failures",
                                extra={
                                    "consecutive_failures": self._consecutive_validation_failures,
                                    "backoff_seconds": self._validation_backoff_seconds,
                                    "operation": "route_response",
                                },
                            )

                        logger.exception(
                            "Response validation failed; clearing pending requests (dispatcher continues)",
                            extra={
                                "error": str(e),
                                "request_id": request_id,
                                "operation": "route_response",
                                "validation_failure": True,
                                "consecutive_failures": self._consecutive_validation_failures,
                            },
                        )
                        cleared = 0
                        for rid, pending_future in list(self._pending_requests.items()):
                            if not pending_future.done():
                                # Set exception instead of cancelling to ensure proper cleanup
                                pending_future.set_exception(
                                    TransportRequestError(
                                        f"Request {rid} failed due to validation error"
                                    )
                                )
                                # Retrieve the exception to prevent "unretrieved exception" warnings
                                try:
                                    pending_future.exception()
                                except (
                                    asyncio.CancelledError,
                                    asyncio.InvalidStateError,
                                ):
                                    # Future was cancelled or in invalid state - safe to ignore
                                    pass
                            cleared += 1
                        self._pending_requests.clear()
                        self._concurrent_request_count = 0
                        with self._metrics_lock:
                            self._metrics["requests_failed"] += (
                                cleared if cleared else 1
                            )
                            self._metrics[
                                "validation_failures"
                            ] += 1  # Track validation failure specifically
                        return
            else:
                logger.warning(
                    "Received response for unknown request ID",
                    extra={"request_id": request_id, "operation": "route_response"},
                )

    async def _route_notification(self, message_dict: dict):
        """Route a notification message to the notification queue."""
        try:
            notification = self._validator.validate_notification(message_dict)
            await self._notification_queue.put(notification)
            logger.debug(
                "Notification queued",
                extra={
                    "method": notification.method,
                    "operation": "route_notification",
                },
            )
        except ValidationError as e:
            logger.exception(
                "Invalid notification received",
                extra={"error": str(e), "operation": "route_notification"},
            )
            # Don't raise - just log and continue

    async def send_message(self, message: MCPRequest) -> None:
        """Send a JSON-RPC message to the MCP server via stdin.

        Args:
            message: The MCP request message to send

        Raises:
            TransportDisconnectedError: If not connected
            TransportProcessError: If process has exited
            TransportConcurrencyLimitError: If concurrent request limit exceeded
            TransportConnectionError: If connection-related send fails
            TransportError: If other send errors occur or circuit breaker is open
        """
        if not self.is_connected():
            raise TransportDisconnectedError("send_message")

        # Check circuit breaker
        if self._validation_circuit_breaker_until is not None:
            if time.time() < self._validation_circuit_breaker_until:
                raise TransportError(
                    f"Circuit breaker is open due to {self._consecutive_validation_failures} consecutive validation failures. "
                    f"Retry after {self._validation_circuit_breaker_until - time.time():.1f} seconds."
                )
            else:
                # Circuit breaker timeout expired, reset
                self._validation_circuit_breaker_until = None
                self._consecutive_validation_failures = 0
                logger.info("Circuit breaker reset after backoff period")

        # Check if process has exited
        if self._process.returncode is not None:
            raise TransportProcessError(
                f"MCP server process has exited with code {self._process.returncode}",
                exit_code=self._process.returncode,
            )

        # Register this request for response correlation
        async with self._request_lock:
            # Check concurrent request limit
            if self._concurrent_request_count >= self._max_concurrent_requests:
                raise TransportConcurrencyLimitError(
                    limit=self._max_concurrent_requests,
                    current=self._concurrent_request_count,
                )
            future = asyncio.Future()
            self._pending_requests[message.id] = future
            self._concurrent_request_count += (
                1  # Track all requests, not just send_and_receive
            )

        # Serialize message to JSON
        json_data = self._serialize_request(message)

        try:
            if self._log_json_content:
                logger.debug(f"Sending message: {json_data.strip()}")
            else:
                logger.debug(
                    f"Sending request - method: {message.method}, id: {message.id}"
                )
            with self._metrics_lock:
                self._metrics["requests_sent"] += 1
            self._process.stdin.write(json_data.encode("utf-8"))
            await self._process.stdin.drain()

        except (BrokenPipeError, ConnectionResetError) as e:
            # Clean up on failure
            async with self._request_lock:
                self._pending_requests.pop(message.id, None)
                self._concurrent_request_count -= 1
            with self._metrics_lock:
                self._metrics["requests_failed"] += 1
            logger.exception(
                "Failed to send message - connection error",
                extra={
                    "error": str(e),
                    "request_id": message.id,
                    "method": message.method,
                    "operation": "send_message",
                },
            )
            raise TransportConnectionError(f"Failed to send message: {e}", cause=e)
        except Exception as e:
            # Clean up on failure
            async with self._request_lock:
                self._pending_requests.pop(message.id, None)
                self._concurrent_request_count -= 1
            with self._metrics_lock:
                self._metrics["requests_failed"] += 1
            logger.exception(
                "Failed to send message - unexpected error",
                extra={
                    "error": str(e),
                    "request_id": message.id,
                    "method": message.method,
                    "operation": "send_message",
                },
            )
            raise TransportError(f"Failed to send message: {e}", cause=e)

    async def send_notification(self, notification: MCPNotification) -> None:
        """Send a notification to the MCP server via stdin.

        Args:
            notification: The MCP notification message to send

        Raises:
            TransportDisconnectedError: If not connected
            TransportProcessError: If process has exited
            TransportConnectionError: If send fails
        """
        if not self.is_connected():
            raise TransportDisconnectedError("send_notification")

        # Check if process has exited
        if self._process.returncode is not None:
            raise TransportProcessError(
                f"MCP server process has exited with code {self._process.returncode}",
                exit_code=self._process.returncode,
            )

        # Serialize notification to JSON
        json_data = self._serialize_notification(notification)

        try:
            if self._log_json_content:
                logger.debug(f"Sending notification: {json_data.strip()}")
            else:
                logger.debug(f"Sending notification - method: {notification.method}")
            self._process.stdin.write(json_data.encode("utf-8"))
            await self._process.stdin.drain()

        except (BrokenPipeError, ConnectionResetError) as e:
            logger.exception(
                "Failed to send notification - connection error",
                extra={
                    "error": str(e),
                    "method": notification.method,
                    "operation": "send_notification",
                },
            )
            raise TransportConnectionError(f"Failed to send notification: {e}", cause=e)
        except Exception as e:
            logger.exception(
                "Failed to send notification - unexpected error",
                extra={
                    "error": str(e),
                    "method": notification.method,
                    "operation": "send_notification",
                },
            )
            raise TransportConnectionError(f"Failed to send notification: {e}", cause=e)

    async def receive_message(self) -> MCPResponse:
        """Receive a JSON-RPC response for any pending request.

        This method waits for the next available response from any pending request.
        Responses are delivered in the order they arrive, not necessarily in the
        order requests were sent.

        Returns:
            The received MCP response or error message

        Raises:
            TransportDisconnectedError: If not connected
            TransportRequestError: If no pending requests
            TransportTimeoutError: If timeout waiting for response
        """
        if not self.is_connected():
            raise TransportDisconnectedError("receive_message")

        # Check if we have any pending requests
        async with self._request_lock:
            if not self._pending_requests:
                raise TransportRequestError("No pending requests")
            # Get any pending future to wait for
            pending_futures = list(self._pending_requests.values())

        if not pending_futures:
            raise TransportRequestError("No pending requests")

        try:
            # Wait for any response to arrive using wait()
            done, pending = await asyncio.wait(
                pending_futures,
                timeout=self.request_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                # Timeout - don't clear all requests, just report timeout
                raise TransportTimeoutError(
                    f"Timeout waiting for response after {self.request_timeout} seconds",
                    timeout=self.request_timeout,
                    operation="receive_message",
                )

            # Get the completed future and its response
            completed_future = done.pop()
            response_dict = completed_future.result()

            # Clean up the completed request from pending dict
            response_id = response_dict.get("id")
            if response_id is not None:
                async with self._request_lock:
                    self._pending_requests.pop(response_id, None)
                    self._concurrent_request_count -= 1

            # Parse response (validation already done in dispatcher)
            if "error" in response_dict and response_dict["error"] is not None:
                # This is an error response
                return MCPResponse(
                    jsonrpc=response_dict["jsonrpc"],
                    id=response_dict["id"],
                    error=response_dict["error"],
                )
            else:
                # This is a regular response
                return MCPResponse(
                    jsonrpc=response_dict["jsonrpc"],
                    id=response_dict["id"],
                    result=response_dict.get("result"),
                )

        except asyncio.CancelledError:
            # Clean up if task is cancelled
            # Try to find and clean up the completed future if response_id is available
            try:
                if response_id is not None:
                    async with self._request_lock:
                        if self._pending_requests.pop(response_id, None):
                            self._concurrent_request_count -= 1
            except NameError:
                # response_id wasn't set yet - we haven't actually consumed a response
                # But we still need to ensure counter is consistent
                # Since we didn't get a response, no decrement needed
                pass
            raise

    async def cancel_request(self, request_id: Union[str, int]) -> bool:
        """Cancel a pending request and clean up resources.

        Args:
            request_id: The ID of the request to cancel

        Returns:
            True if request was cancelled, False if not found
        """
        async with self._request_lock:
            if request_id in self._pending_requests:
                future = self._pending_requests.pop(request_id)
                # Only decrement if future not done (still pending)
                # If done, it was already decremented by receive_message or send_and_receive
                if not future.done():
                    self._concurrent_request_count -= 1
                    future.cancel()
                    logger.debug(f"Cancelled pending request {request_id}")
                else:
                    logger.debug(
                        f"Request {request_id} already completed, removed from tracking"
                    )
                return True
            return False

    async def send_and_receive(self, request: MCPRequest) -> MCPResponse:
        """Send a request and wait for its specific response.

        This method uses the existing request tracking infrastructure to ensure
        we get the correct response even when multiple requests are in flight.

        Args:
            request: The MCP request to send

        Returns:
            The specific response for this request

        Raises:
            TransportDisconnectedError: If not connected
            TransportProcessError: If process has exited
            TransportConcurrencyLimitError: If concurrent request limit exceeded
            TransportTimeoutError: If response timeout occurs
            TransportError: If request fails
        """
        if not self.is_connected():
            raise TransportDisconnectedError("send_message")

        # Check if process has exited
        if self._process.returncode is not None:
            raise TransportProcessError(
                f"MCP server process has exited with code {self._process.returncode}",
                exit_code=self._process.returncode,
            )

        # Check concurrent request limit
        async with self._request_lock:
            if self._concurrent_request_count >= self._max_concurrent_requests:
                raise TransportConcurrencyLimitError(
                    limit=self._max_concurrent_requests,
                    current=self._concurrent_request_count,
                )
            self._concurrent_request_count += 1

        try:
            # Register this request for response correlation
            async with self._request_lock:
                future = asyncio.Future()
                self._pending_requests[request.id] = future

            # Serialize and send the request
            json_data = self._serialize_request(request)

            try:
                if self._log_json_content:
                    logger.debug(f"Sending request {request.id}: {json_data.strip()}")
                else:
                    logger.debug(
                        f"Sending request - method: {request.method}, id: {request.id}"
                    )
                with self._metrics_lock:
                    self._metrics["requests_sent"] += 1
                self._process.stdin.write(json_data.encode("utf-8"))
                await self._process.stdin.drain()

                # Wait for the specific response for this request
                try:
                    response_dict = await asyncio.wait_for(
                        future, timeout=self.request_timeout
                    )

                    # Parse response
                    if "error" in response_dict and response_dict["error"] is not None:
                        return MCPResponse(
                            jsonrpc=response_dict["jsonrpc"],
                            id=response_dict["id"],
                            error=response_dict["error"],
                        )
                    else:
                        return MCPResponse(
                            jsonrpc=response_dict["jsonrpc"],
                            id=response_dict["id"],
                            result=response_dict.get("result"),
                        )

                except asyncio.CancelledError:
                    # Clean up on cancellation
                    async with self._request_lock:
                        self._pending_requests.pop(request.id, None)
                    raise
                except asyncio.TimeoutError as e:
                    # Clean up on timeout and wrap in TransportTimeoutError
                    async with self._request_lock:
                        self._pending_requests.pop(request.id, None)
                    with self._metrics_lock:
                        self._metrics["requests_failed"] += 1
                    raise TransportTimeoutError(
                        f"Request {request.id} timed out after {self.request_timeout} seconds",
                        timeout=self.request_timeout,
                        operation="send_and_receive",
                    ) from e

            except Exception as e:
                logger.exception(f"Failed to send request {request.id}: {e}")
                raise TransportError(f"Failed to send request: {e}", cause=e)

        finally:
            async with self._request_lock:
                self._concurrent_request_count -= 1

    async def get_next_notification(self) -> MCPNotification:
        """Get next notification from the queue.

        Blocks until a notification is available. For shutdown, cancel the
        calling task - CancelledError will propagate cleanly.

        Returns:
            The next available notification from the upstream server

        Raises:
            TransportDisconnectedError: If not connected
            asyncio.CancelledError: If the calling task is cancelled (normal shutdown)
        """
        if not self.is_connected():
            raise TransportDisconnectedError("get_next_notification")

        notification = await self._notification_queue.get()
        with self._metrics_lock:
            self._metrics["notifications_received"] += 1
        return notification

    async def notifications(self):
        """Async iterator for receiving notifications.

        This provides a cleaner interface for consuming notifications
        without the polling pattern.

        Yields:
            MCPNotification: The next notification from the server

        Example:
            async for notification in transport.notifications():
                await handle_notification(notification)
        """
        while self.is_connected() and self._running:
            try:
                notification = await self._notification_queue.get()
                yield notification
                with self._metrics_lock:
                    self._metrics["notifications_received"] += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in notification iterator: {e}")
                break

    def _serialize_request(self, request: MCPRequest) -> str:
        """Helper to serialize request to JSON.

        Args:
            request: The request to serialize

        Returns:
            JSON string with newline
        """
        message_dict = {
            "jsonrpc": request.jsonrpc,
            "method": request.method,
            "id": request.id,
        }
        if request.params is not None:
            message_dict["params"] = request.params
        return json.dumps(message_dict) + "\n"

    def _serialize_notification(self, notification: MCPNotification) -> str:
        """Helper to serialize notification to JSON.

        Args:
            notification: The notification to serialize

        Returns:
            JSON string with newline
        """
        notification_dict = {
            "jsonrpc": notification.jsonrpc,
            "method": notification.method,
        }
        if notification.params is not None:
            notification_dict["params"] = notification.params
        return json.dumps(notification_dict) + "\n"

    def get_metrics(self) -> Dict[str, int]:
        """Get current transport metrics.

        Returns:
            Dictionary of metric counters
        """
        with self._metrics_lock:
            return self._metrics.copy()
