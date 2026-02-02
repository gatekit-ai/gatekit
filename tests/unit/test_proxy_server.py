"""Unit tests for MCPProxy core proxy server implementation.

This module tests the central proxy server that integrates with plugins
and handles MCP client-server communication.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch

from gatekit.proxy.server import MCPProxy
from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig, PluginsConfig
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.protocol.errors import MCPErrorCodes
from gatekit.plugins.interfaces import (
    ProcessingPipeline,
    PipelineOutcome,
)
from gatekit.plugins.manager import PluginManager


def create_pipeline(request, allowed=True, blocked_at=None):
    """Helper to create ProcessingPipeline for tests."""
    if allowed:
        return ProcessingPipeline(
            original_content=request,
            final_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
            capture_content=True,
        )
    else:
        return ProcessingPipeline(
            original_content=request,
            final_content=request,
            pipeline_outcome=PipelineOutcome.BLOCKED,
            blocked_at_stage=blocked_at or "SecurityPlugin",
            had_security_plugin=True,
            capture_content=False,
        )


class MockStdioServerForTesting:
    """Mock stdio server for unit testing."""

    def __init__(self):
        self._running = False
        self.messages_handled = 0
        self.notifications_sent = []

    async def start(self):
        """Mock start method."""
        self._running = True

    async def stop(self):
        """Mock stop method."""
        self._running = False

    def is_running(self):
        """Mock running check."""
        return self._running

    async def handle_messages(self, request_handler, notification_handler=None):
        """Mock message handling."""
        self.messages_handled += 1
        # Just return immediately for testing
        pass

    async def write_notification(self, notification):
        """Mock notification writing."""
        self.notifications_sent.append(notification)


@pytest.fixture
def mock_stdio_server():
    """Provide a mock stdio server for testing."""
    return MockStdioServerForTesting()


class TestMCPProxyInit:
    """Test MCPProxy initialization and configuration."""

    def test_proxy_init_with_valid_config(self, mock_stdio_server):
        """Test proxy initialization with valid configuration."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        assert proxy.config == config
        assert isinstance(proxy._plugin_manager, PluginManager)
        assert hasattr(
            proxy, "_server_manager"
        )  # Now uses server manager instead of direct transport
        assert proxy._is_running is False
        assert proxy._client_requests == 0
        assert isinstance(proxy.plugin_config, dict)

    def test_proxy_init_creates_plugin_manager_with_config(self, mock_stdio_server):
        """Test that proxy creates plugin manager with proper configuration."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Plugin manager should be initialized with configuration
        assert hasattr(proxy, "_plugin_manager")
        assert isinstance(proxy._plugin_manager, PluginManager)
        # Should have plugin_config property available
        assert hasattr(proxy, "plugin_config")
        assert isinstance(proxy.plugin_config, dict)

    def test_proxy_init_with_http_transport_raises_error(self, mock_stdio_server):
        """Test that HTTP transport raises NotImplementedError for v0.1.0."""
        from gatekit.config.models import HttpConfig

        config = ProxyConfig(
            transport="http",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
            http=HttpConfig(host="localhost", port=8080),
        )

        with pytest.raises(
            NotImplementedError, match="HTTP transport not implemented in v0.1.0"
        ):
            MCPProxy(config, stdio_server=mock_stdio_server)

    def test_proxy_init_includes_disabled_upstreams_in_connections(self, mock_stdio_server):
        """Test that proxy includes disabled upstreams in connections for later enablement."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="enabled_server",
                    command=["python", "-m", "enabled_server"],
                    enabled=True,
                ),
                UpstreamConfig(
                    name="disabled_server",
                    command=["python", "-m", "disabled_server"],
                    enabled=False,
                ),
                UpstreamConfig(
                    name="another_enabled",
                    command=["python", "-m", "another_enabled"],
                    enabled=True,
                ),
            ],
            timeouts=TimeoutConfig(),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # All servers should be in connections (including disabled)
        # This allows disabled servers to be enabled via hot-reload
        assert len(proxy._server_manager.connections) == 3
        assert "enabled_server" in proxy._server_manager.connections
        assert "another_enabled" in proxy._server_manager.connections
        assert "disabled_server" in proxy._server_manager.connections

        # But disabled server should have enabled=False in config
        disabled_conn = proxy._server_manager.connections["disabled_server"]
        assert disabled_conn.config.enabled is False

    def test_proxy_init_with_all_upstreams_disabled_keeps_in_connections(
        self, mock_stdio_server
    ):
        """Test that proxy keeps disabled upstreams in connections for later enablement."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="disabled1",
                    command=["python", "-m", "disabled1"],
                    enabled=False,
                ),
                UpstreamConfig(
                    name="disabled2",
                    command=["python", "-m", "disabled2"],
                    enabled=False,
                ),
            ],
            timeouts=TimeoutConfig(),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Should have connections but none enabled
        assert len(proxy._server_manager.connections) == 2
        assert "disabled1" in proxy._server_manager.connections
        assert "disabled2" in proxy._server_manager.connections

        # Both should be disabled
        for conn in proxy._server_manager.connections.values():
            assert conn.config.enabled is False

    def test_proxy_init_default_enabled_is_true(self, mock_stdio_server):
        """Test that upstreams are enabled by default."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="default_enabled",
                    command=["python", "-m", "default_enabled"],
                    # enabled not specified, should default to True
                ),
            ],
            timeouts=TimeoutConfig(),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Server should be in the connections
        assert len(proxy._server_manager.connections) == 1
        assert "default_enabled" in proxy._server_manager.connections


