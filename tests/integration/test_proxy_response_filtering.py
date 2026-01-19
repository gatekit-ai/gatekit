"""Integration tests for proxy response filtering functionality.

This module tests the complete proxy pipeline with tools/list response filtering.
"""

import pytest
from unittest.mock import AsyncMock, Mock
from gatekit.proxy.server import MCPProxy
from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.protocol.messages import MCPRequest, MCPResponse
from gatekit.transport.base import Transport
from gatekit.plugins.manager import PluginManager


class MockUpstreamTransport(Transport):
    """Mock upstream transport for testing."""

    def __init__(self, response_to_return=None):
        self.response_to_return = response_to_return
        self.sent_messages = []
        self._connected = False

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def send_message(self, message):
        self.sent_messages.append(message)

    async def send_notification(self, notification):
        self.sent_messages.append(notification)

    async def receive_message(self):
        return self.response_to_return

    async def send_and_receive(self, message):
        self.sent_messages.append(message)
        return self.response_to_return

    async def get_next_notification(self):
        # Mock implementation - not used in these tests
        import asyncio

        await asyncio.sleep(10)  # Hang forever since we don't expect notifications
        return None


class TestProxyResponseFiltering:
    """Test complete proxy pipeline with tools/list filtering."""

    def _create_proxy_with_tool_manager(self, tools=None, response_to_return=None):
        """Helper to create proxy with tool manager configuration."""
        # Create basic proxy config
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="filesystem", command=["python", "-m", "example_server"]
                )
            ],
            timeouts=TimeoutConfig(),
        )

        # Create plugin manager with tool manager configuration
        plugin_config = {
            "middleware": {
                "filesystem": [
                    {"handler": "tool_manager", "config": {"enabled": True}}
                ]
            }
        }

        normalized_tools = []
        if tools:
            for tool in tools:
                if isinstance(tool, str):
                    normalized_tools.append({"tool": tool})
                elif isinstance(tool, dict):
                    normalized_tools.append(tool)
                else:
                    raise TypeError(f"Unsupported tool config type: {type(tool)}")
        plugin_config["middleware"]["filesystem"][0]["config"][
            "tools"
        ] = normalized_tools

        plugin_manager = PluginManager(plugin_config)

        # Create mock upstream transport
        mock_transport = MockUpstreamTransport(response_to_return)

        # Create mock stdio server for testing
        class MockStdioServer:
            def __init__(self):
                self._running = False

            async def start(self):
                self._running = True

            async def stop(self):
                self._running = False

            def is_running(self):
                return self._running

            async def handle_messages(self, request_handler, notification_handler=None):
                pass

            async def write_notification(self, notification):
                pass

        mock_stdio_server = MockStdioServer()

        # Create mock server manager that uses our mock transport
        from gatekit.server_manager import ServerManager

        mock_server_manager = Mock(spec=ServerManager)
        mock_server_manager.connect_all = AsyncMock(return_value=(1, 0))
        mock_server_manager.disconnect_all = AsyncMock()
        mock_connection = Mock()
        mock_connection.status = "connected"
        mock_connection.transport = mock_transport
        mock_server_manager.get_connection = Mock(return_value=mock_connection)
        mock_server_manager.extract_server_name = Mock(
            return_value=("filesystem", "default")
        )
        # Mock the connections dict to simulate server with name "filesystem"
        mock_server_manager.connections = {"filesystem": mock_connection}

        # Create proxy with injected components
        return (
            MCPProxy(
                config,
                plugin_manager=plugin_manager,
                server_manager=mock_server_manager,
                stdio_server=mock_stdio_server,
            ),
            mock_transport,
        )

    @pytest.fixture
    def tools_list_response_multiple_tools(self):
        """Create a tools/list response with multiple tools."""
        return MCPResponse(
            jsonrpc="2.0",
            id="test-tools-list-1",
            result={
                "tools": [
                    {"name": "read_file", "description": "Read a file"},
                    {"name": "write_file", "description": "Write a file"},
                    {"name": "dangerous_tool", "description": "Dangerous operation"},
                    {"name": "create_directory", "description": "Create directory"},
                    {"name": "delete_everything", "description": "Delete all files"},
                ]
            },
        )

    @pytest.fixture
    def tools_list_request(self):
        """Create a tools/list request."""
        return MCPRequest(
            jsonrpc="2.0", method="tools/list", id="test-tools-list-1", params={}
        )

    @pytest.mark.asyncio
    async def test_proxy_end_to_end_tools_list_filtering_allowlist(
        self, tools_list_request, tools_list_response_multiple_tools
    ):
        """Test complete proxy pipeline with tools/list filtering in allowlist mode."""

        proxy, mock_transport = self._create_proxy_with_tool_manager(
            tools=["read_file", "write_file", "create_directory"],
            response_to_return=tools_list_response_multiple_tools,
        )

        await proxy.start()

        # Load plugins after proxy start
        await proxy._plugin_manager.load_plugins()

        try:
            # Send tools/list request through proxy
            response = await proxy.handle_request(tools_list_request)

            # Verify upstream was called
            assert len(mock_transport.sent_messages) == 1
            assert mock_transport.sent_messages[0].method == "tools/list"

            # Verify response was filtered
            assert response.result is not None
            filtered_tools = response.result["tools"]
            tool_names = [tool["name"] for tool in filtered_tools]

            # Should only contain allowed tools (with namespace prefix)
            assert set(tool_names) == {
                "filesystem__read_file",
                "filesystem__write_file",
                "filesystem__create_directory",
            }
            assert "dangerous_tool" not in tool_names
            assert "delete_everything" not in tool_names

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_proxy_end_to_end_tools_list_filters_unlisted(
        self, tools_list_request, tools_list_response_multiple_tools
    ):
        """Test pipeline hides tools that are not explicitly allowlisted."""

        proxy, mock_transport = self._create_proxy_with_tool_manager(
            tools=["read_file", "write_file", "create_directory"],
            response_to_return=tools_list_response_multiple_tools,
        )

        await proxy.start()

        # Load plugins after proxy start
        await proxy._plugin_manager.load_plugins()

        try:
            response = await proxy.handle_request(tools_list_request)

            # Verify response was filtered
            assert response.result is not None
            filtered_tools = response.result["tools"]
            tool_names = [tool["name"] for tool in filtered_tools]

            # Should contain only allowlisted tools (with namespace prefix)
            assert set(tool_names) == {
                "filesystem__read_file",
                "filesystem__write_file",
                "filesystem__create_directory",
            }
            assert "dangerous_tool" not in tool_names
            assert "delete_everything" not in tool_names

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_proxy_handles_malformed_tools_list_response(
        self, tools_list_request
    ):
        """Test proxy behavior when upstream returns malformed tools/list response."""

        # Create malformed response
        malformed_response = MCPResponse(
            jsonrpc="2.0", id="test-tools-list-1", result={}  # Missing tools field
        )

        proxy, mock_transport = self._create_proxy_with_tool_manager(
            tools=["read_file"], response_to_return=malformed_response
        )

        await proxy.start()

        # Load plugins after proxy start
        await proxy._plugin_manager.load_plugins()

        try:
            response = await proxy.handle_request(tools_list_request)

            # Verify response handles malformed upstream gracefully by returning empty tools list
            assert response.error is None
            assert response.result is not None
            assert response.result["tools"] == []

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_proxy_non_tools_list_requests_unchanged(self):
        """Test that non-tools/list requests pass through unchanged."""

        # Create tools/call request and response
        tools_call_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "filesystem__read_file"},
        )

        tools_call_response = MCPResponse(
            jsonrpc="2.0", id="test-1", result={"content": "file content"}
        )

        proxy, mock_transport = self._create_proxy_with_tool_manager(
            tools=["read_file"],  # Allow this tool
            response_to_return=tools_call_response,
        )

        await proxy.start()

        # Load plugins after proxy start
        await proxy._plugin_manager.load_plugins()

        try:
            response = await proxy.handle_request(tools_call_request)

            # Verify response content is preserved (now includes metadata for consistency)
            assert response.result["content"] == "file content"
            assert (
                "_gatekit_metadata" in response.result
            )  # Metadata is now always added
            assert not response.result["_gatekit_metadata"]["partial"]
            assert response.error is None

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_proxy_preserves_other_result_fields(self, tools_list_request):
        """Test that filtering preserves other fields in the result object."""

        # Create response with additional fields
        response_with_extra_fields = MCPResponse(
            jsonrpc="2.0",
            id="test-tools-list-1",
            result={
                "tools": [
                    {"name": "read_file", "description": "Read a file"},
                    {"name": "blocked_tool", "description": "This will be filtered"},
                ],
                "server_info": {"name": "test-server", "version": "1.0"},
                "custom_field": "custom_value",
            },
        )

        proxy, mock_transport = self._create_proxy_with_tool_manager(
            tools=["read_file"], response_to_return=response_with_extra_fields
        )

        await proxy.start()

        # Load plugins after proxy start
        await proxy._plugin_manager.load_plugins()

        try:
            response = await proxy.handle_request(tools_list_request)

            # Verify tools were filtered and namespaced correctly
            assert response.result is not None
            assert len(response.result["tools"]) == 1
            assert response.result["tools"][0]["name"] == "filesystem__read_file"

            # Note: Server-specific metadata fields are not preserved in aggregated responses

        finally:
            await proxy.stop()
