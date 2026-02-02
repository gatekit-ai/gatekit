"""Core proxy server implementation for Gatekit MCP gateway.

This module provides the MCPProxy class that serves as the central orchestrator
for the Gatekit proxy server, integrating with the plugin system and handling
MCP client-server communications through a 6-step request processing pipeline.
"""

import asyncio
import logging
import random
from typing import Dict, Any, List, Optional
from pathlib import Path

from gatekit.config.models import ProxyConfig, UpstreamConfig
from gatekit.config.loader import ConfigLoader
from gatekit.plugins.manager import PluginManager
from gatekit._version import __version__
from gatekit.plugins.interfaces import (
    ProcessingPipeline,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.protocol.errors import MCPErrorCodes, create_error_response
from gatekit.server_manager import ServerManager
from gatekit.transport.errors import HttpSessionExpired
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

    Class Attributes:
        HOT_RELOAD_SUPPORT: Known MCP clients and their hot-reload capability.
            Exact match only (no substring matching) to avoid misclassification.
            Unknown clients default to False (conservative).
    """

    # Known clients and their hot-reload support (exact matches only)
    # Conservative: unknown clients default to False
    HOT_RELOAD_SUPPORT: Dict[str, bool] = {
        # Confirmed working
        "github-copilot": True,
        # Confirmed broken/unsupported
        "claude-code": False,  # Claimed but broken per our testing
        "claude": False,  # Claude Desktop
        "claude-desktop": False,  # Possible variant
        "cursor": False,  # Confirmed in forum post
    }

    def __init__(
        self,
        config: ProxyConfig,
        config_directory: Optional[Path] = None,
        config_path: Optional[Path] = None,
        plugin_manager=None,
        server_manager=None,
        stdio_server=None,
    ):
        """Initialize the proxy server.

        Args:
            config: Proxy configuration including upstream and transport settings
            config_directory: Directory containing the configuration file (for path resolution)
            config_path: Path to configuration file (for hot-reload monitoring)
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

        # Client info and hot-reload capability tracking
        # Hot-reload is disabled by default until client capability is verified
        self._client_info: Optional[Dict[str, Any]] = None
        self._hot_reload_enabled: bool = False  # Conservative default

        # Hot-reload configuration tracking
        self._config_path: Optional[Path] = config_path
        self._config_directory: Optional[Path] = config_directory
        self._config_mtime: Optional[float] = None
        self._reload_lock = asyncio.Lock()

        # Generation-based plugin manager tracking (prevents cleanup during in-flight requests)
        self._plugin_manager_generation = 0
        self._active_requests_per_generation: Dict[int, int] = {0: 0}
        self._generation_lock = asyncio.Lock()

        # Notification listener task tracking (for dynamic server management)
        self._notification_tasks: Dict[str, asyncio.Task] = {}

        # Plugin cleanup task tracking (to cancel on shutdown)
        self._plugin_cleanup_tasks: List[asyncio.Task] = []

        # Initialize config mtime if config path exists
        if config_path and config_path.exists():
            try:
                self._config_mtime = config_path.stat().st_mtime
            except OSError:
                pass

        # Initialize components (allow injection for testing)
        if config.transport == "http":
            raise NotImplementedError("HTTP transport not implemented in v0.1.0")

        # Add ALL upstreams to ServerManager (including disabled ones)
        # This allows disabled servers to be enabled later via hot-reload
        # ServerManager.connect_all() will only connect enabled servers
        enabled_count = sum(1 for u in config.upstreams if u.enabled)
        disabled_count = len(config.upstreams) - enabled_count
        if disabled_count > 0:
            disabled_names = [u.name for u in config.upstreams if not u.enabled]
            logger.info(
                f"{disabled_count} upstream server(s) configured but disabled: {', '.join(disabled_names)}"
            )

        # Initialize plugin manager with plugin configuration if provided
        plugin_config = config.plugins.to_dict() if config.plugins else {}
        self._plugin_manager = plugin_manager or PluginManager(
            plugin_config, config_directory
        )
        self._server_manager = server_manager or ServerManager(
            config.upstreams,  # Pass ALL upstreams, not just enabled
            request_timeout=config.timeouts.request_timeout,
        )
        self._stdio_server = stdio_server or StdioServer()

        logger.info(
            f"Initialized MCPProxy with {config.transport} transport for {enabled_count} enabled upstream server(s)"
        )

    def _check_client_hot_reload_support(self, client_name: str) -> bool:
        """Check if client supports hot-reload notifications.

        Uses exact matching only (no substring matching) to avoid misclassification.
        Unknown clients default to False (conservative).

        Args:
            client_name: The client name from the MCP initialize request.

        Returns:
            True if the client is known to support hot-reload, False otherwise.
        """
        # Config override takes precedence
        if hasattr(self, "config") and self.config is not None:
            hot_reload_setting = getattr(self.config, "hot_reload", "auto")
            if hot_reload_setting == "enabled":
                return True
            if hot_reload_setting == "disabled":
                return False
            # "auto" falls through to client detection

        # Normalize client name for matching (exact match only)
        normalized = client_name.lower().replace(" ", "-").replace("_", "-")

        # Exact match only - no substring matching to avoid misclassification
        if normalized in self.HOT_RELOAD_SUPPORT:
            return self.HOT_RELOAD_SUPPORT[normalized]

        # Unknown client - default to disabled (conservative)
        logger.debug(
            f"Unknown client '{client_name}' (normalized: '{normalized}') - "
            "defaulting to hot-reload disabled"
        )
        return False

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

            # Check if there are any enabled servers configured
            enabled_count = sum(1 for u in self.config.upstreams if u.enabled)

            if successful == 0 and enabled_count > 0:
                # Enabled servers exist but none connected - this is a fatal error
                error_details = self._server_manager.get_connection_errors()
                error_msg = (
                    f"All upstream servers failed to connect: {error_details}"
                    if error_details
                    else "All upstream servers failed to connect"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            elif successful == 0 and enabled_count == 0:
                # All servers are disabled - this is OK, they can be enabled via hot-reload
                logger.info(
                    "No enabled servers at startup. Servers can be enabled via hot-reload."
                )
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

        # Step 0: Check for config changes (hot-reload)
        await self._check_and_reload_config()

        # Acquire generation token and capture plugin_manager reference
        # CRITICAL: Capture reference to ensure consistency throughout request
        generation = await self._acquire_generation()
        plugin_manager = self._plugin_manager

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
                    await plugin_manager.log_request(
                        request, rejected_pipeline, None
                    )

                    # Log the error response
                    error_pipeline = ProcessingPipeline(
                        original_content=routed,
                        final_content=routed,
                        pipeline_outcome=PipelineOutcome.ERROR,
                        capture_content=False,
                    )
                    await plugin_manager.log_response(
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
                request_pipeline = await plugin_manager.process_request(
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
                    await plugin_manager.log_request(
                        routed.request, request_pipeline, routed.target_server
                    )
                    # Create minimal response pipeline for auditing symmetry
                    response_pipeline = ProcessingPipeline(
                        original_content=completed,
                        final_content=completed,
                        pipeline_outcome=PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
                        capture_content=request_pipeline.capture_content,
                    )
                    await plugin_manager.log_response(
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
            # Skip for broadcast methods — per-server logging happens in _broadcast_request
            if not self._is_broadcast_method(routed.request.method):
                try:
                    await plugin_manager.log_request(
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
                    await plugin_manager.log_response(
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
                    await plugin_manager.log_response(
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
                        await plugin_manager.log_response(
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
                response_pipeline = await plugin_manager.process_response(
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
            # Skip for broadcast methods — per-server logging happens in _broadcast_request
            if not self._is_broadcast_method(routed.request.method):
                try:
                    await plugin_manager.log_response(
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
            # Release generation token
            await self._release_generation(generation)
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

        # Acquire generation token and capture plugin_manager reference
        generation = await self._acquire_generation()
        plugin_manager = self._plugin_manager

        try:
            # Determine target server for audit attribution
            # - notifications/cancelled: look up from request tracking
            # - notifications/initialized: broadcast (no single server)
            # - Other: unknown at this point
            notification_server_name = None
            if notification.method == "notifications/cancelled" and notification.params:
                request_id_for_cancel = notification.params.get("requestId")
                if request_id_for_cancel:
                    notification_server_name = self._request_to_server.get(
                        request_id_for_cancel
                    )

            # Process notification through plugins (for auditing)
            # Note: Security plugins typically don't block notifications
            pipeline = await plugin_manager.process_notification(notification)

            # Log notification to auditing plugins (before outcome handling, like responses)
            await plugin_manager.log_notification(
                notification, pipeline, notification_server_name
            )

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
        finally:
            await self._release_generation(generation)

    async def _listen_for_upstream_notifications(self) -> None:
        """Background task to manage notification listeners for all upstream servers.

        This method starts listener tasks for all connected servers using the
        _notification_tasks tracking dict. It runs for the lifetime of the proxy,
        periodically cleaning up finished tasks. New servers added via hot-reload
        will have their listeners started by _start_notification_listener().
        """
        logger.info("Starting upstream notification listeners")

        # Start initial listeners for all connected servers
        for server_name, conn in self._server_manager.connections.items():
            if conn.status == "connected" and conn.transport:
                self._start_notification_listener(server_name)

        if not self._notification_tasks:
            logger.warning("No connected servers for notification listening")
            # Don't return - stay running to pick up new servers via hot-reload

        try:
            # Keep running until proxy stops (listeners run independently)
            while self._is_running:
                # Clean up finished tasks
                finished = [
                    name
                    for name, task in self._notification_tasks.items()
                    if task.done()
                ]
                for name in finished:
                    self._notification_tasks.pop(name, None)
                await asyncio.sleep(1)  # Periodic cleanup
        except asyncio.CancelledError:
            pass
        finally:
            # Cancel all listeners on shutdown
            for task in self._notification_tasks.values():
                task.cancel()
            if self._notification_tasks:
                await asyncio.gather(
                    *self._notification_tasks.values(), return_exceptions=True
                )
            self._notification_tasks.clear()

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
        """Broadcast notification to all connected and enabled servers."""
        if not hasattr(self._server_manager, "connections"):
            logger.debug("No connections available for broadcast")
            return

        success_count = 0
        error_count = 0

        for server_name, conn in self._server_manager.connections.items():
            # Skip disabled servers - they should not receive notifications
            if hasattr(conn, "config") and not conn.config.enabled:
                continue
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
            # Check enabled status in loop condition - listener should stop if server is disabled
            # Use hasattr for defensive check against mock objects in tests
            while (
                self._is_running
                and conn.status == "connected"
                and (not hasattr(conn, "config") or conn.config.enabled)
            ):
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

                    # Process notification through plugins with generation tracking
                    generation = await self._acquire_generation()
                    plugin_manager = self._plugin_manager
                    try:
                        pipeline = await plugin_manager.process_notification(
                            modified_notification, server_name
                        )

                        # Log notification to auditing plugins (before outcome handling, like responses)
                        await plugin_manager.log_notification(
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
                    finally:
                        await self._release_generation(generation)

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
        # Stop all notification listeners first
        for _name, task in list(self._notification_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._notification_tasks.clear()

        # Cancel any pending plugin cleanup tasks
        for task in self._plugin_cleanup_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._plugin_cleanup_tasks.clear()

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

    # --- Generation-Based Plugin Manager Tracking ---

    async def _acquire_generation(self) -> int:
        """Acquire a generation token before processing a request.

        Returns the current generation number. The caller must call
        _release_generation with this number when done.
        """
        async with self._generation_lock:
            gen = self._plugin_manager_generation
            self._active_requests_per_generation[gen] = (
                self._active_requests_per_generation.get(gen, 0) + 1
            )
            return gen

    async def _release_generation(self, generation: int) -> None:
        """Release a generation token after processing a request."""
        async with self._generation_lock:
            count = self._active_requests_per_generation.get(generation, 0)
            if count > 1:
                self._active_requests_per_generation[generation] = count - 1
            else:
                self._active_requests_per_generation.pop(generation, None)

    # --- Hot-Reload Configuration Monitoring ---

    async def _check_and_reload_config(self) -> None:
        """Check for config changes and apply them.

        Called at the start of each request. Uses mtime polling for
        efficient cross-platform change detection.

        Skips entirely if the connected client doesn't support hot-reload
        (list_changed notifications). This is determined during initialize.
        """
        # Skip entirely if client doesn't support hot-reload
        # Default to False (disabled) - conservative until client capability verified
        if not getattr(self, "_hot_reload_enabled", False):
            return

        if not self._config_path or not self._config_path.exists():
            logger.debug("DEBUG hot-reload: No config path or file doesn't exist")
            return

        # Quick mtime check (no lock needed)
        try:
            current_mtime = self._config_path.stat().st_mtime
        except OSError:
            return

        if current_mtime == self._config_mtime:
            return

        logger.info(f"DEBUG hot-reload: mtime changed {self._config_mtime} -> {current_mtime}")

        # Double-check under lock (prevents concurrent reloads)
        async with self._reload_lock:
            try:
                current_mtime = self._config_path.stat().st_mtime
            except OSError:
                return

            if current_mtime == self._config_mtime:
                logger.info("DEBUG hot-reload: mtime unchanged after acquiring lock (concurrent reload)")
                return

            logger.info("DEBUG hot-reload: Applying config changes...")
            success = await self._apply_config_changes()
            logger.info(f"DEBUG hot-reload: Apply result: {success}")
            # Only update mtime if reload succeeded - this allows retry on next request
            if success:
                self._config_mtime = current_mtime

    async def _apply_config_changes(self) -> bool:
        """Load new config and apply server + plugin changes.

        TRANSACTIONAL: Only updates self.config after ALL changes succeed.
        If any step fails, the entire reload is aborted.

        Order: servers → plugins → timeouts
        This ensures plugin failures don't leave servers in an inconsistent state.

        Returns:
            True if reload succeeded, False if any step failed
        """
        try:
            loader = ConfigLoader()
            new_config = loader.load_from_file(self._config_path)
        except Exception as e:
            # Use error (not exception) - stack traces confuse users for config errors
            logger.error(f"Hot-reload failed: invalid config: {e}")  # noqa: TRY400
            return False

        # Reject transport changes
        if new_config.transport != self.config.transport:
            logger.warning("Hot-reload: transport changes require restart")
            return False

        # === PRE-FLIGHT CHECKS (before making any changes) ===
        old_plugins = self.config.plugins.to_dict() if self.config.plugins else {}
        new_plugins = new_config.plugins.to_dict() if new_config.plugins else {}

        # Check for CSV format-breaking changes
        if self._is_csv_format_breaking_change(old_plugins, new_plugins):
            logger.error(
                "Hot-reload rejected: CSV format options changed without changing output_file. "
                "This would corrupt the log file. Change output_file or restart the gateway."
            )
            return False  # Abort entire reload

        # === SERVER HOT-RELOAD (do first - less likely to have cascading failures) ===
        old_servers = {u.name: u for u in self.config.upstreams}
        new_servers = {u.name: u for u in new_config.upstreams}

        added = set(new_servers) - set(old_servers)
        removed = set(old_servers) - set(new_servers)
        potentially_modified = set(old_servers) & set(new_servers)

        logger.info(f"DEBUG servers: added={added}, removed={removed}, potentially_modified={potentially_modified}")
        for name in potentially_modified:
            old, new = old_servers[name], new_servers[name]
            logger.info(f"DEBUG server '{name}': enabled {old.enabled} -> {new.enabled}")

        try:
            for name in removed:
                await self._remove_server(name)
                logger.info(f"Hot-reload: Removed server '{name}'")

            for name in potentially_modified:
                old, new = old_servers[name], new_servers[name]
                await self._update_server(old, new)

            for name in added:
                config = new_servers[name]
                # Add ALL servers to connections (enabled or not)
                # This ensures disabled servers can be enabled later via hot-reload
                await self._add_server(config)
                if config.enabled:
                    logger.info(f"Hot-reload: Added and connected server '{name}'")
                else:
                    logger.info(f"Hot-reload: Added server '{name}' (disabled)")
        except Exception as e:
            # Use error (not exception) - stack traces confuse users for config errors
            logger.error(f"Hot-reload failed: server update error: {e}")  # noqa: TRY400
            # Server changes may be partial, but plugins are untouched.
            return False

        # === PLUGIN HOT-RELOAD (do after servers - most likely to fail) ===
        plugins_changed = new_config.plugins != self.config.plugins
        if plugins_changed:
            try:
                # Log what's changing
                self._log_plugin_config_changes(old_plugins, new_plugins)
                await self._reload_plugins(new_config)
                logger.info("Hot-reload: Plugin configuration reloaded")
            except Exception as e:
                # Use error (not exception) - stack traces confuse users for config errors
                logger.error(f"Hot-reload failed: plugin reload error: {e}")  # noqa: TRY400
                # Note: Server changes already applied. This leaves servers updated but
                # plugins old. Since server changes are typically additive/safe and plugin
                # changes are policy changes, this ordering minimizes security impact.
                return False

        # === TIMEOUT HOT-RELOAD ===
        # Note: This updates the default for NEW connections only. Existing transports
        # keep their original timeout until they reconnect. This is by design - it avoids
        # complex transport API changes and ensures in-flight requests use consistent timeouts.
        if new_config.timeouts != self.config.timeouts:
            self._server_manager._request_timeout = new_config.timeouts.request_timeout
            logger.info("Hot-reload: Timeout configuration updated (applies to new connections)")

        # === ALL CHANGES SUCCEEDED - Update config reference ===
        self.config = new_config

        # Send capability change notifications to client
        await self._notify_capability_changes()

        return True

    async def _reload_plugins(self, new_config: ProxyConfig) -> None:
        """Reload plugins with generation-based safe swap."""
        # Create new plugin manager
        plugin_config = new_config.plugins.to_dict() if new_config.plugins else {}
        new_plugin_manager = PluginManager(plugin_config, self._config_directory)
        await new_plugin_manager.load_plugins()

        # Atomic swap under lock
        async with self._generation_lock:
            old_plugin_manager = self._plugin_manager
            old_generation = self._plugin_manager_generation

            self._plugin_manager = new_plugin_manager
            self._plugin_manager_generation += 1
            self._active_requests_per_generation[self._plugin_manager_generation] = 0

        # Schedule background cleanup of old plugin manager (track for shutdown cancellation)
        cleanup_task = asyncio.create_task(
            self._cleanup_old_plugin_manager(old_plugin_manager, old_generation)
        )
        self._plugin_cleanup_tasks.append(cleanup_task)
        # Clean up completed tasks from the list to prevent unbounded growth
        self._plugin_cleanup_tasks = [t for t in self._plugin_cleanup_tasks if not t.done()]

    async def _cleanup_old_plugin_manager(
        self, old_manager: PluginManager, generation: int
    ) -> None:
        """Wait for all requests using old generation to complete, then cleanup.

        Has timeouts to prevent hanging forever if requests are stuck.
        """
        max_wait_time = 60.0  # 60 seconds max wait for in-flight requests
        wait_time = 0.0
        poll_interval = 0.05  # 50ms

        while wait_time < max_wait_time:
            async with self._generation_lock:
                count = self._active_requests_per_generation.get(generation, 0)
                if count == 0:
                    self._active_requests_per_generation.pop(generation, None)
                    break
            await asyncio.sleep(poll_interval)
            wait_time += poll_interval
        else:
            # Timeout reached - force cleanup anyway
            logger.warning(
                f"Timeout waiting for generation {generation} requests to complete. "
                f"Forcing cleanup with {count} request(s) still in flight."
            )
            async with self._generation_lock:
                self._active_requests_per_generation.pop(generation, None)

        try:
            # Timeout on cleanup() call to prevent hanging on stuck plugins
            await asyncio.wait_for(old_manager.cleanup(), timeout=30.0)
            logger.debug(f"Cleaned up old plugin manager (generation {generation})")
        except asyncio.TimeoutError:
            # Timeout errors don't need stack traces - the timeout is self-explanatory
            logger.error(  # noqa: TRY400
                f"Timeout cleaning up old plugin manager (generation {generation}). "
                "Some plugin resources may not have been released."
            )
        except Exception as e:
            # Cleanup errors are logged but don't need full stack traces
            logger.error(f"Error cleaning up old plugin manager: {e}")  # noqa: TRY400

    def _is_csv_format_breaking_change(
        self, old_config: dict, new_config: dict
    ) -> bool:
        """Check if CSV auditing format changed without output_file change."""
        old_csv = self._get_csv_plugin_config(old_config)
        new_csv = self._get_csv_plugin_config(new_config)

        if not old_csv or not new_csv:
            return False  # No CSV plugin configured

        # Same output file?
        if old_csv.get("output_file") != new_csv.get("output_file"):
            return False  # Different files - no corruption risk

        # Check format options
        old_fmt = old_csv.get("csv_config", {})
        new_fmt = new_csv.get("csv_config", {})

        format_fields = ["delimiter", "quote_char", "quote_style", "escape_char"]
        for field in format_fields:
            if old_fmt.get(field) != new_fmt.get(field):
                return True  # Format changed with same file

        return False

    def _get_csv_plugin_config(self, plugins_config: dict) -> Optional[dict]:
        """Extract CSV auditing plugin config from plugins dict."""
        auditing = plugins_config.get("auditing", {})
        for _scope, plugins in auditing.items():
            if isinstance(plugins, list):
                for plugin in plugins:
                    if plugin.get("handler") == "csv_audit":
                        return plugin.get("config", {})
        return None

    def _log_plugin_config_changes(
        self, old_plugins: dict, new_plugins: dict
    ) -> None:
        """Log all plugin configuration changes."""
        # Get all plugin names from both configs
        old_names = self._get_plugin_names(old_plugins)
        new_names = self._get_plugin_names(new_plugins)

        # Log added plugins
        for name in new_names - old_names:
            logger.info(f"Hot-reload: Plugin '{name}' added")

        # Log removed plugins
        for name in old_names - new_names:
            logger.info(f"Hot-reload: Plugin '{name}' removed")

        # Log modified plugins - only if config actually changed
        for name in old_names & new_names:
            old_cfg = self._get_plugin_config_by_name(old_plugins, name)
            new_cfg = self._get_plugin_config_by_name(new_plugins, name)
            if old_cfg != new_cfg:
                logger.info(f"Hot-reload: Plugin '{name}' configuration changed")

    def _get_plugin_config_by_name(self, plugins_config: dict, handler_name: str) -> Optional[dict]:
        """Extract plugin config for a specific handler name."""
        for category in ["middleware", "security", "auditing"]:
            category_config = plugins_config.get(category, {})
            for _scope, plugins in category_config.items():
                if isinstance(plugins, list):
                    for plugin in plugins:
                        if plugin.get("handler") == handler_name:
                            return plugin.get("config", {})
        return None

    def _get_plugin_names(self, plugins_config: dict) -> set:
        """Extract set of plugin handler names from config dict."""
        names = set()
        for category in ["middleware", "security", "auditing"]:
            category_config = plugins_config.get(category, {})
            for _scope, plugins in category_config.items():
                if isinstance(plugins, list):
                    for plugin in plugins:
                        if handler := plugin.get("handler"):
                            names.add(handler)
        return names

    # --- Server Hot-Reload Helpers ---

    async def _add_server(self, config: UpstreamConfig) -> None:
        """Add a new server and start its notification listener if enabled."""
        success = await self._server_manager.add_server(config)
        # Only start notification listener if server is enabled and connected
        if success and config.enabled:
            self._start_notification_listener(config.name)

    async def _remove_server(self, name: str) -> None:
        """Stop notification listener and remove server."""
        await self._stop_notification_listener(name)
        await self._server_manager.remove_server(name)

    async def _update_server(self, old: UpstreamConfig, new: UpstreamConfig) -> None:
        """Handle server config updates.

        Handles four cases:
        1. enabled -> disabled: disconnect, keep in connections
        2. disabled -> enabled (no reconnect needed): just connect
        3. disabled -> enabled (reconnect needed): update_server handles remove+add+connect
        4. enabled -> enabled (reconnect needed): update_server handles remove+add+connect
        """
        needs_reconnect = self._server_manager._needs_reconnect(old, new)

        if old.enabled and not new.enabled:
            # Case 1: Disabled - disconnect but keep in manager
            await self._stop_notification_listener(old.name)
            # Update config first (so enabled=False is stored)
            await self._server_manager.update_server(new)
            await self._server_manager.disconnect_server(old.name)
            logger.info(f"Hot-reload: Disabled server '{old.name}'")

        elif not old.enabled and new.enabled:
            # Case 2/3: Enabling a previously disabled server
            await self._stop_notification_listener(old.name)  # Safety: stop if somehow running

            if needs_reconnect:
                # Case 3: Connection settings changed - update_server does remove+add+connect
                await self._server_manager.update_server(new)
                # update_server with reconnect does add_server which connects if enabled
                # So we just need to start the listener if connected
            else:
                # Case 2: No reconnect needed - just update config and connect
                await self._server_manager.update_server(new)
                await self._server_manager.connect_server(old.name)

            conn = self._server_manager.get_connection(old.name)
            if conn and conn.status == "connected":
                self._start_notification_listener(old.name)
                logger.info(f"Hot-reload: Enabled server '{old.name}'")
            else:
                logger.warning(f"Hot-reload: Failed to enable server '{old.name}'")

        elif old.enabled and new.enabled:
            # Case 4: Both enabled - check for reconnect-worthy changes
            if needs_reconnect:
                await self._stop_notification_listener(old.name)
                # update_server handles remove+add+connect when needs_reconnect
                await self._server_manager.update_server(new)
                conn = self._server_manager.get_connection(old.name)
                if conn and conn.status == "connected":
                    self._start_notification_listener(old.name)
                    logger.info(f"Hot-reload: Reconnected server '{old.name}'")
                else:
                    logger.warning(
                        f"Hot-reload: Server '{old.name}' reconnect failed, "
                        "notification listener not started"
                    )
            else:
                # No reconnect needed - just update config
                await self._server_manager.update_server(new)

        else:
            # disabled -> disabled: just update config
            await self._server_manager.update_server(new)

    def _start_notification_listener(self, name: str) -> None:
        """Start notification listener task for a server."""
        # Guard against double-starting
        if name in self._notification_tasks and not self._notification_tasks[name].done():
            return  # Already running

        conn = self._server_manager.get_connection(name)
        if conn and conn.status == "connected" and conn.transport:
            task = asyncio.create_task(self._listen_server_notifications(name, conn))
            self._notification_tasks[name] = task

    async def _stop_notification_listener(self, name: str) -> None:
        """Stop notification listener task for a server."""
        task = self._notification_tasks.pop(name, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _notify_capability_changes(self) -> None:
        """Notify client that capabilities may have changed."""
        # Skip if client doesn't support hot-reload (list_changed notifications)
        # Default to False (disabled) - conservative until client capability verified
        if not getattr(self, "_hot_reload_enabled", False):
            logger.debug("Skipping list_changed notifications (client doesn't support)")
            return

        # Only applicable for stdio transport (HTTP doesn't have persistent notification channel)
        if not hasattr(self, "_stdio_server") or self._stdio_server is None:
            logger.info("DEBUG notify: No stdio_server, skipping notifications")
            return

        logger.info("DEBUG notify: Sending list_changed notifications to client...")

        # MCP spec: send list_changed notifications
        # Include explicit empty params - some clients may expect this
        notifications = [
            MCPNotification(jsonrpc="2.0", method="notifications/tools/list_changed", params={}),
            MCPNotification(jsonrpc="2.0", method="notifications/resources/list_changed", params={}),
            MCPNotification(jsonrpc="2.0", method="notifications/prompts/list_changed", params={}),
        ]
        for notif in notifications:
            try:
                await self._stdio_server.write_notification(notif)
                logger.info(f"DEBUG notify: Sent {notif.method}")
            except Exception as e:
                logger.warning(f"DEBUG notify: Failed to send {notif.method}: {e}")

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
        """Handle initialize request by broadcasting to all servers.

        Also captures client info and determines hot-reload capability based on
        the client's support for list_changed notifications.
        """
        # Capture client info and determine hot-reload capability
        if request.params:
            self._client_info = request.params.get("clientInfo", {})
            client_name = self._client_info.get("name", "unknown")
            client_version = self._client_info.get("version", "unknown")
            logger.info(f"MCP client connected: {client_name} v{client_version}")

            # Determine hot-reload capability based on client support
            self._hot_reload_enabled = self._check_client_hot_reload_support(
                client_name
            )
            if self._hot_reload_enabled:
                logger.info(f"Hot-reload enabled for client '{client_name}'")
            else:
                logger.info(
                    f"Hot-reload disabled for client '{client_name}' - "
                    "config changes require restart"
                )

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
            # Wrap in RoutedRequest for type compatibility
            routed = RoutedRequest(request=request, target_server=None)
            mock_response = await self._route_to_single_server(routed)

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

        # Prepare concurrent tasks for all ENABLED servers only
        tasks = []
        server_names = []

        for server_name, conn in self._server_manager.connections.items():
            # Skip disabled servers - they should not participate in broadcasts
            if not conn.config.enabled:
                continue
            # Add task for each enabled server (reconnection will be attempted if needed)
            tasks.append(self._send_request_with_reconnect(request, server_name, conn))
            server_names.append(server_name)

        # Execute all requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        all_items = []
        errors = []
        successful_servers = []
        total_servers = len(server_names)

        # Use current plugin manager for per-server audit logging
        # (caller _process_client_request already holds the generation token)
        plugin_manager = self._plugin_manager

        for server_name, result in zip(server_names, results, strict=False):
            if isinstance(result, Exception):
                server_desc = self._server_manager.get_server_description(server_name)
                logger.warning(f"Failed to get response from {server_desc}: {result}")
                errors.append({"server": server_name, "error": str(result)})
            elif isinstance(result, MCPResponse):
                # Log per-server request and response for auditing (e.g. token counting)
                try:
                    req_pipeline = ProcessingPipeline(
                        original_content=request,
                        final_content=request,
                        pipeline_outcome=PipelineOutcome.ALLOWED,
                        capture_content=False,
                    )
                    await plugin_manager.log_request(
                        request, req_pipeline, server_name
                    )
                    resp_pipeline = ProcessingPipeline(
                        original_content=result,
                        final_content=result,
                        pipeline_outcome=(
                            PipelineOutcome.ERROR if result.error
                            else PipelineOutcome.ALLOWED
                        ),
                        capture_content=False,
                    )
                    await plugin_manager.log_response(
                        request, result, resp_pipeline, server_name
                    )
                except Exception as e:
                    logger.warning(
                        f"Auditing failed for broadcast to {server_name}: {e}"
                    )

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

        # Check if server is disabled - don't reconnect disabled servers
        if hasattr(conn, "config") and not conn.config.enabled:
            server_desc = self._server_manager.get_server_description(server_name)
            raise Exception(f"{server_desc.capitalize()} is disabled")

        # Handle connection state
        if conn.status != "connected":
            # Try one reconnection attempt (will be refused if disabled)
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
        except HttpSessionExpired:
            # HTTP session expired - reconnect and retry once
            server_desc = self._server_manager.get_server_description(server_name)
            logger.info(f"Session expired for {server_desc}, reconnecting and retrying")

            # Mark connection as disconnected
            if hasattr(conn, "status"):
                conn.status = "disconnected"

            # Attempt reconnection
            if hasattr(self._server_manager, "reconnect_server"):
                reconnected = await self._server_manager.reconnect_server(server_name)
            else:
                reconnected = False

            if not reconnected:
                raise Exception(
                    f"Request to {server_desc} failed: session expired and reconnection failed"
                )

            # Retry the request after successful reconnection
            logger.debug(f"Retrying request to {server_desc} after session recovery")
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
        # Check if server is disabled - don't route to disabled servers
        if hasattr(conn, "config") and not conn.config.enabled:
            server_desc = self._server_manager.get_server_description(server_name)
            raise Exception(f"{server_desc.capitalize()} is disabled")

        if conn.status != "connected":
            # Check if already reconnecting
            if hasattr(conn, "_reconnecting") and conn._reconnecting:
                # Wait for reconnection to complete (with timeout to prevent deadlock)
                max_wait = 30.0  # 30 seconds max wait
                wait_time = 0.0
                while conn._reconnecting and wait_time < max_wait:
                    await asyncio.sleep(0.01)
                    wait_time += 0.01
                if wait_time >= max_wait:
                    server_desc = self._server_manager.get_server_description(
                        server_name
                    )
                    raise Exception(
                        f"{server_desc.capitalize()} reconnection timed out"
                    )
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

        except HttpSessionExpired:
            # HTTP session expired - reconnect and retry once
            server_desc = self._server_manager.get_server_description(server_name)
            logger.info(f"Session expired for {server_desc}, reconnecting and retrying")

            # Mark connection as disconnected
            if hasattr(conn, "status"):
                conn.status = "disconnected"

            # Attempt reconnection
            if hasattr(self._server_manager, "_reconnect_server_internal"):
                reconnected = await self._server_manager._reconnect_server_internal(
                    server_name
                )
            else:
                reconnected = await self._server_manager.reconnect_server(server_name)

            if not reconnected:
                raise Exception(
                    f"Request to {server_desc} failed: session expired and reconnection failed"
                )

            # Retry the request after successful reconnection
            logger.debug(f"Retrying request to {server_desc} after session recovery")
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