class TestMCPProxyLifecycle:
    """Test MCPProxy server lifecycle management."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

    @pytest.fixture
    def proxy(self, proxy_config, mock_stdio_server):
        """Create MCPProxy instance for testing."""
        return MCPProxy(proxy_config, stdio_server=mock_stdio_server)

    @pytest.mark.asyncio
    async def test_proxy_start_initializes_components(self, proxy, mock_stdio_server):
        """Test that start() properly initializes all components."""
        with (
            patch.object(
                proxy._plugin_manager, "load_plugins", new_callable=AsyncMock
            ) as mock_load_plugins,
            patch.object(
                proxy._server_manager, "connect_all", new_callable=AsyncMock
            ) as mock_connect,
        ):

            # Mock connect_all to return (successful=1, failed=0)
            mock_connect.return_value = (1, 0)

            await proxy.start()

            mock_load_plugins.assert_called_once()
            mock_connect.assert_called_once()
            assert proxy._is_running is True

    @pytest.mark.asyncio
    async def test_proxy_start_twice_raises_error(self, proxy, mock_stdio_server):
        """Test that starting an already running proxy raises error."""
        with (
            patch.object(proxy._plugin_manager, "load_plugins", new_callable=AsyncMock),
            patch.object(
                proxy._server_manager, "connect_all", new_callable=AsyncMock
            ) as mock_connect,
        ):

            # Mock connect_all to return (successful=1, failed=0)
            mock_connect.return_value = (1, 0)

            await proxy.start()

            with pytest.raises(RuntimeError, match="Proxy is already running"):
                await proxy.start()

    @pytest.mark.asyncio
    async def test_proxy_stop_cleanup(self, proxy, mock_stdio_server):
        """Test that stop() properly cleans up resources."""
        with (
            patch.object(proxy._plugin_manager, "load_plugins", new_callable=AsyncMock),
            patch.object(
                proxy._server_manager, "connect_all", new_callable=AsyncMock
            ) as mock_connect,
            patch.object(
                proxy._server_manager, "disconnect_all", new_callable=AsyncMock
            ) as mock_disconnect,
            patch.object(
                proxy._plugin_manager, "cleanup", new_callable=AsyncMock
            ) as mock_cleanup,
        ):

            # Mock connect_all to return (successful=1, failed=0)
            mock_connect.return_value = (1, 0)

            await proxy.start()
            await proxy.stop()

            mock_disconnect.assert_called_once()
            mock_cleanup.assert_called_once()
            assert proxy._is_running is False

    @pytest.mark.asyncio
    async def test_proxy_stop_when_not_running_is_safe(self, proxy, mock_stdio_server):
        """Test that stop() is safe when proxy is not running."""
        with (
            patch.object(
                proxy._server_manager, "disconnect_all", new_callable=AsyncMock
            ) as mock_disconnect,
            patch.object(
                proxy._plugin_manager, "cleanup", new_callable=AsyncMock
            ) as mock_cleanup,
        ):

            # Should not raise error
            await proxy.stop()

            mock_disconnect.assert_called_once()
            mock_cleanup.assert_called_once()


class TestMCPProxyRequestProcessing:
    """Test MCPProxy 5-step request processing pipeline."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

    @pytest.fixture
    def proxy(self, proxy_config, mock_stdio_server):
        """Create MCPProxy instance for testing."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)
        proxy._is_running = True  # Set as running for tests
        return proxy

    @pytest.fixture
    def sample_request(self):
        """Create sample MCP request."""
        return MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_server__echo", "arguments": {"text": "hello"}},
        )

    @pytest.fixture
    def sample_response(self):
        """Create sample MCP response."""
        return MCPResponse(jsonrpc="2.0", id="test-1", result={"output": "hello"})

    @pytest.mark.asyncio
    async def test_handle_request_allowed_full_pipeline(
        self, proxy, sample_request, sample_response, mock_stdio_server
    ):
        """Test complete 5-step pipeline for allowed request."""
        # Create clean request that would be created by parse_incoming_request
        clean_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "echo", "arguments": {"text": "hello"}},
        )

        # Create ProcessingPipeline with clean request
        allowed_pipeline = ProcessingPipeline(
            original_content=clean_request,
            final_content=clean_request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
            capture_content=True,
        )

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=allowed_pipeline,
            ) as mock_process,
            patch.object(
                proxy._plugin_manager, "log_request", new_callable=AsyncMock
            ) as mock_log_request,
            patch.object(
                proxy,
                "_route_request",
                new_callable=AsyncMock,
                return_value=sample_response,
            ) as mock_route,
            patch.object(
                proxy._plugin_manager, "log_response", new_callable=AsyncMock
            ) as mock_log_response,
        ):

            result = await proxy.handle_request(sample_request)

            # Verify 5-step pipeline
            # Step 1: Security check (now receives the clean request from RoutedRequest)
            from unittest.mock import ANY

            # The process_request receives the CLEAN request (denamespaced) from RoutedRequest
            clean_request = mock_process.call_args[0][0]
            assert (
                clean_request.params["name"] == "echo"
            )  # Clean name without namespace
            assert (
                mock_process.call_args[0][1] == "test_server"
            )  # Server name extracted

            # Step 2: Log request (uses clean request from routed.request)
            mock_log_request.assert_called_once_with(
                clean_request, allowed_pipeline, "test_server"
            )

            # Step 3: Policy check passed, so forward request
            # Step 4: Forward to upstream using RoutedRequest
            from gatekit.core.routing import RoutedRequest

            # _route_request now receives a RoutedRequest
            assert mock_route.called
            routed_arg = mock_route.call_args[0][0]
            assert isinstance(routed_arg, RoutedRequest)
            assert routed_arg.request.params["name"] == "echo"  # Clean request
            assert routed_arg.target_server == "test_server"
            assert routed_arg.namespaced_name == "test_server__echo"

            # Step 5: Log response (uses clean request from routed.request)
            mock_log_response.assert_called_once_with(
                clean_request, sample_response, ANY, "test_server"
            )

            assert result == sample_response
            assert proxy._client_requests == 1

    @pytest.mark.asyncio
    async def test_handle_request_blocked_by_policy(
        self, proxy, sample_request, mock_stdio_server
    ):
        """Test request blocked by security policy."""
        # Create clean request that would be created by parse_incoming_request
        clean_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "echo", "arguments": {"text": "hello"}},
        )
        blocked_pipeline = create_pipeline(
            clean_request, allowed=False, blocked_at="Tool not allowed"
        )

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=blocked_pipeline,
            ) as mock_process,
            patch.object(
                proxy._plugin_manager, "log_request", new_callable=AsyncMock
            ) as mock_log_request,
            patch.object(proxy, "_route_request", new_callable=AsyncMock) as mock_route,
            patch.object(
                proxy._plugin_manager, "log_response", new_callable=AsyncMock
            ) as mock_log_response,
        ):

            result = await proxy.handle_request(sample_request)

            # Steps 1-2: Process and log request

            # process_request gets the clean request
            clean_req = mock_process.call_args[0][0]
            assert clean_req.params["name"] == "echo"
            assert mock_process.call_args[0][1] == "test_server"
            # log_request now receives the clean request from routed.request
            mock_log_request.assert_called_once_with(
                clean_request, blocked_pipeline, "test_server"
            )

            # Step 3: Should not forward to upstream
            mock_route.assert_not_called()

            # Step 5: Should log error response
            mock_log_response.assert_called_once()
            logged_response = mock_log_response.call_args[0][
                1
            ]  # Second argument is the response

            # Verify error response format
            assert result.jsonrpc == "2.0"
            assert result.id == "test-1"
            assert result.error is not None
            assert result.error["code"] == MCPErrorCodes.SECURITY_VIOLATION
            assert "Tool not allowed" in result.error["message"]
            assert result == logged_response

    @pytest.mark.asyncio
    async def test_handle_request_when_not_running(
        self, proxy, sample_request, mock_stdio_server
    ):
        """Test handling request when proxy is not running."""
        proxy._is_running = False

        with pytest.raises(RuntimeError, match="Proxy is not running"):
            await proxy.handle_request(sample_request)

    @pytest.mark.asyncio
    async def test_handle_request_upstream_failure(
        self, proxy, sample_request, mock_stdio_server
    ):
        """Test handling upstream transport failure."""
        # Create clean request that would be created by parse_incoming_request
        clean_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "echo", "arguments": {"text": "hello"}},
        )
        allowed_pipeline = create_pipeline(clean_request, allowed=True)

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=allowed_pipeline,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(
                proxy,
                "_route_request",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Connection failed"),
            ) as mock_route,
            patch.object(
                proxy._plugin_manager, "log_response", new_callable=AsyncMock
            ) as mock_log_response,
        ):

            result = await proxy.handle_request(sample_request)

            # _route_request now receives a RoutedRequest
            from gatekit.core.routing import RoutedRequest

            assert mock_route.called
            routed_arg = mock_route.call_args[0][0]
            assert isinstance(routed_arg, RoutedRequest)
            mock_log_response.assert_called_once()

            # Should return proper error response
            assert result.jsonrpc == "2.0"
            assert result.id == "test-1"
            assert result.error is not None
            assert result.error["code"] == MCPErrorCodes.UPSTREAM_UNAVAILABLE
            assert "Connection failed" in result.error["message"]

    @pytest.mark.asyncio
    async def test_handle_request_plugin_failure_fails_closed(
        self, proxy, sample_request, sample_response, mock_stdio_server
    ):
        """Test that plugin failures cause request to be blocked (fail-closed)."""
        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                side_effect=Exception("Plugin error"),
            ) as mock_process,
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(
                proxy,
                "_route_request",
                new_callable=AsyncMock,
                return_value=sample_response,
            ) as mock_route,
            patch.object(
                proxy._plugin_manager, "log_response", new_callable=AsyncMock
            ) as mock_log_response,
        ):

            result = await proxy.handle_request(sample_request)


            # process_request gets the clean request
            clean_req = mock_process.call_args[0][0]
            assert clean_req.params["name"] == "echo"
            assert mock_process.call_args[0][1] == "test_server"
            # Should NOT continue with request (fail-closed)
            mock_route.assert_not_called()
            mock_log_response.assert_not_called()

            # Should return error response
            assert result.id == "test-1"
            assert result.error is not None
            assert result.error["code"] == MCPErrorCodes.INTERNAL_ERROR
            assert "Security check failed" in result.error["message"]


class TestMCPProxyErrorHandling:
    """Test MCPProxy error handling and resilience."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

    @pytest.fixture
    def proxy(self, proxy_config, mock_stdio_server):
        """Create MCPProxy instance for testing."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)
        proxy._is_running = True
        return proxy

    @pytest.mark.asyncio
    async def test_handle_request_with_malformed_request(
        self, proxy, mock_stdio_server
    ):
        """Test handling of malformed request objects."""
        # Create malformed request (missing required fields)
        malformed_request = MCPRequest(
            jsonrpc="2.0", method="", id="test-1"  # Empty method
        )

        result = await proxy.handle_request(malformed_request)

        assert result.jsonrpc == "2.0"
        assert result.id == "test-1"
        assert result.error is not None
        assert result.error["code"] == MCPErrorCodes.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_handle_startup_failure_cleanup(self, proxy, mock_stdio_server):
        """Test that startup failure properly cleans up."""
        proxy._is_running = False

        with (
            patch.object(
                proxy._plugin_manager, "load_plugins", new_callable=AsyncMock
            ) as mock_load_plugins,
            patch.object(
                proxy._server_manager,
                "connect_all",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Connection failed"),
            ),
            patch.object(
                proxy._plugin_manager, "cleanup", new_callable=AsyncMock
            ) as mock_cleanup,
        ):

            with pytest.raises(RuntimeError, match="Connection failed"):
                await proxy.start()

            # Should cleanup loaded plugins on failure
            mock_load_plugins.assert_called_once()
            mock_cleanup.assert_called_once()
            assert proxy._is_running is False

    @pytest.mark.asyncio
    async def test_context_manager_cleanup(self, proxy_config, mock_stdio_server):
        """Test that proxy context manager properly cleans up."""
        proxy = MCPProxy(
            proxy_config, stdio_server=mock_stdio_server
        )  # Create fresh proxy for context manager test

        with (
            patch.object(proxy._plugin_manager, "load_plugins", new_callable=AsyncMock),
            patch.object(
                proxy._server_manager, "connect_all", new_callable=AsyncMock
            ) as mock_connect,
            patch.object(
                proxy._server_manager, "disconnect_all", new_callable=AsyncMock
            ) as mock_disconnect,
            patch.object(
                proxy._plugin_manager, "cleanup", new_callable=AsyncMock
            ) as mock_cleanup,
        ):

            # Mock connect_all to return (successful=1, failed=0)
            mock_connect.return_value = (1, 0)

            async with proxy:
                assert proxy._is_running is True

            mock_disconnect.assert_called_once()
            mock_cleanup.assert_called_once()
            assert proxy._is_running is False


class TestMCPProxyIntegration:
    """Test MCPProxy integration with existing components."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

    def test_proxy_uses_plugin_manager_correctly(self, proxy_config, mock_stdio_server):
        """Test that proxy initializes PluginManager with plugin configuration."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)

        assert isinstance(proxy._plugin_manager, PluginManager)
        # Should be initialized with plugin config from configuration system

    def test_proxy_uses_stdio_transport_correctly(
        self, proxy_config, mock_stdio_server
    ):
        """Test that proxy initializes StdioTransport with upstream config."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)

        assert hasattr(proxy, "_server_manager")  # Now uses server manager
        # Server manager should be initialized with upstream configs
        assert (
            len(proxy._server_manager.connections) == 2
        )  # We now have test_server and example_server
        # Check that both servers are configured correctly
        test_server_conn = proxy._server_manager.connections.get("test_server")
        assert test_server_conn is not None
        assert test_server_conn.config.command == proxy_config.upstreams[0].command

        example_server_conn = proxy._server_manager.connections.get("example_server")
        assert example_server_conn is not None
        assert example_server_conn.config.command == proxy_config.upstreams[1].command

    @pytest.mark.asyncio
    async def test_proxy_request_stats_tracking(self, proxy_config, mock_stdio_server):
        """Test that proxy tracks request statistics."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)
        proxy._is_running = True

        request = MCPRequest(jsonrpc="2.0", method="tools/list", id="test-1")
        response = MCPResponse(jsonrpc="2.0", id="test-1", result={})
        allowed_pipeline = create_pipeline(request, allowed=True)

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=allowed_pipeline,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(
                proxy, "_route_request", new_callable=AsyncMock, return_value=response
            ),
            patch.object(proxy._plugin_manager, "log_response", new_callable=AsyncMock),
        ):

            await proxy.handle_request(request)
            await proxy.handle_request(request)

            assert proxy._client_requests == 2

    def test_proxy_plugin_configuration_integration(
        self, proxy_config, mock_stdio_server
    ):
        """Test plugin configuration integration."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)

        # Plugin configuration should be accessible through property
        plugin_config = proxy.plugin_config
        assert isinstance(plugin_config, dict)

        # Should return empty dict if no plugins configured
        assert plugin_config == {}


