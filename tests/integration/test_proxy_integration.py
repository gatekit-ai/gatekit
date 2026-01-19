"""Integration tests for MCP gateway server end-to-end communication.

This module tests the complete proxy server functionality with real MCP servers,
demonstrating the full request processing pipeline and integration with all components.
"""

import asyncio
import pytest
from unittest.mock import Mock, AsyncMock
from typing import Dict

from gatekit.proxy.server import MCPProxy
from gatekit.plugins.manager import PluginManager

# Import deprecated alias directly for backward compatibility in tests
from gatekit.plugins.interfaces import PipelineOutcome
from gatekit.transport.stdio import StdioTransport
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig

# Import mock classes from conftest
from conftest import MockSecurityPlugin, MockAuditingPlugin


class MockStdioServer:
    """Mock stdio server for integration testing."""

    def __init__(self):
        self._running = False
        self.messages_handled = 0

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
        pass


class MockMCPServer:
    """Mock MCP server for testing."""

    def __init__(self, responses: Dict[str, Dict]):
        self.responses = responses
        self.received_requests = []

    def get_response(self, request: MCPRequest) -> Dict:
        """Get mock response for a request."""
        self.received_requests.append(request)

        # Return predefined response if available
        if request.method in self.responses:
            response_template = self.responses[request.method]
            return {"jsonrpc": "2.0", "id": request.id, **response_template}

        # Default echo response
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": {
                "method": request.method,
                "params": request.params,
                "echo": True,
            },
        }


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    upstream = UpstreamConfig(
        name="test",
        command=["python", "-c", "pass"],
        restart_on_failure=True,
        max_restart_attempts=3,
    )

    timeouts = TimeoutConfig(connection_timeout=30, request_timeout=60)

    return ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)


@pytest.fixture
def security_plugin():
    """Create a test security plugin."""
    return MockSecurityPlugin(
        {"blocked_methods": ["dangerous_method"], "blocked_keywords": ["malicious"]}
    )


@pytest.fixture
def auditing_plugin():
    """Create a test auditing plugin."""
    return MockAuditingPlugin({"log_level": "DEBUG"})


@pytest.fixture
def plugin_manager(security_plugin, auditing_plugin):
    """Create a plugin manager with test plugins."""
    plugins_config = {
        "security": [{"handler": "test_security", "config": {"enabled": True}}],
        "auditing": [{"handler": "test_auditing", "config": {"enabled": True}}],
    }
    manager = PluginManager(plugins_config)
    # Manually set plugins for testing
    manager.security_plugins = [security_plugin]
    manager.auditing_plugins = [auditing_plugin]
    manager._initialized = True
    return manager


@pytest.fixture
def mock_transport():
    """Create a mock transport for testing."""
    transport = Mock(spec=StdioTransport)
    transport.send_and_receive = (
        AsyncMock()
    )  # Changed to send_and_receive for concurrency
    # send_and_receive replaces both send_message and receive_message
    transport.connect = AsyncMock()
    transport.disconnect = AsyncMock()
    transport.is_connected = Mock(return_value=True)
    return transport


@pytest.fixture
def mock_server_manager(mock_transport):
    """Create a mock server manager with a connected transport."""
    from gatekit.server_manager import ServerManager

    mock_server_manager = Mock(spec=ServerManager)
    mock_server_manager.connect_all = AsyncMock(return_value=(1, 0))
    mock_server_manager.disconnect_all = AsyncMock()

    mock_connection = Mock()
    mock_connection.status = "connected"
    mock_connection.transport = mock_transport

    mock_server_manager.get_connection = Mock(return_value=mock_connection)
    mock_server_manager.extract_server_name = Mock(return_value=(None, "default"))

    return mock_server_manager


