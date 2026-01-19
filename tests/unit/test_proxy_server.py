"""Unit tests for MCPProxy core proxy server implementation.

This module tests the central proxy server that integrates with plugins
and handles MCP client-server communication.
"""

import pytest
from unittest.mock import AsyncMock, patch

from gatekit.proxy.server import MCPProxy
from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.protocol.messages import MCPRequest, MCPResponse
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