class TestMCPProxyProtocolCompliance:
    """Test MCPProxy compliance with MCP protocol."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
                UpstreamConfig(
                    name="example_server", command=["python", "-m", "example_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

    @pytest.fixture
    def proxy(self, proxy_config, mock_stdio_server):
        """Create MCPProxy instance for testing."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)
        proxy._is_running = True
        return proxy

    @pytest.mark.asyncio
    async def test_proxy_preserves_request_id(
        self, proxy, sample_initialize_request, mock_stdio_server
    ):
        """Test that proxy preserves request ID in responses."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-123",
            params=sample_initialize_request["params"],
        )

        blocked_pipeline = create_pipeline(request, allowed=False, blocked_at="Blocked")

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=blocked_pipeline,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(proxy._plugin_manager, "log_response", new_callable=AsyncMock),
        ):

            result = await proxy.handle_request(request)

            assert result.id == "init-123"

    @pytest.mark.asyncio
    async def test_proxy_maintains_jsonrpc_version(self, proxy, mock_stdio_server):
        """Test that proxy maintains JSON-RPC 2.0 version."""
        request = MCPRequest(jsonrpc="2.0", method="tools/list", id="test-1")
        blocked_pipeline = create_pipeline(request, allowed=False, blocked_at="Blocked")

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=blocked_pipeline,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(proxy._plugin_manager, "log_response", new_callable=AsyncMock),
        ):

            result = await proxy.handle_request(request)

            assert result.jsonrpc == "2.0"

    @pytest.mark.asyncio
    async def test_proxy_handles_initialize_method(
        self, proxy, sample_initialize_request, mock_stdio_server
    ):
        """Test proxy handling of initialize method."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-1",
            params=sample_initialize_request["params"],
        )

        response = MCPResponse(
            jsonrpc="2.0",
            id="init-1",
            result={"protocolVersion": "2024-11-05", "capabilities": {}},
        )

        allowed_pipeline = create_pipeline(request, allowed=True)

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=allowed_pipeline,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(
                proxy, "_route_request", new_callable=AsyncMock, return_value=response
            ),
            patch.object(proxy._plugin_manager, "log_response", new_callable=AsyncMock),
            patch.object(
                proxy._server_manager,
                "reconnect_server",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):

            result = await proxy.handle_request(request)

            # The actual initialize handler returns a different structure, so just check key fields
            assert result.jsonrpc == "2.0"
            assert result.id == "init-1"
            assert result.result is not None
            assert "capabilities" in result.result

    @pytest.mark.asyncio
    async def test_proxy_handles_tools_call_method(
        self, proxy, sample_tools_call_request, mock_stdio_server
    ):
        """Test proxy handling of tools/call method."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="tool-1",
            params=sample_tools_call_request["params"],
        )

        response = MCPResponse(
            jsonrpc="2.0", id="tool-1", result={"output": "Hello, World!"}
        )

        # Create clean request for the pipeline
        clean_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="tool-1",
            params={"name": "echo", "arguments": {"text": "Hello, World!"}},
        )
        allowed_pipeline = create_pipeline(clean_request, allowed=True)

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                return_value=allowed_pipeline,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(
                proxy, "_route_request", new_callable=AsyncMock, return_value=response
            ),
            patch.object(proxy._plugin_manager, "log_response", new_callable=AsyncMock),
        ):

            result = await proxy.handle_request(request)

            assert result == response
            assert result.result["output"] == "Hello, World!"


class TestMCPProxyHotReload:
    """Test MCPProxy hot-reload functionality."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
        )

    @pytest.fixture
    def proxy(self, proxy_config, mock_stdio_server):
        """Create MCPProxy instance for testing."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)
        proxy._is_running = True
        return proxy

    def test_proxy_init_with_config_path(self, proxy_config, mock_stdio_server):
        """Test proxy initialization with config_path."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("proxy:\n  upstreams: []\n")
            config_path = Path(f.name)

        try:
            proxy = MCPProxy(
                proxy_config,
                config_path=config_path,
                stdio_server=mock_stdio_server,
            )

            assert proxy._config_path == config_path
            assert proxy._config_mtime is not None
        finally:
            config_path.unlink()

    def test_proxy_init_without_config_path(self, proxy_config, mock_stdio_server):
        """Test proxy initialization without config_path."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)

        assert proxy._config_path is None
        assert proxy._config_mtime is None

    @pytest.mark.asyncio
    async def test_acquire_release_generation(self, proxy):
        """Test generation token acquisition and release."""
        # Initial state
        assert proxy._plugin_manager_generation == 0
        assert proxy._active_requests_per_generation == {0: 0}

        # Acquire
        gen = await proxy._acquire_generation()
        assert gen == 0
        assert proxy._active_requests_per_generation[0] == 1

        # Acquire again
        gen2 = await proxy._acquire_generation()
        assert gen2 == 0
        assert proxy._active_requests_per_generation[0] == 2

        # Release one
        await proxy._release_generation(gen)
        assert proxy._active_requests_per_generation[0] == 1

        # Release the other
        await proxy._release_generation(gen2)
        # Generation 0 should be removed when count reaches 0
        assert 0 not in proxy._active_requests_per_generation

    @pytest.mark.asyncio
    async def test_check_and_reload_config_no_path(self, proxy):
        """Test that hot-reload does nothing when no config path."""
        proxy._config_path = None

        # Should return without doing anything
        await proxy._check_and_reload_config()

    @pytest.mark.asyncio
    async def test_check_and_reload_config_no_change(self, proxy):
        """Test that hot-reload skips when mtime unchanged."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("proxy:\n  upstreams: []\n")
            config_path = Path(f.name)

        try:
            proxy._config_path = config_path
            proxy._config_mtime = config_path.stat().st_mtime

            # Should not call _apply_config_changes
            with patch.object(proxy, "_apply_config_changes") as mock_apply:
                await proxy._check_and_reload_config()
                mock_apply.assert_not_called()
        finally:
            config_path.unlink()

    @pytest.mark.asyncio
    async def test_check_and_reload_config_detects_change(self, proxy):
        """Test that hot-reload detects mtime change."""
        import tempfile
        import time
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("proxy:\n  upstreams: []\n")
            config_path = Path(f.name)

        try:
            proxy._config_path = config_path
            proxy._config_mtime = config_path.stat().st_mtime - 1  # Old mtime
            proxy._hot_reload_enabled = True  # Enable hot-reload for this test

            # Should call _apply_config_changes
            with patch.object(proxy, "_apply_config_changes", new_callable=AsyncMock) as mock_apply:
                await proxy._check_and_reload_config()
                mock_apply.assert_called_once()
        finally:
            config_path.unlink()

    def test_is_csv_format_breaking_change_no_csv(self, proxy):
        """Test CSV format check when no CSV plugin."""
        old_config = {"auditing": {}}
        new_config = {"auditing": {}}

        result = proxy._is_csv_format_breaking_change(old_config, new_config)
        assert result is False

    def test_is_csv_format_breaking_change_different_file(self, proxy):
        """Test CSV format check when output files differ."""
        old_config = {
            "auditing": {
                "_global": [
                    {"handler": "csv_audit", "config": {"output_file": "old.csv"}}
                ]
            }
        }
        new_config = {
            "auditing": {
                "_global": [
                    {"handler": "csv_audit", "config": {"output_file": "new.csv"}}
                ]
            }
        }

        result = proxy._is_csv_format_breaking_change(old_config, new_config)
        assert result is False  # Different files = no corruption risk

    def test_is_csv_format_breaking_change_same_file_format_changed(self, proxy):
        """Test CSV format check when format changes with same file."""
        old_config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "csv_audit",
                        "config": {
                            "output_file": "audit.csv",
                            "csv_config": {"delimiter": ","},
                        },
                    }
                ]
            }
        }
        new_config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "csv_audit",
                        "config": {
                            "output_file": "audit.csv",
                            "csv_config": {"delimiter": "|"},
                        },
                    }
                ]
            }
        }

        result = proxy._is_csv_format_breaking_change(old_config, new_config)
        assert result is True  # Same file + format change = corruption risk

    def test_is_csv_format_breaking_change_same_file_no_format_change(self, proxy):
        """Test CSV format check when format unchanged with same file."""
        old_config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "csv_audit",
                        "config": {
                            "output_file": "audit.csv",
                            "csv_config": {"delimiter": ","},
                        },
                    }
                ]
            }
        }
        new_config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "csv_audit",
                        "config": {
                            "output_file": "audit.csv",
                            "csv_config": {"delimiter": ","},
                        },
                    }
                ]
            }
        }

        result = proxy._is_csv_format_breaking_change(old_config, new_config)
        assert result is False  # Same format = safe

    def test_get_plugin_names(self, proxy):
        """Test extracting plugin names from config."""
        config = {
            "middleware": {
                "_global": [{"handler": "tool_manager"}]
            },
            "security": {
                "_global": [{"handler": "allow_list"}],
                "server1": [{"handler": "deny_list"}],
            },
            "auditing": {
                "_global": [{"handler": "jsonl_audit"}]
            },
        }

        names = proxy._get_plugin_names(config)
        assert names == {"tool_manager", "allow_list", "deny_list", "jsonl_audit"}

    def test_log_plugin_config_changes(self, proxy, caplog):
        """Test plugin change logging."""
        import logging

        old_plugins = {
            "middleware": {"_global": [{"handler": "old_middleware"}]},
            "security": {"_global": [{"handler": "unchanged", "config": {"key": "old"}}]},
            "auditing": {"_global": [{"handler": "modified", "config": {"setting": "a"}}]},
        }
        new_plugins = {
            "middleware": {"_global": [{"handler": "new_middleware"}]},
            "security": {"_global": [{"handler": "unchanged", "config": {"key": "old"}}]},
            "auditing": {"_global": [{"handler": "modified", "config": {"setting": "b"}}]},
        }

        with caplog.at_level(logging.INFO):
            proxy._log_plugin_config_changes(old_plugins, new_plugins)

        # Should log added and removed plugins
        assert "Plugin 'new_middleware' added" in caplog.text
        assert "Plugin 'old_middleware' removed" in caplog.text
        # unchanged should NOT be logged (config is identical)
        assert "Plugin 'unchanged' configuration changed" not in caplog.text
        # modified should be logged (config actually changed)
        assert "Plugin 'modified' configuration changed" in caplog.text

    @pytest.mark.asyncio
    async def test_apply_config_changes_rejects_transport_change(self, proxy, caplog):
        """Test that transport changes are rejected."""
        import tempfile
        import logging
        from pathlib import Path

        yaml_content = """
proxy:
  transport: http
  http:
    host: localhost
    port: 8080
  upstreams:
    - name: test
      transport: stdio
      command: ["python", "-m", "test"]
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            config_path = Path(f.name)

        try:
            proxy._config_path = config_path
            proxy._config_directory = config_path.parent
            original_config = proxy.config

            with caplog.at_level(logging.WARNING):
                await proxy._apply_config_changes()

            # Config should not have changed
            assert proxy.config == original_config
            assert "transport changes require restart" in caplog.text
        finally:
            config_path.unlink()

    @pytest.mark.asyncio
    async def test_notify_capability_changes(self, proxy, mock_stdio_server):
        """Test that capability notifications are sent."""
        proxy._stdio_server = mock_stdio_server
        proxy._hot_reload_enabled = True  # Enable hot-reload for this test

        await proxy._notify_capability_changes()

        # Should have sent 3 notifications
        assert len(mock_stdio_server.notifications_sent) == 3

        methods = [n.method for n in mock_stdio_server.notifications_sent]
        assert "notifications/tools/list_changed" in methods
        assert "notifications/resources/list_changed" in methods
        assert "notifications/prompts/list_changed" in methods

    @pytest.mark.asyncio
    async def test_start_notification_listener_already_running(self, proxy):
        """Test that starting already-running listener is safe."""
        import asyncio

        # Create a mock running task
        async def never_ending():
            while True:
                await asyncio.sleep(100)

        task = asyncio.create_task(never_ending())
        proxy._notification_tasks["test_server"] = task

        try:
            # Should not create a new task
            proxy._start_notification_listener("test_server")

            # Should still be the same task
            assert proxy._notification_tasks["test_server"] is task
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_stop_notification_listener(self, proxy):
        """Test stopping a notification listener."""
        import asyncio

        # Create a mock task
        async def never_ending():
            try:
                while True:
                    await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(never_ending())
        proxy._notification_tasks["test_server"] = task

        await proxy._stop_notification_listener("test_server")

        assert "test_server" not in proxy._notification_tasks
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_stop_notification_listener_nonexistent(self, proxy):
        """Test stopping a non-existent listener is safe."""
        # Should not raise
        await proxy._stop_notification_listener("nonexistent")

    @pytest.mark.asyncio
    async def test_handle_request_uses_captured_plugin_manager(self, proxy, mock_stdio_server):
        """Test that handle_request captures plugin_manager reference."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_server__echo", "arguments": {}},
        )

        response = MCPResponse(jsonrpc="2.0", id="test-1", result={})
        clean_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "echo", "arguments": {}},
        )
        allowed_pipeline = create_pipeline(clean_request, allowed=True)

        captured_managers = []

        async def capture_manager(req, server_name):
            captured_managers.append(proxy._plugin_manager)
            return allowed_pipeline

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                side_effect=capture_manager,
            ),
            patch.object(proxy._plugin_manager, "log_request", new_callable=AsyncMock),
            patch.object(
                proxy, "_route_request", new_callable=AsyncMock, return_value=response
            ),
            patch.object(proxy._plugin_manager, "log_response", new_callable=AsyncMock),
            patch.object(proxy, "_check_and_reload_config", new_callable=AsyncMock),
        ):
            await proxy.handle_request(request)

        # The plugin manager reference should be captured at request start
        assert len(captured_managers) == 1

    @pytest.mark.asyncio
    async def test_handle_request_releases_generation_on_error(self, proxy, mock_stdio_server):
        """Test that generation is released even on error."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_server__echo", "arguments": {}},
        )

        # Verify initial state
        assert proxy._active_requests_per_generation.get(0, 0) == 0

        with (
            patch.object(
                proxy._plugin_manager,
                "process_request",
                new_callable=AsyncMock,
                side_effect=Exception("Test error"),
            ),
            patch.object(proxy, "_check_and_reload_config", new_callable=AsyncMock),
        ):
            # Should not raise - error is caught internally
            result = await proxy.handle_request(request)

        # Response should be an error
        assert result.error is not None

        # Generation should be released (count back to 0)
        assert proxy._active_requests_per_generation.get(0, 0) == 0

    @pytest.mark.asyncio
    async def test_cleanup_old_plugin_manager_waits_for_requests(self, proxy):
        """Test that old plugin manager cleanup waits for in-flight requests."""
        # Simulate an in-flight request on generation 0
        proxy._active_requests_per_generation[0] = 1

        old_manager = proxy._plugin_manager
        old_manager.cleanup = AsyncMock()

        cleanup_started = False
        cleanup_finished = False

        async def cleanup_wrapper():
            nonlocal cleanup_started, cleanup_finished
            cleanup_started = True
            await proxy._cleanup_old_plugin_manager(old_manager, 0)
            cleanup_finished = True

        import asyncio

        cleanup_task = asyncio.create_task(cleanup_wrapper())

        # Give it a moment to start
        await asyncio.sleep(0.1)

        # Cleanup should have started but not finished
        assert cleanup_started
        assert not cleanup_finished
        old_manager.cleanup.assert_not_called()

        # Now release the generation
        await proxy._release_generation(0)

        # Wait for cleanup to finish
        await cleanup_task

        # Cleanup should have been called
        old_manager.cleanup.assert_called_once()
        assert cleanup_finished

    @pytest.mark.asyncio
    async def test_broadcast_notification_skips_disabled_servers(self, mock_stdio_server):
        """Test that broadcast notifications skip disabled servers."""
        from gatekit.config.models import UpstreamConfig

        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="enabled_server", command=["echo", "test"], enabled=True),
                UpstreamConfig(name="disabled_server", command=["echo", "test"], enabled=False),
            ],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(security={}, auditing={}),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)
        proxy._is_running = True

        # Set up mock connections
        enabled_conn = Mock()
        enabled_conn.config = config.upstreams[0]  # enabled
        enabled_conn.status = "connected"
        enabled_conn.transport = AsyncMock()

        disabled_conn = Mock()
        disabled_conn.config = config.upstreams[1]  # disabled
        disabled_conn.status = "connected"  # Even if "connected", should be skipped
        disabled_conn.transport = AsyncMock()

        proxy._server_manager.connections = {
            "enabled_server": enabled_conn,
            "disabled_server": disabled_conn,
        }

        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/initialized",
            params={},
        )

        await proxy._broadcast_notification_to_all_servers(notification)

        # Only enabled server should receive the notification
        enabled_conn.transport.send_notification.assert_called_once_with(notification)
        disabled_conn.transport.send_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_request_internal_reconnect_timeout(self, mock_stdio_server):
        """Test that reconnection wait has a timeout to prevent deadlock."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test_server", command=["echo", "test"]),
            ],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(security={}, auditing={}),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)
        proxy._is_running = True

        # Mock a connection that is stuck reconnecting
        mock_conn = Mock()
        mock_conn.config = config.upstreams[0]
        mock_conn.status = "disconnected"
        mock_conn._reconnecting = True  # Stuck in reconnecting state
        mock_conn.error = None

        # Override get_server_description
        proxy._server_manager.get_server_description = Mock(return_value="server 'test_server'")

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "echo"},
        )

        # Patch sleep to speed up the test
        original_sleep = asyncio.sleep

        async def fast_sleep(delay):
            # Make sleep instant for testing
            await original_sleep(0)

        with patch("gatekit.proxy.server.asyncio.sleep", fast_sleep):
            # Should timeout and raise exception
            with pytest.raises(Exception) as exc_info:
                await proxy._route_request_internal(mock_conn, "test_server", request)

            assert "timed out" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_start_with_all_servers_disabled(self, mock_stdio_server):
        """Test that proxy can start with all servers disabled for later hot-reload enablement."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["echo", "test"], enabled=False),
                UpstreamConfig(name="server2", command=["echo", "test"], enabled=False),
            ],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(security={}, auditing={}),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Mock the necessary methods
        proxy._plugin_manager.load_plugins = AsyncMock()
        proxy._server_manager.connect_all = AsyncMock(return_value=(0, 0))
        proxy._stdio_server.start = AsyncMock()

        # Should not raise - starting with all disabled is allowed
        await proxy.start()

        assert proxy._is_running is True

        await proxy.stop()

    @pytest.mark.asyncio
    async def test_update_server_enable_with_reconnect_no_double_connect(self, mock_stdio_server):
        """Test that enabling a server with reconnect settings doesn't double-connect."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test_server", command=["old_cmd"], enabled=False),
            ],
            timeouts=TimeoutConfig(connection_timeout=5, request_timeout=5),
            plugins=PluginsConfig(security={}, auditing={}),
        )

        proxy = MCPProxy(config, stdio_server=mock_stdio_server)
        proxy._is_running = True

        # Track connection attempts
        connect_calls = []

        async def track_connect_server(name):
            connect_calls.append(("connect_server", name))
            return True

        async def track_add_server(cfg, connect=True):
            connect_calls.append(("add_server", cfg.name, connect))
            # Simulate add_server creating a connected connection
            mock_conn = Mock()
            mock_conn.config = cfg
            mock_conn.status = "connected" if connect and cfg.enabled else "disconnected"
            mock_conn.transport = Mock()
            proxy._server_manager.connections[cfg.name] = mock_conn
            return True

        async def track_remove_server(name):
            connect_calls.append(("remove_server", name))
            proxy._server_manager.connections.pop(name, None)

        proxy._server_manager.connect_server = track_connect_server
        proxy._server_manager.add_server = track_add_server
        proxy._server_manager.remove_server = track_remove_server

        # Set up initial mock connection (disabled)
        mock_conn = Mock()
        mock_conn.config = config.upstreams[0]
        mock_conn.status = "disconnected"
        mock_conn.transport = None
        proxy._server_manager.connections = {"test_server": mock_conn}

        # New config: enabled with different command (needs reconnect)
        old_config = config.upstreams[0]
        new_config = UpstreamConfig(name="test_server", command=["new_cmd"], enabled=True)

        await proxy._update_server(old_config, new_config)

        # Should have: remove_server, add_server (which connects since enabled)
        # Should NOT have: connect_server (that would be double-connecting)
        assert ("remove_server", "test_server") in connect_calls
        assert any(c[0] == "add_server" and c[1] == "test_server" for c in connect_calls)
        # Verify connect_server was NOT called (add_server handles connection)
        assert not any(c[0] == "connect_server" for c in connect_calls)