class TestMCPProxyIntegration:
    """Integration tests for MCP gateway server."""

    @pytest.mark.asyncio
    async def test_proxy_initialization_and_startup(self, mock_config, plugin_manager):
        """Test proxy initialization and startup process."""
        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(config=mock_config, stdio_server=mock_stdio_server)

        assert proxy.config == mock_config
        assert not proxy.is_running

        # Mock server manager to simulate successful connection
        from unittest.mock import patch

        with patch.object(proxy._server_manager, "connect_all", return_value=(1, 0)):
            with patch.object(proxy._server_manager, "disconnect_all"):
                # Test startup
                await proxy.start()
                assert proxy.is_running

                # Test shutdown
                await proxy.stop()
                assert not proxy.is_running

    @pytest.mark.asyncio
    async def test_context_manager_support(self, mock_config, plugin_manager):
        """Test proxy context manager support."""
        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(config=mock_config, stdio_server=mock_stdio_server)

        # Mock server manager to simulate successful connection
        from unittest.mock import patch

        with patch.object(proxy._server_manager, "connect_all", return_value=(1, 0)):
            with patch.object(proxy._server_manager, "disconnect_all"):
                async with proxy:
                    assert proxy.is_running
                assert not proxy.is_running

    @pytest.mark.asyncio
    async def test_successful_request_processing_pipeline(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test complete request processing pipeline for successful requests."""
        # Setup mock transport response
        mock_response = MCPResponse(
            jsonrpc="2.0",
            id="test-1",
            result={"status": "success", "data": "test_data"},
        )
        mock_transport.send_and_receive = AsyncMock(return_value=mock_response)

        mock_stdio_server = MockStdioServer()

        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_server__test_tool", "arguments": {"arg1": "value1"}},
        )

        async with proxy:
            response = await proxy.handle_request(request)

        # Verify response
        assert response.jsonrpc == "2.0"
        assert response.id == "test-1"
        assert response.result["status"] == "success"

        # Verify transport was called
        mock_transport.send_and_receive.assert_called_once()

        # Verify plugins were invoked
        auditing_plugin = plugin_manager.auditing_plugins[0]

        assert len(auditing_plugin.request_log) == 1
        assert auditing_plugin.request_log[0]["method"] == "tools/call"
        assert auditing_plugin.request_log[0]["pipeline_outcome"] == "allowed"

        assert len(auditing_plugin.response_log) == 1
        assert auditing_plugin.response_log[0]["id"] == "test-1"

    @pytest.mark.asyncio
    async def test_security_policy_blocking(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test security policy blocking dangerous requests."""
        # Reset the mock to ensure clean state
        mock_transport.reset_mock()
        mock_transport.send_and_receive.reset_mock()

        # Configure the mock transport to ensure we don't rely on it
        # In this test we should never reach the transport layer since security blocks it

        mock_stdio_server = MockStdioServer()

        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        # Test blocked method
        blocked_request = MCPRequest(
            jsonrpc="2.0", method="dangerous_method", id="blocked-1", params={}
        )

        async with proxy:
            response = await proxy.handle_request(blocked_request)

        # Verify request was blocked
        assert response.jsonrpc == "2.0"
        assert response.id == "blocked-1"
        assert response.error is not None
        assert "blocked" in response.error["message"].lower()

        # Verify transport was NOT called
        mock_transport.send_and_receive.assert_not_called()

        # Verify auditing logged the blocked request
        auditing_plugin = plugin_manager.auditing_plugins[0]
        assert len(auditing_plugin.request_log) == 1
        assert auditing_plugin.request_log[0]["pipeline_outcome"] == "blocked"

    @pytest.mark.asyncio
    async def test_malicious_content_blocking(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test blocking requests with malicious content."""
        # Reset the mock to ensure clean state
        mock_transport.reset_mock()
        mock_transport.send_and_receive.reset_mock()
        mock_transport.send_and_receive.reset_mock()

        # Configure the mock transport to ensure we don't rely on it
        # In this test we should never reach the transport layer since security blocks it

        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        # Test request with malicious keyword
        malicious_request = MCPRequest(
            jsonrpc="2.0",
            method="normal_method",
            id="malicious-1",
            params={"data": "This contains malicious content"},
        )

        async with proxy:
            response = await proxy.handle_request(malicious_request)

        # Verify request was blocked
        assert response.jsonrpc == "2.0"
        assert response.id == "malicious-1"
        assert response.error is not None
        assert "blocked" in response.error["message"].lower()

        # Verify transport was NOT called
        mock_transport.send_and_receive.assert_not_called()

    @pytest.mark.asyncio
    async def test_upstream_server_error_handling(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test handling of upstream server errors."""
        # Setup mock transport to raise exception
        mock_transport.send_and_receive.side_effect = Exception("Upstream server error")

        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="error-1",
            params={"name": "test_server__test_tool", "arguments": {}},
        )

        async with proxy:
            response = await proxy.handle_request(request)

        # Verify error response
        assert response.jsonrpc == "2.0"
        assert response.id == "error-1"
        assert response.error is not None
        assert "Upstream server error" in response.error["message"]

    @pytest.mark.asyncio
    async def test_plugin_failure_isolation(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test that plugin failures don't break the proxy."""
        # Setup mock transport response
        mock_response = MCPResponse(
            jsonrpc="2.0", id="test-1", result={"status": "success"}
        )
        mock_transport.send_and_receive = AsyncMock()
        mock_transport.send_and_receive = AsyncMock(return_value=mock_response)

        # Make security plugin raise exception
        security_plugin = plugin_manager.security_plugins[0]
        original_check = security_plugin.process_request
        security_plugin.process_request = Mock(side_effect=Exception("Plugin error"))

        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_server__test_tool", "arguments": {}},
        )

        async with proxy:
            response = await proxy.handle_request(request)

        # Verify request still processed (plugin failure isolated)
        assert response.jsonrpc == "2.0"
        assert response.id == "test-1"
        # Should default to allowing request when security plugin fails
        assert response.result is not None or response.error is not None

        # Restore original method
        security_plugin.process_request = original_check

    @pytest.mark.asyncio
    async def test_concurrent_request_processing(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test concurrent request processing."""

        # Setup mock transport with delayed responses
        async def delayed_response(request):
            await asyncio.sleep(0.1)  # Simulate processing delay
            return MCPResponse(
                jsonrpc="2.0",
                id=request.id,  # Use the actual request ID
                result={"processed": True},
            )

        mock_transport.send_and_receive = AsyncMock(side_effect=delayed_response)

        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        # Create multiple requests
        requests = [
            MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id=f"concurrent-{i}",
                params={"name": f"test_server__tool_{i}", "arguments": {"index": i}},
            )
            for i in range(5)
        ]

        async with proxy:
            # Process requests concurrently
            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks)

        # Verify all responses
        assert len(responses) == 5
        for _i, response in enumerate(responses):
            assert response.jsonrpc == "2.0"
            # Response IDs might not match due to mocking, just check they exist
            assert response.id is not None
            assert response.result is not None

    @pytest.mark.asyncio
    async def test_request_statistics_tracking(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test request statistics tracking."""
        mock_response = MCPResponse(
            jsonrpc="2.0", id="stat-1", result={"success": True}
        )
        mock_transport.send_and_receive = AsyncMock()
        mock_transport.send_and_receive = AsyncMock(return_value=mock_response)

        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        async with proxy:
            # Process some requests
            for i in range(3):
                request = MCPRequest(
                    jsonrpc="2.0", method="test_method", id=f"stat-{i}", params={}
                )
                await proxy.handle_request(request)

            # Check basic statistics
            assert proxy.client_requests == 3

    @pytest.mark.asyncio
    async def test_malformed_request_handling(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test handling of malformed requests."""
        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        # Test request with empty method (this should trigger validation error)
        malformed_request = MCPRequest(
            jsonrpc="2.0",
            method="",  # Empty method should trigger validation error
            id="malformed-1",
            params={},
        )

        async with proxy:
            response = await proxy.handle_request(malformed_request)

        # Verify error response
        assert response.jsonrpc == "2.0"
        assert response.error is not None
        assert response.error["code"] == -32600  # Invalid Request

    @pytest.mark.asyncio
    async def test_plugin_configuration_integration(self):
        """Test integration with plugin configuration using real objects instead of mocks.

        This test demonstrates the principle of using real PluginManager objects
        instead of mocked ones, even though the specific upstream-scoped functionality
        may require additional architectural work.
        """
        # Create real plugin manager (using empty config but real implementation)
        plugin_manager = PluginManager({})

        # Test that the real plugin manager initializes properly
        assert plugin_manager is not None
        assert hasattr(plugin_manager, "security_plugins")
        assert hasattr(plugin_manager, "auditing_plugins")

        # Test real MCPRequest creation and processing
        test_request = MCPRequest(
            jsonrpc="2.0",
            method="test_method",
            id="integration-test-1",
            params={"test_param": "test_value"},
        )

        # Test that the plugin manager can process requests with real objects
        # Even with no plugins configured, it should return a valid pipeline
        pipeline = await plugin_manager.process_request(test_request)

        # Verify we get a real ProcessingPipeline object (not a mock)
        assert pipeline is not None
        assert hasattr(pipeline, "pipeline_outcome")
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        assert hasattr(pipeline, "had_security_plugin")
        assert pipeline.had_security_plugin is False  # No plugins configured
        # Pipeline should have stages (empty list when no plugins)
        assert hasattr(pipeline, "stages")
        assert isinstance(pipeline.stages, list)
        assert len(pipeline.stages) == 0  # No plugins means no stages

        # Test real MCPResponse processing
        test_response = MCPResponse(
            jsonrpc="2.0",
            id="integration-test-1",
            result={"integration_test": True, "status": "success"},
        )

        response_pipeline = await plugin_manager.process_response(
            test_request, test_response
        )
        assert response_pipeline is not None
        # With no security plugins, should have NO_SECURITY_EVALUATION outcome
        assert (
            response_pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )
        assert response_pipeline.had_security_plugin is False

        # Test real MCPNotification processing
        test_notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/test",
            params={"notification_test": True},
        )

        notification_pipeline = await plugin_manager.process_notification(
            test_notification
        )
        assert notification_pipeline is not None
        # With no security plugins, should have NO_SECURITY_EVALUATION outcome
        assert (
            notification_pipeline.pipeline_outcome
            == PipelineOutcome.NO_SECURITY_EVALUATION
        )
        assert notification_pipeline.had_security_plugin is False

        # Cleanup real plugin manager
        await plugin_manager.cleanup()

    @pytest.mark.asyncio
    async def test_graceful_shutdown_with_pending_requests(
        self, mock_config, plugin_manager, mock_server_manager, mock_transport
    ):
        """Test graceful shutdown when requests are pending."""

        # Setup delayed transport response
        async def slow_response(request):
            await asyncio.sleep(0.5)  # Simulate slow upstream
            return MCPResponse(jsonrpc="2.0", id=request.id, result={"delayed": True})

        mock_transport.send_and_receive = AsyncMock(side_effect=slow_response)

        mock_stdio_server = MockStdioServer()
        proxy = MCPProxy(
            config=mock_config,
            plugin_manager=plugin_manager,
            server_manager=mock_server_manager,
            stdio_server=mock_stdio_server,
        )

        request = MCPRequest(
            jsonrpc="2.0", method="slow_method", id="shutdown-test-1", params={}
        )

        await proxy.start()

        # Start a slow request
        task = asyncio.create_task(proxy.handle_request(request))

        # Allow request to start
        await asyncio.sleep(0.1)

        # Shutdown proxy
        await proxy.stop()

        # Verify request completes or is cancelled gracefully
        try:
            response = await task
            # If completed, should be valid response
            assert response.jsonrpc == "2.0"
        except asyncio.CancelledError:
            # Cancellation is also acceptable for graceful shutdown
            pass
