"""Core proxy server implementation for Gatekit MCP gateway.

This module provides the MCPProxy class that serves as the central orchestrator
for the Gatekit proxy server, integrating with the plugin system and handling
MCP client-server communications through a 6-step request processing pipeline.
"""

import asyncio
import logging
import random
from typing import Dict, Any, Optional
from pathlib import Path

from gatekit.config.models import ProxyConfig
from gatekit.plugins.manager import PluginManager
from gatekit._version import __version__
from gatekit.plugins.interfaces import (
    ProcessingPipeline,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.protocol.errors import MCPErrorCodes, create_error_response
from gatekit.server_manager import ServerManager
from gatekit.core.routing import (
    RoutedRequest,
    parse_incoming_request,
    prepare_outgoing_response,
)
from gatekit.utils.namespacing import (
    namespace_tools_response,
    namespace_resources_response,
    namespace_prompts_response,
)
from .stdio_server import StdioServer

logger = logging.getLogger(__name__)

# Constants for version strings
PROTOCOL_VERSION = "2025-06-18"
GATEKIT_VERSION = __version__

# Metadata keys for enhanced observability
GATEKIT_METADATA_KEY = "_gatekit_metadata"


class MCPProxy:
    """Main proxy server that orchestrates plugins and transport.

    The MCPProxy implements a 6-step request processing pipeline:
    1. Security check through plugins
    2. Request logging
    3. Plugin decision handling
    4. Upstream forwarding (if allowed)
    5. Response filtering
    6. Response logging

    This implementation uses the YAML-based plugin configuration system.
    """

    def __init__(
        self,
        config: ProxyConfig,
        config_directory: Optional[Path] = None,
        plugin_manager=None,
        server_manager=None,
        stdio_server=None,
    ):
        """Initialize the proxy server.

        Args:
            config: Proxy configuration including upstream and transport settings
            config_directory: Directory containing the configuration file (for path resolution)
            plugin_manager: Optional plugin manager (for testing)
            server_manager: Optional server manager (for testing)
            stdio_server: Optional stdio server (for testing)

        Raises:
            NotImplementedError: If HTTP transport is specified (v0.1.0 limitation)
        """
        self.config = config
        self._is_running = False
        self._client_requests = 0
        self._concurrent_requests = 0
        self._max_concurrent_observed = 0

        # Request tracking for notification routing
        self._request_to_server: Dict[str, str] = {}

        # Initialize components (allow injection for testing)
        if config.transport == "http":
            raise NotImplementedError("HTTP transport not implemented in v0.1.0")

        # Initialize plugin manager with plugin configuration if provided
        plugin_config = config.plugins.to_dict() if config.plugins else {}
        self._plugin_manager = plugin_manager or PluginManager(
            plugin_config, config_directory
        )
        self._server_manager = server_manager or ServerManager(config.upstreams)
        self._stdio_server = stdio_server or StdioServer()

        logger.info(
            f"Initialized MCPProxy with {config.transport} transport for {len(config.upstreams)} upstream server(s)"
        )

    async def start(self) -> None:
        """Start the proxy server and initialize all components.

        This method:
        - Loads all configured plugins
        - Establishes connections to upstream MCP servers
        - Starts the stdio server for client connections
        - Sets the proxy as running

        Raises:
            RuntimeError: If proxy is already running or startup fails
        """
        if self._is_running:
            raise RuntimeError("Proxy is already running")

        try:
            logger.info("Starting MCPProxy server")

            # Initialize plugin system
            await self._plugin_manager.load_plugins()
            logger.info("Plugin manager initialized")

            # Connect to all upstream servers
            successful, failed = await self._server_manager.connect_all()

            if successful == 0:
                error_details = self._server_manager.get_connection_errors()
                error_msg = (
                    f"All upstream servers failed to connect: {error_details}"
                    if error_details
                    else "All upstream servers failed to connect"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            elif failed > 0:
                logger.warning(
                    f"Connected to {successful} servers, {failed} failed to connect"
                )
            else:
                logger.info(
                    f"Successfully connected to all {successful} upstream servers"
                )

            # Start stdio server for client connections
            await self._stdio_server.start()
            logger.info("Stdio server started for client connections")

            self._is_running = True
            logger.info("MCPProxy server started successfully")

        except Exception as e:
            logger.exception(f"Failed to start proxy server: {e}")
            # Cleanup on failure
            await self._cleanup()
            raise

    async def stop(self) -> None:
        """Stop the proxy server and cleanup resources.

        This method is safe to call multiple times and when the proxy
        is not running.
        """
        logger.info("Stopping MCPProxy server")
        await self._cleanup()
        self._is_running = False
        logger.info("MCPProxy server stopped")

    async def run(self) -> None:
        """Start the proxy server and begin accepting client connections.

        This method starts all components and then begins the main server loop
        that accepts and processes client connections via stdio. It will run
        until the server is stopped.

        Raises:
            RuntimeError: If proxy startup fails
        """
        await self.start()

        # Start notification listener task for upstream notifications
        notification_task = asyncio.create_task(
            self._listen_for_upstream_notifications()
        )

        try:
            logger.info("MCPProxy now accepting client connections")
            # Begin handling client messages through stdio server
            await self._stdio_server.handle_messages(
                self.handle_request, self.handle_notification
            )
        except Exception as e:
            logger.exception(f"Error in client connection handling: {e}")
            raise
        finally:
            # Cancel the notification listener task
            notification_task.cancel()
            try:
                await notification_task
            except asyncio.CancelledError:
                pass
            await self.stop()

    async def handle_request(self, request: MCPRequest) -> MCPResponse:
        """Handle an MCP request through the 6-step processing pipeline.

        Pipeline Steps:
        1. Security check through plugins
        2. Request logging
        3. Plugin decision handling
        4. Upstream forwarding (if allowed)
        5. Response filtering
        6. Response logging

        NOTE: MCP notification handling is not yet implemented. This will be
        added in a future release. The plugin interfaces support notifications
        but the proxy server currently only handles request/response flows.

        Args:
            request: The MCP request to process

        Returns:
            MCPResponse: The response from upstream server or error response

        Raises:
            RuntimeError: If proxy is not running
        """
        if not self._is_running:
            raise RuntimeError("Proxy is not running")

        self._client_requests += 1
        self._concurrent_requests += 1
        self._max_concurrent_observed = max(
            self._max_concurrent_observed, self._concurrent_requests
        )

        try:
            request_id = request.id

            logger.debug(f"Processing request {request_id}: {request.method}")

            # Handle initialize request specially to aggregate server capabilities
            if request.method == "initialize":
                return await self._handle_initialize(request)

            # Early validation of request
            if not request.method:
                logger.warning(f"Invalid request {request_id}: empty method")
                error_response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.INVALID_REQUEST,
                    message="Invalid request: empty method",
                )
                return error_response

            # Parse ONCE at ingress - create RoutedRequest
            routed = parse_incoming_request(request)

            # Check if parsing returned an error response
            if isinstance(routed, MCPResponse):
                logger.debug(f"Request {request_id} failed validation: {routed.error}")

                # Audit parse-time rejections for visibility
                try:
                    # Create synthetic pipeline for the rejection
                    rejected_pipeline = ProcessingPipeline(
                        original_content=request,
                        final_content=request,
                        pipeline_outcome=PipelineOutcome.BLOCKED,
                        blocked_at_stage="Invalid namespace format",
                        had_security_plugin=False,  # No plugins were run
                        capture_content=True,
                    )

                    # Log the rejected request (no target server since it couldn't be parsed)
                    await self._plugin_manager.log_request(
                        request, rejected_pipeline, None
                    )

                    # Log the error response
                    error_pipeline = ProcessingPipeline(
                        original_content=routed,
                        final_content=routed,
                        pipeline_outcome=PipelineOutcome.ERROR,
                        capture_content=False,
                    )
                    await self._plugin_manager.log_response(
                        request, routed, error_pipeline, None
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to audit parse-time rejection for request {request_id}: {e}"
                    )

                return routed

            # Track which server will handle this request (for notification routing)
            if request.id and routed.target_server:
                self._request_to_server[request.id] = routed.target_server
                logger.debug(
                    f"Tracking request {request.id} → server {routed.target_server}"
                )

            # Step 1: Run request through processing pipeline with clean request
            try:
                request_pipeline = await self._plugin_manager.process_request(
                    routed.request, routed.target_server
                )
            except Exception as e:
                logger.exception(
                    f"Plugin security check failed for request {request_id}: {e}"
                )
                error_response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.INTERNAL_ERROR,
                    message="Security check failed",
                )
                return error_response

            # Step 2: Handle request pipeline outcomes
            if (
                request_pipeline.pipeline_outcome
                == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
            ):
                # Middleware generated a full response - no upstream call
                completed = request_pipeline.final_content
                if not isinstance(completed, MCPResponse):
                    logger.error(
                        "Completed_by_middleware pipeline did not produce MCPResponse; returning internal error"
                    )
                    return create_error_response(
                        request_id=request_id,
                        code=MCPErrorCodes.INTERNAL_ERROR,
                        message="Middleware completion invalid",
                    )
                # Log request & synthetic response pipeline
                try:
                    await self._plugin_manager.log_request(
                        routed.request, request_pipeline, routed.target_server
                    )
                    # Create minimal response pipeline for auditing symmetry
                    response_pipeline = ProcessingPipeline(
                        original_content=completed,
                        final_content=completed,
                        pipeline_outcome=PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
                        capture_content=request_pipeline.capture_content,
                    )
                    await self._plugin_manager.log_response(
                        routed.request,
                        completed,
                        response_pipeline,
                        routed.target_server,
                    )
                except Exception as e:
                    logger.warning(
                        f"Auditing failed for completed request {request_id}: {e}"
                    )
                return completed

            # Log request pipeline (non-completed)
            try:
                await self._plugin_manager.log_request(
                    routed.request, request_pipeline, routed.target_server
                )
            except Exception as e:
                logger.warning(f"Request logging failed for request {request_id}: {e}")

            # Blocked request
            if request_pipeline.pipeline_outcome == PipelineOutcome.BLOCKED:
                reason = (
                    request_pipeline.blocked_at_stage or "blocked by security handler"
                )
                logger.info(f"Request {request_id} blocked at stage {reason}")
                error_response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.SECURITY_VIOLATION,
                    message=f"Request blocked: {reason}",
                )
                # Log synthetic response pipeline representing the block
                try:
                    blocked_pipeline = ProcessingPipeline(
                        original_content=error_response,
                        final_content=error_response,
                        pipeline_outcome=PipelineOutcome.BLOCKED,
                        capture_content=False,
                    )
                    await self._plugin_manager.log_response(
                        routed.request,
                        error_response,
                        blocked_pipeline,
                        routed.target_server,
                    )
                except Exception as e:
                    logger.warning(
                        f"Response logging failed for blocked request {request_id}: {e}"
                    )
                return error_response

            # Error in request pipeline (treat as internal error, fail closed)
            if request_pipeline.pipeline_outcome == PipelineOutcome.ERROR:
                logger.error(
                    f"Request {request_id} encountered plugin error; failing closed"
                )
                error_response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.INTERNAL_ERROR,
                    message="Request processing error",
                )
                try:
                    err_pipeline = ProcessingPipeline(
                        original_content=error_response,
                        final_content=error_response,
                        pipeline_outcome=PipelineOutcome.ERROR,
                        capture_content=False,
                    )
                    await self._plugin_manager.log_response(
                        routed.request,
                        error_response,
                        err_pipeline,
                        routed.target_server,
                    )
                except Exception as e:
                    logger.warning(
                        f"Error response logging failed for request {request_id}: {e}"
                    )
                return error_response

            # Update RoutedRequest if plugins modified the request
            if request_pipeline.final_content != routed.request:
                routed = routed.update_request(request_pipeline.final_content)

            # Validate target server exists AFTER plugin processing (not before)
            # Rationale for post-plugin validation:
            # 1. Allows auditing/logging of attempts to unknown servers
            # 2. Future: Enables routing plugins to redirect or create virtual servers
            # 3. Trade-off: Some plugin CPU spent on impossible routes, but maximizes flexibility
            # See docs/todos/routing-model-spec/current-sources-of-truth.md for details
            if routed.target_server and not self._is_broadcast_method(
                routed.request.method
            ):
                conn = self._server_manager.get_connection(routed.target_server)
                if not conn:
                    logger.warning(
                        f"Request {request_id} targets unknown server: {routed.target_server}"
                    )
                    error_response = create_error_response(
                        request_id=request_id,
                        code=MCPErrorCodes.INVALID_PARAMS,
                        message=f"Unknown server '{routed.target_server}' in request",
                    )
                    # Log the error response
                    try:
                        err_pipeline = ProcessingPipeline(
                            original_content=error_response,
                            final_content=error_response,
                            pipeline_outcome=PipelineOutcome.ERROR,
                            capture_content=False,
                        )
                        await self._plugin_manager.log_response(
                            routed.request,
                            error_response,
                            err_pipeline,
                            routed.target_server,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Error response logging failed for request {request_id}: {e}"
                        )
                    return error_response

            # Upstream forwarding: route using the complete RoutedRequest
            try:
                response = await self._route_request(routed)
                logger.debug(f"Received response for request {request_id}")

            except Exception as e:
                logger.exception(
                    f"Upstream communication failed for request {request_id}: {e}"
                )
                error_response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.UPSTREAM_UNAVAILABLE,
                    message=str(
                        e
                    ),  # Preserve original error message with server context
                )
                response = error_response
            # Step 5: Response filtering via pipeline
            try:
                response_pipeline = await self._plugin_manager.process_response(
                    routed.request, response, routed.target_server
                )
            except Exception as e:
                logger.exception(
                    f"Response filtering invocation failed for request {request_id}: {e}"
                )
                response_pipeline = ProcessingPipeline(
                    original_content=response,
                    final_content=response,
                    pipeline_outcome=PipelineOutcome.ERROR,
                    capture_content=False,
                )

            # Interpret response pipeline outcome
            if (
                response_pipeline.pipeline_outcome
                == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
            ):
                if isinstance(response_pipeline.final_content, MCPResponse):
                    response = response_pipeline.final_content
                    logger.debug(
                        f"Response for request {request_id} completed by middleware"
                    )
                else:
                    logger.error(
                        "Response pipeline marked completed but final_content not MCPResponse"
                    )
            elif response_pipeline.pipeline_outcome == PipelineOutcome.BLOCKED:
                logger.info(
                    f"Response for request {request_id} blocked by security plugin"
                )
                response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.SECURITY_VIOLATION,
                    message="Response blocked by security handler",
                )
            elif response_pipeline.pipeline_outcome == PipelineOutcome.ERROR:
                logger.error(
                    f"Response filtering error for request {request_id}; returning internal error"
                )
                response = create_error_response(
                    request_id=request_id,
                    code=MCPErrorCodes.INTERNAL_ERROR,
                    message="Response filtering failed",
                )
            else:
                # Normal allowed flow (possibly modified)
                if isinstance(response_pipeline.final_content, MCPResponse):
                    response = response_pipeline.final_content

            # Step 6: Log response pipeline
            try:
                await self._plugin_manager.log_response(
                    routed.request, response, response_pipeline, routed.target_server
                )
            except Exception as e:
                logger.warning(f"Response logging failed for request {request_id}: {e}")

            # Add metadata to all responses for consistency (if not already added by broadcast)
            if response.result is not None and isinstance(response.result, dict):
                if GATEKIT_METADATA_KEY not in response.result:
                    # Single-server response - add minimal metadata
                    response.result[GATEKIT_METADATA_KEY] = {
                        "partial": False,
                        "errors": [],
                        "successful_servers": (
                            [routed.target_server] if routed.target_server else []
                        ),
                        "total_servers": 1,
                        "failed_count": 0,
                    }

            # Apply namespace at egress using preserved context
            return prepare_outgoing_response(response, routed)

        except Exception as e:
            # Handle unexpected errors
            logger.exception(f"Unexpected error processing request {request_id}: {e}")

            # Validate request for better error handling
            if not request.method:
                error_code = MCPErrorCodes.INVALID_REQUEST
                error_message = "Invalid request: empty method"
            else:
                error_code = MCPErrorCodes.INTERNAL_ERROR
                error_message = f"Internal proxy error: {e}"

            error_response = create_error_response(
                request_id=request_id, code=error_code, message=error_message
            )

            return error_response
        finally:
            # Clean up completed request tracking
            if request_id:
                self._cleanup_completed_request(request_id)
            self._concurrent_requests -= 1

    async def handle_notification(self, notification: MCPNotification) -> None:
        """Handle an MCP notification with proper routing.

        Notifications are one-way messages that don't require a response.
        They are processed through plugins for auditing and then routed
        appropriately based on the notification type:

        - notifications/cancelled: Route to server that handled the original request
        - notifications/initialized: Broadcast to all servers
        - Other notifications: Route based on content or forward transparently

        Args:
            notification: The MCP notification to process

        Raises:
            RuntimeError: If proxy is not running
        """
        if not self._is_running:
            raise RuntimeError("Proxy is not running")

        logger.debug(f"Processing notification: {notification.method}")

        try:
            # Process notification through plugins (for auditing)
            # Note: Security plugins typically don't block notifications
            pipeline = await self._plugin_manager.process_notification(notification)

            # Log notification to auditing plugins (before outcome handling, like responses)
            await self._plugin_manager.log_notification(notification, pipeline)

            # Middleware completion
            if pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE:
                logger.debug(
                    f"Notification {notification.method} completed by middleware"
                )
                return

            if pipeline.pipeline_outcome == PipelineOutcome.BLOCKED:
                logger.info(
                    f"Notification {notification.method} blocked by security handler"
                )
                return
            if pipeline.pipeline_outcome == PipelineOutcome.ERROR:
                logger.error(
                    f"Notification {notification.method} encountered plugin error; dropping"
                )
                return

            # Forward (may be modified)
            final_notification = (
                pipeline.final_content
                if isinstance(pipeline.final_content, MCPNotification)
                else notification
            )
            await self._route_notification(final_notification)

        except Exception as e:
            logger.exception(f"Error processing notification {notification.method}: {e}")
            # Notifications don't get error responses, so we just log the error

    async def _listen_for_upstream_notifications(self) -> None:
        """Background task to listen for notifications from all upstream servers.

        This method creates listener tasks for all connected servers and forwards
        notifications to the client after processing through plugins.
        """
        logger.info("Starting upstream notification listeners")

        tasks = []
        for server_name, conn in self._server_manager.connections.items():
            if conn.status == "connected" and conn.transport:
                task = asyncio.create_task(
                    self._listen_server_notifications(server_name, conn)
                )
                tasks.append(task)

        if not tasks:
            logger.warning("No connected servers for notification listening")
            return

        try:
            # Wait for all tasks (they run until cancelled or connection lost)
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.exception(f"Error in notification listeners: {e}")
        finally:
            # Cancel any remaining tasks to prevent resource leaks
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        logger.info("All upstream notification listeners stopped")

    def _cleanup_completed_request(self, request_id: str) -> None:
        """Clean up tracking data for a completed request."""
        if request_id in self._request_to_server:
            server_name = self._request_to_server.pop(request_id)
            logger.debug(f"Cleaned up request tracking: {request_id} → {server_name}")

    async def _route_notification(self, notification: MCPNotification) -> None:
        """Route notification to appropriate server(s) based on type.

        Client→Server notifications:
        - notifications/cancelled: Route to server that handled the original request
        - notifications/initialized: Broadcast to all servers
        - Other client notifications: Forward to default server (original behavior)

        Server→Client notifications are handled by _listen_server_notifications
        and are forwarded transparently to the client.
        """
        if notification.method == "notifications/cancelled":
            await self._route_cancellation_notification(notification)
        elif notification.method == "notifications/initialized":
            await self._broadcast_notification_to_all_servers(notification)
        else:
            # Other client→server notifications: forward to default server (original behavior)
            await self._forward_notification_to_default_server(notification)

    async def _route_cancellation_notification(
        self, notification: MCPNotification
    ) -> None:
        """Route cancellation notification to the server that handled the original request."""
        if not notification.params:
            logger.warning("Cancellation notification missing params")
            return

        request_id = notification.params.get("requestId")
        if not request_id:
            logger.warning("Cancellation notification missing requestId")
            return

        target_server = self._request_to_server.get(request_id)
        if target_server:
            conn = self._server_manager.get_connection(target_server)
            if conn and conn.status == "connected":
                try:
                    await conn.transport.send_notification(notification)
                    logger.info(
                        f"Cancellation for request {request_id} routed to server {target_server}"
                    )
                except Exception as e:
                    logger.exception(
                        f"Failed to route cancellation to server {target_server}: {e}"
                    )
            else:
                logger.warning(
                    f"Cannot route cancellation for request {request_id}: server {target_server} not connected"
                )
        else:
            logger.warning(
                f"Cannot route cancellation for unknown request {request_id}"
            )

    async def _broadcast_notification_to_all_servers(
        self, notification: MCPNotification
    ) -> None:
        """Broadcast notification to all connected servers."""
        if not hasattr(self._server_manager, "connections"):
            logger.debug("No connections available for broadcast")
            return

        success_count = 0
        error_count = 0

        for server_name, conn in self._server_manager.connections.items():
            if conn.status == "connected":
                try:
                    await conn.transport.send_notification(notification)
                    success_count += 1
                    logger.debug(
                        f"Broadcast notification {notification.method} to server {server_name}"
                    )
                except Exception as e:
                    error_count += 1
                    logger.exception(
                        f"Failed to broadcast notification {notification.method} to server {server_name}: {e}"
                    )

        if success_count > 0:
            logger.info(
                f"Broadcast notification {notification.method} to {success_count} servers"
            )
        if error_count > 0:
            logger.warning(
                f"Failed to broadcast notification {notification.method} to {error_count} servers"
            )

    async def _forward_notification_to_default_server(
        self, notification: MCPNotification
    ) -> None:
        """Forward notification to default server (original behavior)."""
        try:
            logger.debug(
                f"Forwarding notification {notification.method} to upstream server"
            )
            # For notifications, send to default server (first available connection)
            connection = None
            if hasattr(self._server_manager, "connections"):
                for conn in self._server_manager.connections.values():
                    if conn.status == "connected":
                        connection = conn
                        break

            if connection:
                await connection.transport.send_notification(notification)
                logger.info(
                    f"Notification {notification.method} forwarded to upstream server"
                )
            else:
                logger.error(
                    f"No connected server available for notification {notification.method}"
                )
        except Exception as e:
            logger.exception(
                f"Failed to forward notification {notification.method} to upstream: {e}"
            )

    async def _listen_server_notifications(
        self, server_name: Optional[str], conn
    ) -> None:
        """Listen for notifications from a specific server."""
        server_display = server_name or "default"

        logger.info(f"Starting notification listener for server: {server_display}")

        # Exponential backoff parameters
        backoff_delay = 1.0  # Start with 1 second
        max_backoff = 60.0  # Cap at 60 seconds
        backoff_factor = 2.0  # Double each time
        consecutive_errors = 0
        max_consecutive_errors = 10

        try:
            while self._is_running and conn.status == "connected":
                try:
                    # Get notification from this server's transport
                    if hasattr(conn.transport, "get_server_to_client_notification"):
                        notification = (
                            await conn.transport.get_server_to_client_notification()
                        )
                    else:
                        notification = await conn.transport.get_next_notification()

                    # Reset backoff on successful receive
                    consecutive_errors = 0
                    backoff_delay = 1.0

                    logger.debug(
                        f"Received notification from {server_display}: {notification.method}"
                    )

                    # Notifications should maintain their original method names for MCP protocol compliance
                    # Unlike tools/resources/prompts, notifications don't need namespacing
                    modified_notification = notification

                    # Process notification through plugins
                    try:
                        pipeline = await self._plugin_manager.process_notification(
                            modified_notification, server_name
                        )

                        # Log notification to auditing plugins (before outcome handling, like responses)
                        await self._plugin_manager.log_notification(
                            modified_notification, pipeline, server_name
                        )

                        if (
                            pipeline.pipeline_outcome
                            == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
                        ):
                            logger.debug(
                                f"Server notification completed by middleware: {modified_notification.method}"
                            )
                            continue

                        if pipeline.pipeline_outcome == PipelineOutcome.BLOCKED:
                            logger.info(
                                f"Notification {modified_notification.method} from {server_display} blocked by handler"
                            )
                            continue
                        if pipeline.pipeline_outcome == PipelineOutcome.ERROR:
                            logger.error(
                                f"Notification {modified_notification.method} from {server_display} had plugin error; dropping"
                            )
                            continue

                        outgoing = (
                            pipeline.final_content
                            if isinstance(pipeline.final_content, MCPNotification)
                            else modified_notification
                        )
                        logger.debug(
                            f"Forwarding notification {outgoing.method} to client"
                        )
                        await self._stdio_server.write_notification(outgoing)

                    except Exception as e:
                        logger.exception(
                            f"Error processing notification {notification.method} from {server_display}: {e}"
                        )
                        # Don't forward notifications that can't be processed

                except asyncio.CancelledError:
                    # Normal shutdown - task was cancelled
                    logger.debug(
                        f"Notification listener for {server_display} cancelled (shutdown)"
                    )
                    break
                except Exception as e:
                    if "Not connected" in str(e) or "disconnected" in str(e).lower():
                        logger.info(
                            f"Connection to {server_display} closed, stopping notification listener"
                        )
                        break
                    else:
                        consecutive_errors += 1
                        logger.exception(
                            f"Error in notification listener for {server_display} (attempt {consecutive_errors}/{max_consecutive_errors}): {e}"
                        )

                        # Check if we've hit max errors
                        if consecutive_errors >= max_consecutive_errors:
                            logger.exception(
                                f"Max consecutive errors reached for {server_display}, stopping listener"
                            )
                            break

                        # Exponential backoff with jitter
                        jitter = random.uniform(-0.1, 0.1) * backoff_delay
                        sleep_time = min(backoff_delay + jitter, max_backoff)
                        logger.debug(
                            f"Backing off for {sleep_time:.1f} seconds before retry"
                        )
                        await asyncio.sleep(sleep_time)

                        # Increase backoff for next time
                        backoff_delay = min(backoff_delay * backoff_factor, max_backoff)

        except Exception as e:
            logger.exception(f"Notification listener error for {server_display}: {e}")
            conn.status = "disconnected"
        finally:
            logger.info(f"Notification listener for {server_display} stopped")

    async def _cleanup(self) -> None:
        """Internal cleanup method for stopping resources."""
        try:
            await self._stdio_server.stop()
        except Exception as e:
            logger.warning(f"Error stopping stdio server: {e}")

        try:
            await self._server_manager.disconnect_all()
        except Exception as e:
            logger.warning(f"Error disconnecting from upstream servers: {e}")

        try:
            await self._plugin_manager.cleanup()
        except Exception as e:
            logger.warning(f"Error cleaning up plugins: {e}")

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()

    @property
    def is_running(self) -> bool:
        """Check if the proxy server is currently running."""
        return self._is_running

    @property
    def client_requests(self) -> int:
        """Get the number of client requests processed."""
        return self._client_requests

    @property
    def plugin_config(self) -> Dict[str, Any]:
        """Get the current plugin configuration.

        Returns the plugin configuration from the loaded config.
        """
        return self.config.plugins.to_dict() if self.config.plugins else {}

    async def _handle_initialize(self, request: MCPRequest) -> MCPResponse:
        """Handle initialize request by broadcasting to all servers."""
        return await self._broadcast_request(request)

    async def _route_request(self, routed: RoutedRequest) -> MCPResponse:
        """Route based on RoutedRequest context."""
        # Special handling for broadcast methods (*/list)
        if self._is_broadcast_method(routed.request.method):
            return await self._broadcast_request(routed.request)

        # For everything else, route to specific server
        return await self._route_to_single_server(routed)

    def _is_broadcast_method(self, method: str) -> bool:
        """Check if this method should be broadcast to all servers."""
        return method in ["initialize", "tools/list", "resources/list", "prompts/list"]

    async def _broadcast_request(self, request: MCPRequest) -> MCPResponse:
        """Send request to all connected servers and aggregate results."""
        request_id = request.id

        # Handle mock server manager (for tests)
        if not hasattr(self._server_manager, "connections"):
            logger.debug(f"Using mock server manager fallback for {request.method}")
            # For tests without real connections dict, create a minimal broadcast simulation
            # This ensures namespacing behavior is consistent between real and test scenarios
            mock_response = await self._route_to_single_server(request)

            # If this is a list method, apply namespacing to match production behavior
            if (
                request.method in ["tools/list", "resources/list", "prompts/list"]
                and mock_response.result
            ):
                # Try to get server name from the mock connection
                if (
                    hasattr(self._server_manager, "connections")
                    and self._server_manager.connections
                ):
                    # Get first server name
                    server_name = next(iter(self._server_manager.connections.keys()))
                elif hasattr(self._server_manager, "get_connection"):
                    # Extract from first connection if available
                    conn = self._server_manager.get_connection(None)
                    if hasattr(conn, "name"):
                        server_name = conn.name
                    else:
                        server_name = "filesystem"  # Default for tests
                else:
                    server_name = "filesystem"  # Default for tests

                # Apply namespacing to match production behavior
                if request.method == "tools/list" and "tools" in mock_response.result:
                    tools = mock_response.result["tools"]
                    namespaced_tools = namespace_tools_response(server_name, tools)
                    logger.debug(
                        f"Namespacing tools for mock server {server_name}: {[t['name'] for t in namespaced_tools]}"
                    )
                    mock_response = MCPResponse(
                        jsonrpc=mock_response.jsonrpc,
                        id=mock_response.id,
                        result={**mock_response.result, "tools": namespaced_tools},
                        error=mock_response.error,
                        sender_context=mock_response.sender_context,
                    )
                elif (
                    request.method == "resources/list"
                    and "resources" in mock_response.result
                ):
                    resources = mock_response.result["resources"]
                    namespaced_resources = namespace_resources_response(
                        server_name, resources
                    )
                    mock_response = MCPResponse(
                        jsonrpc=mock_response.jsonrpc,
                        id=mock_response.id,
                        result={
                            **mock_response.result,
                            "resources": namespaced_resources,
                        },
                        error=mock_response.error,
                        sender_context=mock_response.sender_context,
                    )
                elif (
                    request.method == "prompts/list"
                    and "prompts" in mock_response.result
                ):
                    prompts = mock_response.result["prompts"]
                    namespaced_prompts = namespace_prompts_response(
                        server_name, prompts
                    )
                    mock_response = MCPResponse(
                        jsonrpc=mock_response.jsonrpc,
                        id=mock_response.id,
                        result={**mock_response.result, "prompts": namespaced_prompts},
                        error=mock_response.error,
                        sender_context=mock_response.sender_context,
                    )

            return mock_response

        # Broadcast to all servers and aggregate results

        # Prepare concurrent tasks for all servers (connected or not - reconnection will be attempted)
        tasks = []
        server_names = []

        for server_name, conn in self._server_manager.connections.items():
            # Add task for each server (reconnection will be attempted if needed)
            tasks.append(self._send_request_with_reconnect(request, server_name, conn))
            server_names.append(server_name)

        # Execute all requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        all_items = []
        errors = []
        successful_servers = []
        total_servers = len(server_names)

        for server_name, result in zip(server_names, results, strict=False):
            if isinstance(result, Exception):
                server_desc = self._server_manager.get_server_description(server_name)
                logger.warning(f"Failed to get response from {server_desc}: {result}")
                errors.append({"server": server_name, "error": str(result)})
            elif isinstance(result, MCPResponse):
                # Check if response has an error
                if result.error:
                    server_desc = self._server_manager.get_server_description(
                        server_name
                    )
                    logger.warning(
                        f"Server {server_desc} returned error: {result.error}"
                    )
                    errors.append({"server": server_name, "error": result.error})
                elif result.result:
                    successful_servers.append(server_name)
                    # Get the appropriate array from the response
                    if request.method == "tools/list":
                        items = result.result.get("tools", [])
                        items = namespace_tools_response(server_name, items)
                        logger.debug(
                            f"Namespaced tools for server {server_name}: {[t['name'] for t in items]}"
                        )
                    elif request.method == "resources/list":
                        items = result.result.get("resources", [])
                        items = namespace_resources_response(server_name, items)
                    elif request.method == "prompts/list":
                        items = result.result.get("prompts", [])
                        items = namespace_prompts_response(server_name, items)
                    else:
                        items = []

                    all_items.extend(items)

        # Handle initialize responses differently - merge capabilities
        if request.method == "initialize":
            # Process concurrent results for initialize
            first_response = None
            merged_capabilities = {
                "tools": {
                    "listChanged": True
                },  # Always True due to dynamic tool filtering
                "resources": {},
                "prompts": {},
            }

            for _server_name, result in zip(server_names, results, strict=False):
                if isinstance(result, MCPResponse) and result.result:
                    if first_response is None:
                        first_response = result.result

                    # Merge capabilities from this server
                    if "capabilities" in result.result:
                        server_caps = result.result["capabilities"]

                        # Merge capability flags using OR logic (if ANY server supports it)
                        if "tools" in server_caps:
                            # Always set listChanged to True since Gatekit security plugins
                            # can dynamically allow/block tools, changing the effective tool list
                            merged_capabilities["tools"]["listChanged"] = True

                        if "resources" in server_caps:
                            if "subscribe" in server_caps["resources"]:
                                merged_capabilities["resources"]["subscribe"] = (
                                    merged_capabilities["resources"].get(
                                        "subscribe", False
                                    )
                                    or server_caps["resources"]["subscribe"]
                                )
                            if "listChanged" in server_caps["resources"]:
                                merged_capabilities["resources"]["listChanged"] = (
                                    merged_capabilities["resources"].get(
                                        "listChanged", False
                                    )
                                    or server_caps["resources"]["listChanged"]
                                )

                        if "prompts" in server_caps:
                            if "listChanged" in server_caps["prompts"]:
                                merged_capabilities["prompts"]["listChanged"] = (
                                    merged_capabilities["prompts"].get(
                                        "listChanged", False
                                    )
                                    or server_caps["prompts"]["listChanged"]
                                )

            # Build result with metadata
            result_dict = {
                "protocolVersion": (
                    first_response.get("protocolVersion", PROTOCOL_VERSION)
                    if first_response
                    else PROTOCOL_VERSION
                ),
                "serverInfo": {"name": "gatekit", "version": GATEKIT_VERSION},
                "capabilities": merged_capabilities,
            }

            # Always include metadata for consistency
            result_dict[GATEKIT_METADATA_KEY] = {
                "partial": len(errors) > 0,
                "errors": errors,
                "successful_servers": successful_servers,
                "total_servers": total_servers,
                "failed_count": len(errors),
            }

            return MCPResponse(jsonrpc="2.0", id=request_id, result=result_dict)

        # Handle list methods - return array of items
        if request.method == "tools/list":
            result_key = "tools"
        elif request.method == "resources/list":
            result_key = "resources"
        elif request.method == "prompts/list":
            result_key = "prompts"
        else:
            result_key = "items"

        # Sort items for reproducibility (case-insensitive, with secondary sort on full name for stability)
        # Since names are already namespaced (e.g., "server1:tool1"), this naturally clusters by server
        all_items.sort(
            key=lambda x: (
                (x.get("name", "") if isinstance(x, dict) else str(x)).lower(),
                (
                    x.get("name", "") if isinstance(x, dict) else str(x)
                ),  # Secondary sort preserves original case order
            )
        )

        # Build result with metadata (always present for consistency)
        result_dict = {result_key: all_items}
        result_dict[GATEKIT_METADATA_KEY] = {
            "partial": len(errors) > 0,
            "errors": errors,
            "successful_servers": successful_servers,
            "total_servers": total_servers,
            "failed_count": len(errors),
        }

        return MCPResponse(jsonrpc="2.0", id=request_id, result=result_dict)

    async def _send_request_with_reconnect(
        self, request: MCPRequest, server_name: str, conn
    ) -> MCPResponse:
        """Send request to a server with reconnection attempt if needed."""
        from gatekit.server_manager import ServerConnection

        # Handle connection state
        if conn.status != "connected":
            # Try one reconnection attempt
            if hasattr(self._server_manager, "reconnect_server"):
                if not await self._server_manager.reconnect_server(server_name):
                    server_desc = self._server_manager.get_server_description(
                        server_name
                    )
                    raise Exception(
                        f"{server_desc.capitalize()} is unavailable: {conn.error or 'connection lost'}"
                    )

        # Send the request (with lock if available)
        try:
            if isinstance(conn, ServerConnection):
                async with conn.lock:
                    response = await conn.transport.send_and_receive(request)
            else:
                response = await conn.transport.send_and_receive(request)
            return response
        except Exception as e:
            # Mark connection as disconnected on failure
            if hasattr(conn, "status"):
                conn.status = "disconnected"
            if hasattr(conn, "error"):
                conn.error = str(e)
            raise

    async def _route_to_single_server(self, routed: RoutedRequest) -> MCPResponse:
        """Route to specific server using RoutedRequest.

        All non-broadcast requests MUST have a target server specified.
        There is no distinction between single and multi-server setups.
        """
        server_name = routed.target_server

        # This should never happen with proper validation at the boundary
        if server_name is None:
            raise ValueError(
                "Internal error: Non-namespaced request reached routing layer. "
                "All tool/resource/prompt calls must be namespaced with 'server__name' format."
            )

        # Get connection for target server
        conn = self._server_manager.get_connection(server_name)

        if not conn:
            server_desc = self._server_manager.get_server_description(server_name)
            raise Exception(f"Unknown {server_desc} in request")

        # Check if connection has real locking support (for race condition prevention)
        # Only use locking for actual ServerConnection instances, not mocks
        from gatekit.server_manager import ServerConnection

        if isinstance(conn, ServerConnection):
            # Use connection lock to ensure atomic connection checking and use
            async with conn.lock:
                return await self._route_request_internal(
                    conn, server_name, routed.request
                )
        else:
            # Fallback for mocked connections or connections without locking
            return await self._route_request_internal(conn, server_name, routed.request)

    async def _route_request_internal(
        self, conn, server_name: Optional[str], request: MCPRequest
    ) -> MCPResponse:
        """Internal request routing logic."""
        if conn.status != "connected":
            # Check if already reconnecting
            if hasattr(conn, "_reconnecting") and conn._reconnecting:
                # Wait for reconnection to complete
                while conn._reconnecting:
                    await asyncio.sleep(0.01)
                if conn.status != "connected":
                    server_desc = self._server_manager.get_server_description(
                        server_name
                    )
                    raise Exception(
                        f"{server_desc.capitalize()} is unavailable: {conn.error or 'connection lost'}"
                    )
            else:
                # Try one reconnection attempt
                if hasattr(self._server_manager, "_reconnect_server_internal"):
                    # Use internal method if available (when holding lock)
                    if not await self._server_manager._reconnect_server_internal(
                        server_name
                    ):
                        server_desc = self._server_manager.get_server_description(
                            server_name
                        )
                        raise Exception(
                            f"{server_desc.capitalize()} is unavailable: {conn.error or 'connection lost'}"
                        )
                else:
                    # Use regular reconnect method for mocked connections
                    if not await self._server_manager.reconnect_server(server_name):
                        server_desc = self._server_manager.get_server_description(
                            server_name
                        )
                        raise Exception(
                            f"{server_desc.capitalize()} is unavailable: {conn.error or 'connection lost'}"
                        )

        # At this point, we're guaranteed to have a connected transport
        # Forward the clean request from RoutedRequest
        try:
            # Send the clean request directly - it's already denamespaced
            response = await conn.transport.send_and_receive(request)
            return response

        except Exception as e:
            # Connection might have been lost during the request
            if hasattr(conn, "status"):
                conn.status = "disconnected"
            if hasattr(conn, "error"):
                conn.error = str(e)
            server_desc = self._server_manager.get_server_description(server_name)
            raise Exception(f"Request to {server_desc} failed: {e}")
