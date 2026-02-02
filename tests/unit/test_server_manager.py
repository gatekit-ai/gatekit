import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, patch
from gatekit.server_manager import ServerManager
from gatekit.config.models import UpstreamConfig


@pytest.fixture
def single_server_config():
    """Single server configuration for testing"""
    return [
        UpstreamConfig(
            name="filesystem",
            transport="stdio",
            command=["npx", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
    ]


@pytest.fixture
def multi_server_config():
    """Multi-server configuration for testing"""
    return [
        UpstreamConfig(
            name="fs",
            transport="stdio",
            command=["npx", "@modelcontextprotocol/server-filesystem", "/tmp"],
        ),
        UpstreamConfig(
            name="github",
            transport="stdio",
            command=["npx", "@modelcontextprotocol/server-github"],
        ),
    ]


@pytest.fixture
def mock_transport():
    """Mock transport for testing"""
    transport = Mock()
    transport.connect = AsyncMock()
    transport.send_request = AsyncMock()
    transport.send_notification = AsyncMock()
    transport.disconnect = AsyncMock()
    return transport


def test_server_manager_initialization(single_server_config):
    """Test ServerManager initialization with one server"""
    manager = ServerManager(single_server_config)

    assert len(manager.connections) == 1
    assert "filesystem" in manager.connections
    assert manager.connections["filesystem"].name == "filesystem"
    assert manager.connections["filesystem"].status == "disconnected"


def test_server_manager_multi_server_initialization(multi_server_config):
    """Test ServerManager initialization with multiple servers"""
    manager = ServerManager(multi_server_config)

    assert len(manager.connections) == 2
    assert "fs" in manager.connections
    assert "github" in manager.connections
    assert manager.connections["fs"].name == "fs"
    assert manager.connections["github"].name == "github"


@pytest.mark.asyncio
async def test_connect_all_success(single_server_config, mock_transport):
    """Test successful connection to all servers"""
    manager = ServerManager(single_server_config)

    # Mock the transport creation and responses
    from gatekit.protocol.messages import MCPResponse

    # Mock responses for initialize, tools/list, resources/list, prompts/list
    init_response = MCPResponse(
        jsonrpc="2.0", id=1, result={"capabilities": {"tools": {}}}
    )

    tools_response = MCPResponse(
        jsonrpc="2.0",
        id=2,
        result={"tools": [{"name": "read_file", "description": "Read file"}]},
    )

    resources_response = MCPResponse(jsonrpc="2.0", id=3, result={"resources": []})

    prompts_response = MCPResponse(jsonrpc="2.0", id=4, result={"prompts": []})

    # Configure mock to return different responses for different requests
    mock_transport.send_and_receive = AsyncMock(
        side_effect=[
            init_response,
            tools_response,
            resources_response,
            prompts_response,
        ]
    )

    with patch("gatekit.server_manager.StdioTransport", return_value=mock_transport):
        successful, failed = await manager.connect_all()

    assert successful == 1
    assert failed == 0
    assert manager.connections["filesystem"].status == "connected"
    # NOTE: ServerManager does not store capabilities - they are handled by the proxy layer


@pytest.mark.asyncio
async def test_connect_all_failure(single_server_config, mock_transport):
    """Test connection failure handling"""
    manager = ServerManager(single_server_config)

    # Mock transport to raise exception
    mock_transport.connect.side_effect = Exception("Connection failed")

    with patch("gatekit.server_manager.StdioTransport", return_value=mock_transport):
        successful, failed = await manager.connect_all()

    assert successful == 0
    assert failed == 1
    assert manager.connections["filesystem"].status == "disconnected"
    assert "Connection failed" in manager.connections["filesystem"].error


@pytest.mark.asyncio
async def test_reconnect_server_success(single_server_config, mock_transport):
    """Test successful server reconnection"""
    manager = ServerManager(single_server_config)

    # Initially failed connection
    manager.connections["filesystem"].status = "disconnected"
    manager.connections["filesystem"].error = "Previous error"

    # Mock successful reconnection
    from gatekit.protocol.messages import MCPResponse

    # Mock responses for initialize, tools/list, resources/list, prompts/list
    init_response = MCPResponse(
        jsonrpc="2.0", id=1, result={"capabilities": {"tools": {}}}
    )

    tools_response = MCPResponse(
        jsonrpc="2.0",
        id=2,
        result={"tools": [{"name": "read_file", "description": "Read file"}]},
    )

    resources_response = MCPResponse(jsonrpc="2.0", id=3, result={"resources": []})

    prompts_response = MCPResponse(jsonrpc="2.0", id=4, result={"prompts": []})

    # Configure mock to return different responses for different requests
    mock_transport.send_and_receive = AsyncMock(
        side_effect=[
            init_response,
            tools_response,
            resources_response,
            prompts_response,
        ]
    )

    with patch("gatekit.server_manager.StdioTransport", return_value=mock_transport):
        result = await manager.reconnect_server("filesystem")

    assert result is True
    assert manager.connections["filesystem"].status == "connected"
    assert manager.connections["filesystem"].error is None


@pytest.mark.asyncio
async def test_reconnect_nonexistent_server(single_server_config):
    """Test reconnection to non-existent server"""
    manager = ServerManager(single_server_config)

    result = await manager.reconnect_server("nonexistent")
    assert result is False


def test_get_connection(multi_server_config):
    """Test getting connection by server name"""
    manager = ServerManager(multi_server_config)

    fs_conn = manager.get_connection("fs")
    assert fs_conn is not None
    assert fs_conn.name == "fs"

    github_conn = manager.get_connection("github")
    assert github_conn is not None
    assert github_conn.name == "github"

    nonexistent_conn = manager.get_connection("nonexistent")
    assert nonexistent_conn is None


def test_extract_server_name_single_server(single_server_config):
    """Test server name extraction for one server"""
    manager = ServerManager(single_server_config)

    server_name, original_name = manager.extract_server_name("read_file")
    assert server_name is None
    assert original_name == "read_file"

    # With uniform architecture, __ always indicates server namespacing regardless of server count
    server_name, original_name = manager.extract_server_name("fs__read_file")
    assert server_name == "fs"
    assert original_name == "read_file"


def test_extract_server_name_multi_server(multi_server_config):
    """Test server name extraction for multiple servers"""
    manager = ServerManager(multi_server_config)

    server_name, original_name = manager.extract_server_name("fs__read_file")
    assert server_name == "fs"
    assert original_name == "read_file"

    server_name, original_name = manager.extract_server_name("github__create_issue")
    assert server_name == "github"
    assert original_name == "create_issue"

    # Name without separator should return None for server name
    server_name, original_name = manager.extract_server_name("simple_name")
    assert server_name is None
    assert original_name == "simple_name"


@pytest.mark.asyncio
async def test_disconnect_all(multi_server_config, mock_transport):
    """Test disconnecting from all servers"""
    manager = ServerManager(multi_server_config)

    # Set up connected servers
    manager.connections["fs"].transport = mock_transport
    manager.connections["fs"].status = "connected"
    manager.connections["github"].transport = mock_transport
    manager.connections["github"].status = "connected"

    await manager.disconnect_all()

    # Should have called disconnect on all transports
    assert mock_transport.disconnect.call_count == 2

    # All connections should be reset
    for conn in manager.connections.values():
        assert conn.transport is None
        assert conn.status == "disconnected"


@pytest.mark.asyncio
async def test_connect_server_invalid_transport(single_server_config):
    """Test connection with invalid transport type"""
    config = single_server_config[0]
    config.transport = "invalid"

    manager = ServerManager([config])

    successful, failed = await manager.connect_all()

    assert successful == 0
    assert failed == 1
    assert "not implemented" in manager.connections["filesystem"].error.lower()


@pytest.mark.asyncio
async def test_connect_server_invalid_response(single_server_config, mock_transport):
    """Test connection with invalid initialize response"""
    manager = ServerManager(single_server_config)

    # Mock invalid response (missing result)
    from gatekit.protocol.messages import MCPResponse

    mock_response = MCPResponse(
        jsonrpc="2.0", id=1, error={"code": -1, "message": "Invalid"}
    )
    mock_transport.send_and_receive = AsyncMock(return_value=mock_response)

    with patch("gatekit.server_manager.StdioTransport", return_value=mock_transport):
        successful, failed = await manager.connect_all()

    assert successful == 0
    assert failed == 1
    assert manager.connections["filesystem"].status == "disconnected"


class TestServerManagerTransportCreation:
    """Test ServerManager._create_transport method."""

    def test_create_stdio_transport(self, single_server_config):
        """Test creating a stdio transport."""
        manager = ServerManager(single_server_config)
        config = single_server_config[0]

        from gatekit.transport.stdio import StdioTransport

        transport = manager._create_transport(config)

        assert isinstance(transport, StdioTransport)
        assert transport.command == config.command

    def test_create_http_transport(self):
        """Test creating an HTTP transport."""
        http_config = UpstreamConfig(
            name="remote_api",
            transport="http",
            url="https://api.example.com/mcp",
        )
        manager = ServerManager([http_config])

        from gatekit.transport.http import StreamableHttpTransport

        transport = manager._create_transport(http_config)

        assert isinstance(transport, StreamableHttpTransport)
        assert transport.url == "https://api.example.com/mcp"
        assert transport._tls_verify is True

    def test_create_http_transport_with_tls_disabled(self):
        """Test creating an HTTP transport with TLS verification disabled."""
        http_config = UpstreamConfig(
            name="remote_api",
            transport="http",
            url="https://localhost:8443/mcp",
            tls_verify=False,
        )
        manager = ServerManager([http_config])

        from gatekit.transport.http import StreamableHttpTransport

        transport = manager._create_transport(http_config)

        assert isinstance(transport, StreamableHttpTransport)
        assert transport._tls_verify is False

    def test_create_transport_invalid_type(self):
        """Test that invalid transport type raises error."""
        # Create config with an invalid transport type
        # We have to bypass validation to create this for testing
        config = UpstreamConfig.create_draft("test")
        config.transport = "websocket"
        config.is_draft = False

        manager = ServerManager([config])

        with pytest.raises(NotImplementedError, match="websocket not implemented"):
            manager._create_transport(config)

    def test_create_stdio_transport_missing_command(self):
        """Test that stdio transport without command raises error."""
        # Create config with missing command (bypassing validation)
        config = UpstreamConfig.create_draft("test")
        config.transport = "stdio"
        config.is_draft = False  # Skip draft validation but we've set command=None

        manager = ServerManager([config])

        # The _create_transport method should validate this
        with pytest.raises(ValueError, match="stdio transport requires command"):
            manager._create_transport(config)

    def test_create_http_transport_missing_url(self):
        """Test that HTTP transport without URL raises error."""
        # Create config with missing URL (bypassing validation)
        config = UpstreamConfig.create_draft("test")
        config.transport = "http"
        config.is_draft = False  # Skip draft validation but we've set url=None

        manager = ServerManager([config])

        # The _create_transport method should validate this
        with pytest.raises(ValueError, match="http transport requires url"):
            manager._create_transport(config)


@pytest.mark.asyncio
async def test_connect_http_server(mock_transport):
    """Test connecting to an HTTP upstream server."""
    http_config = UpstreamConfig(
        name="remote_api",
        transport="http",
        url="https://api.example.com/mcp",
    )
    manager = ServerManager([http_config])

    from gatekit.protocol.messages import MCPResponse

    # Mock responses for initialize
    init_response = MCPResponse(
        jsonrpc="2.0",
        id=1,
        result={
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test-server", "version": "1.0.0"},
        },
    )

    mock_transport.send_and_receive = AsyncMock(return_value=init_response)

    with patch(
        "gatekit.server_manager.StreamableHttpTransport", return_value=mock_transport
    ):
        successful, failed = await manager.connect_all()

    assert successful == 1
    assert failed == 0
    assert manager.connections["remote_api"].status == "connected"
    assert manager.connections["remote_api"].server_identity == "test-server"


class TestServerManagerHotReload:
    """Test ServerManager hot-reload lifecycle methods."""

    @pytest.mark.asyncio
    async def test_add_server_new(self, mock_transport):
        """Test adding a new server dynamically."""
        manager = ServerManager([])
        assert len(manager.connections) == 0

        config = UpstreamConfig(
            name="new_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
            enabled=True,
        )

        # Don't connect (connect=False)
        result = await manager.add_server(config, connect=False)
        assert result is True
        assert "new_server" in manager.connections
        assert manager.connections["new_server"].status == "disconnected"

    @pytest.mark.asyncio
    async def test_add_server_already_exists(self):
        """Test adding a server that already exists returns False."""
        config = UpstreamConfig(
            name="existing",
            transport="stdio",
            command=["python", "-m", "test_server"],
        )
        manager = ServerManager([config])

        # Try to add the same server again
        result = await manager.add_server(config, connect=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_add_server_with_connect(self, mock_transport):
        """Test adding a server and connecting it."""
        from gatekit.protocol.messages import MCPResponse

        manager = ServerManager([])
        config = UpstreamConfig(
            name="new_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
            enabled=True,
        )

        init_response = MCPResponse(
            jsonrpc="2.0", id=1, result={"capabilities": {"tools": {}}}
        )
        mock_transport.send_and_receive = AsyncMock(return_value=init_response)

        with patch("gatekit.server_manager.StdioTransport", return_value=mock_transport):
            result = await manager.add_server(config, connect=True)

        assert result is True
        assert manager.connections["new_server"].status == "connected"

    @pytest.mark.asyncio
    async def test_add_server_disabled_no_connect(self, mock_transport):
        """Test adding a disabled server doesn't connect even with connect=True."""
        manager = ServerManager([])
        config = UpstreamConfig(
            name="disabled_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
            enabled=False,
        )

        # connect=True but server is disabled, so should not attempt connection
        result = await manager.add_server(config, connect=True)

        assert result is True
        assert "disabled_server" in manager.connections
        assert manager.connections["disabled_server"].status == "disconnected"
        # Transport should never have been created
        assert manager.connections["disabled_server"].transport is None

    @pytest.mark.asyncio
    async def test_remove_server(self, mock_transport):
        """Test removing a server disconnects and removes it."""
        config = UpstreamConfig(
            name="to_remove",
            transport="stdio",
            command=["python", "-m", "test_server"],
        )
        manager = ServerManager([config])
        manager.connections["to_remove"].transport = mock_transport
        manager.connections["to_remove"].status = "connected"

        await manager.remove_server("to_remove")

        assert "to_remove" not in manager.connections
        mock_transport.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_server(self):
        """Test removing a non-existent server is safe."""
        manager = ServerManager([])

        # Should not raise
        await manager.remove_server("nonexistent")

    @pytest.mark.asyncio
    async def test_disconnect_server(self, mock_transport):
        """Test disconnecting a server keeps it in connections."""
        config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
        )
        manager = ServerManager([config])
        manager.connections["test_server"].transport = mock_transport
        manager.connections["test_server"].status = "connected"

        await manager.disconnect_server("test_server")

        # Server should still be in connections but disconnected
        assert "test_server" in manager.connections
        assert manager.connections["test_server"].status == "disconnected"
        assert manager.connections["test_server"].transport is None
        mock_transport.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_server(self, mock_transport):
        """Test connecting a previously disconnected server."""
        from gatekit.protocol.messages import MCPResponse

        config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
        )
        manager = ServerManager([config])

        init_response = MCPResponse(
            jsonrpc="2.0", id=1, result={"capabilities": {"tools": {}}}
        )
        mock_transport.send_and_receive = AsyncMock(return_value=init_response)

        with patch("gatekit.server_manager.StdioTransport", return_value=mock_transport):
            result = await manager.connect_server("test_server")

        assert result is True
        assert manager.connections["test_server"].status == "connected"

    @pytest.mark.asyncio
    async def test_connect_nonexistent_server(self):
        """Test connecting a non-existent server returns False."""
        manager = ServerManager([])

        result = await manager.connect_server("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_server_no_reconnect_needed(self, mock_transport):
        """Test updating server config when reconnect is not needed."""
        config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
            enabled=True,
        )
        manager = ServerManager([config])
        manager.connections["test_server"].transport = mock_transport
        manager.connections["test_server"].status = "connected"

        # Update with same transport settings but different enabled state
        new_config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
            enabled=False,
        )

        result = await manager.update_server(new_config)

        assert result is True
        # Config should be updated
        assert manager.connections["test_server"].config.enabled is False
        # No disconnect should have happened (no reconnect needed)
        mock_transport.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_server_reconnect_needed(self, mock_transport):
        """Test updating server config when reconnect is needed."""
        from gatekit.protocol.messages import MCPResponse

        config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "old_server"],
        )
        manager = ServerManager([config])
        manager.connections["test_server"].transport = mock_transport
        manager.connections["test_server"].status = "connected"

        # Change command - requires reconnect
        new_config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "new_server"],
        )

        init_response = MCPResponse(
            jsonrpc="2.0", id=1, result={"capabilities": {"tools": {}}}
        )
        new_mock_transport = Mock()
        new_mock_transport.connect = AsyncMock()
        new_mock_transport.send_and_receive = AsyncMock(return_value=init_response)
        new_mock_transport.disconnect = AsyncMock()
        new_mock_transport.send_notification = AsyncMock()

        with patch(
            "gatekit.server_manager.StdioTransport", return_value=new_mock_transport
        ):
            result = await manager.update_server(new_config)

        assert result is True
        # Old transport should have been disconnected
        mock_transport.disconnect.assert_called_once()
        # New command should be in config
        assert manager.connections["test_server"].config.command == [
            "python",
            "-m",
            "new_server",
        ]

    @pytest.mark.asyncio
    async def test_update_nonexistent_server(self):
        """Test updating a non-existent server returns False."""
        manager = ServerManager([])
        config = UpstreamConfig(
            name="nonexistent",
            transport="stdio",
            command=["python", "-m", "test_server"],
        )

        result = await manager.update_server(config)
        assert result is False

    def test_needs_reconnect_transport_change(self):
        """Test _needs_reconnect detects transport changes."""
        old = UpstreamConfig(name="test", transport="stdio", command=["python"])
        new = UpstreamConfig(
            name="test", transport="http", url="https://example.com/mcp"
        )

        manager = ServerManager([])
        assert manager._needs_reconnect(old, new) is True

    def test_needs_reconnect_command_change(self):
        """Test _needs_reconnect detects command changes."""
        old = UpstreamConfig(name="test", transport="stdio", command=["python", "old.py"])
        new = UpstreamConfig(name="test", transport="stdio", command=["python", "new.py"])

        manager = ServerManager([])
        assert manager._needs_reconnect(old, new) is True

    def test_needs_reconnect_url_change(self):
        """Test _needs_reconnect detects URL changes."""
        old = UpstreamConfig(
            name="test", transport="http", url="https://old.example.com/mcp"
        )
        new = UpstreamConfig(
            name="test", transport="http", url="https://new.example.com/mcp"
        )

        manager = ServerManager([])
        assert manager._needs_reconnect(old, new) is True

    def test_needs_reconnect_tls_verify_change(self):
        """Test _needs_reconnect detects TLS verify changes."""
        old = UpstreamConfig(
            name="test", transport="http", url="https://example.com/mcp", tls_verify=True
        )
        new = UpstreamConfig(
            name="test", transport="http", url="https://example.com/mcp", tls_verify=False
        )

        manager = ServerManager([])
        assert manager._needs_reconnect(old, new) is True

    def test_needs_reconnect_no_change(self):
        """Test _needs_reconnect returns False when no relevant changes."""
        old = UpstreamConfig(
            name="test", transport="stdio", command=["python", "server.py"], enabled=True
        )
        new = UpstreamConfig(
            name="test", transport="stdio", command=["python", "server.py"], enabled=False
        )

        manager = ServerManager([])
        assert manager._needs_reconnect(old, new) is False

    @pytest.mark.asyncio
    async def test_reconnect_timeout_when_stuck_reconnecting(self):
        """Test that reconnect has a timeout when another reconnection is stuck."""
        from unittest.mock import patch

        config = UpstreamConfig(
            name="test_server",
            transport="stdio",
            command=["python", "-m", "test_server"],
            enabled=True,
        )
        manager = ServerManager([config])

        # Simulate a connection stuck in reconnecting state
        conn = manager.connections["test_server"]
        conn._reconnecting = True  # Stuck reconnecting

        # Make sleep instant to speed up test
        original_sleep = asyncio.sleep

        async def fast_sleep(delay):
            await original_sleep(0)

        with patch("gatekit.server_manager.asyncio.sleep", fast_sleep):
            # Should timeout and return False
            result = await manager._reconnect_server_internal("test_server")

        assert result is False