class TestClientAwareHotReload:
    """Test client-aware hot-reload functionality."""

    @pytest.fixture
    def proxy_config(self):
        """Create test proxy configuration with hot_reload=auto for client detection tests."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", command=["python", "-m", "test_server"]
                ),
            ],
            timeouts=TimeoutConfig(),
            hot_reload="auto",  # Enable client detection for these tests
        )

    @pytest.fixture
    def proxy(self, proxy_config, mock_stdio_server):
        """Create MCPProxy instance for testing."""
        proxy = MCPProxy(proxy_config, stdio_server=mock_stdio_server)
        proxy._is_running = True
        return proxy

    # --- Client Name Matching Tests ---

    def test_check_client_hot_reload_support_exact_match_claude_code(self, proxy):
        """Test exact matching for claude-code client."""
        assert proxy._check_client_hot_reload_support("claude-code") is False

    def test_check_client_hot_reload_support_exact_match_github_copilot(self, proxy):
        """Test exact matching for github-copilot client (known working)."""
        assert proxy._check_client_hot_reload_support("github-copilot") is True

    def test_check_client_hot_reload_support_exact_match_cursor(self, proxy):
        """Test exact matching for cursor client."""
        assert proxy._check_client_hot_reload_support("cursor") is False

    def test_check_client_hot_reload_support_exact_match_claude_desktop(self, proxy):
        """Test exact matching for claude-desktop client."""
        assert proxy._check_client_hot_reload_support("claude-desktop") is False

    def test_check_client_hot_reload_support_exact_match_claude(self, proxy):
        """Test exact matching for claude client (Claude Desktop variant)."""
        assert proxy._check_client_hot_reload_support("claude") is False

    # --- Normalization Tests ---

    def test_check_client_hot_reload_support_normalizes_spaces(self, proxy):
        """Test that client names with spaces are normalized to hyphens."""
        # "Claude Code" -> "claude-code"
        assert proxy._check_client_hot_reload_support("Claude Code") is False

    def test_check_client_hot_reload_support_normalizes_underscores(self, proxy):
        """Test that client names with underscores are normalized to hyphens."""
        # "claude_code" -> "claude-code"
        assert proxy._check_client_hot_reload_support("claude_code") is False

    def test_check_client_hot_reload_support_normalizes_uppercase(self, proxy):
        """Test that client names are case-insensitive."""
        assert proxy._check_client_hot_reload_support("CLAUDE-CODE") is False
        assert proxy._check_client_hot_reload_support("GITHUB-COPILOT") is True

    def test_check_client_hot_reload_support_normalizes_mixed_case(self, proxy):
        """Test normalization with mixed case and delimiters."""
        assert proxy._check_client_hot_reload_support("Claude_Code") is False
        assert proxy._check_client_hot_reload_support("GitHub Copilot") is True

    # --- Unknown Client Tests ---

    def test_check_client_hot_reload_support_unknown_client_defaults_false(self, proxy):
        """Test that unknown clients default to hot-reload disabled."""
        assert proxy._check_client_hot_reload_support("unknown-client") is False
        assert proxy._check_client_hot_reload_support("my-custom-mcp-client") is False
        assert proxy._check_client_hot_reload_support("zed") is False

    def test_check_client_hot_reload_support_empty_name(self, proxy):
        """Test that empty client name defaults to disabled."""
        assert proxy._check_client_hot_reload_support("") is False

    # --- Config Override Tests ---

    def test_check_client_hot_reload_support_config_override_enabled(self, mock_stdio_server):
        """Test that config override 'enabled' forces hot-reload on."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test", command=["echo", "test"]),
            ],
            timeouts=TimeoutConfig(),
            hot_reload="enabled",
        )
        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Even known-broken clients should return True
        assert proxy._check_client_hot_reload_support("claude-code") is True
        assert proxy._check_client_hot_reload_support("cursor") is True
        assert proxy._check_client_hot_reload_support("unknown") is True

    def test_check_client_hot_reload_support_config_override_disabled(self, mock_stdio_server):
        """Test that config override 'disabled' forces hot-reload off."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test", command=["echo", "test"]),
            ],
            timeouts=TimeoutConfig(),
            hot_reload="disabled",
        )
        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Even known-working clients should return False
        assert proxy._check_client_hot_reload_support("github-copilot") is False
        assert proxy._check_client_hot_reload_support("unknown") is False

    def test_check_client_hot_reload_support_config_auto(self, mock_stdio_server):
        """Test that config 'auto' uses client detection."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="test", command=["echo", "test"]),
            ],
            timeouts=TimeoutConfig(),
            hot_reload="auto",
        )
        proxy = MCPProxy(config, stdio_server=mock_stdio_server)

        # Should use client detection
        assert proxy._check_client_hot_reload_support("github-copilot") is True
        assert proxy._check_client_hot_reload_support("claude-code") is False

    # --- Default State Tests ---

    def test_proxy_init_hot_reload_disabled_by_default(self, proxy):
        """Test that hot-reload is disabled by default before initialize."""
        assert proxy._hot_reload_enabled is False
        assert proxy._client_info is None

    # --- Initialize Tests ---

    @pytest.mark.asyncio
    async def test_handle_initialize_captures_client_info(self, proxy):
        """Test that initialize captures client info from request."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-1",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "test-client",
                    "version": "1.0.0",
                },
            },
        )

        with patch.object(proxy, "_broadcast_request", new_callable=AsyncMock) as mock_broadcast:
            mock_broadcast.return_value = MCPResponse(jsonrpc="2.0", id="init-1", result={})
            await proxy._handle_initialize(request)

        assert proxy._client_info == {"name": "test-client", "version": "1.0.0"}

    @pytest.mark.asyncio
    async def test_handle_initialize_enables_hot_reload_for_known_client(self, proxy):
        """Test that initialize enables hot-reload for known working clients."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-1",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "github-copilot",
                    "version": "1.0.0",
                },
            },
        )

        with patch.object(proxy, "_broadcast_request", new_callable=AsyncMock) as mock_broadcast:
            mock_broadcast.return_value = MCPResponse(jsonrpc="2.0", id="init-1", result={})
            await proxy._handle_initialize(request)

        assert proxy._hot_reload_enabled is True

    @pytest.mark.asyncio
    async def test_handle_initialize_disables_hot_reload_for_broken_client(self, proxy):
        """Test that initialize disables hot-reload for known broken clients."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-1",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "claude-code",
                    "version": "1.0.50",
                },
            },
        )

        with patch.object(proxy, "_broadcast_request", new_callable=AsyncMock) as mock_broadcast:
            mock_broadcast.return_value = MCPResponse(jsonrpc="2.0", id="init-1", result={})
            await proxy._handle_initialize(request)

        assert proxy._hot_reload_enabled is False

    @pytest.mark.asyncio
    async def test_handle_initialize_without_client_info(self, proxy):
        """Test initialize without clientInfo in params."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-1",
            params={
                "protocolVersion": "2024-11-05",
                "capabilities": {},
            },
        )

        with patch.object(proxy, "_broadcast_request", new_callable=AsyncMock) as mock_broadcast:
            mock_broadcast.return_value = MCPResponse(jsonrpc="2.0", id="init-1", result={})
            await proxy._handle_initialize(request)

        # Should use empty dict and get "unknown" as client name
        assert proxy._client_info == {}
        assert proxy._hot_reload_enabled is False

    @pytest.mark.asyncio
    async def test_handle_initialize_without_params(self, proxy):
        """Test initialize without params entirely."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="init-1",
            params=None,
        )

        with patch.object(proxy, "_broadcast_request", new_callable=AsyncMock) as mock_broadcast:
            mock_broadcast.return_value = MCPResponse(jsonrpc="2.0", id="init-1", result={})
            await proxy._handle_initialize(request)

        # Should remain at defaults
        assert proxy._client_info is None
        assert proxy._hot_reload_enabled is False

    # --- Hot-Reload Guard Tests ---

    @pytest.mark.asyncio
    async def test_check_and_reload_config_skipped_when_disabled(self, proxy):
        """Test that hot-reload check is skipped when client doesn't support it."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("proxy:\n  transport: stdio\n  upstreams:\n    - name: test\n      command: [echo, test]\n")
            config_path = Path(f.name)

        try:
            proxy._config_path = config_path
            proxy._config_mtime = config_path.stat().st_mtime - 1  # Older mtime to trigger change
            proxy._hot_reload_enabled = False  # Disabled

            with patch.object(proxy, "_apply_config_changes", new_callable=AsyncMock) as mock_apply:
                await proxy._check_and_reload_config()
                # Should NOT call _apply_config_changes because hot-reload is disabled
                mock_apply.assert_not_called()
        finally:
            config_path.unlink()

    @pytest.mark.asyncio
    async def test_check_and_reload_config_runs_when_enabled(self, proxy):
        """Test that hot-reload check runs when client supports it."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("proxy:\n  transport: stdio\n  upstreams:\n    - name: test\n      command: [echo, test]\n")
            config_path = Path(f.name)

        try:
            proxy._config_path = config_path
            proxy._config_mtime = config_path.stat().st_mtime - 1  # Older mtime to trigger change
            proxy._hot_reload_enabled = True  # Enabled

            with patch.object(proxy, "_apply_config_changes", new_callable=AsyncMock) as mock_apply:
                await proxy._check_and_reload_config()
                # Should call _apply_config_changes because hot-reload is enabled
                mock_apply.assert_called_once()
        finally:
            config_path.unlink()

    # --- Notification Guard Tests ---

    @pytest.mark.asyncio
    async def test_notify_capability_changes_skipped_when_disabled(self, proxy, mock_stdio_server):
        """Test that notifications are skipped when hot-reload is disabled."""
        proxy._stdio_server = mock_stdio_server
        proxy._hot_reload_enabled = False

        await proxy._notify_capability_changes()

        # Should NOT have sent any notifications
        assert len(mock_stdio_server.notifications_sent) == 0

    @pytest.mark.asyncio
    async def test_notify_capability_changes_sent_when_enabled(self, proxy, mock_stdio_server):
        """Test that notifications are sent when hot-reload is enabled."""
        proxy._stdio_server = mock_stdio_server
        proxy._hot_reload_enabled = True

        await proxy._notify_capability_changes()

        # Should have sent 3 notifications
        assert len(mock_stdio_server.notifications_sent) == 3
        methods = [n.method for n in mock_stdio_server.notifications_sent]
        assert "notifications/tools/list_changed" in methods
        assert "notifications/resources/list_changed" in methods
        assert "notifications/prompts/list_changed" in methods
