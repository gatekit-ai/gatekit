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
