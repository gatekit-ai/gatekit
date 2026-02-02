"""Integration tests with real FastMCP HTTP server.

These tests start a real FastMCP server using the Streamable HTTP transport
and test Gatekit's StreamableHttpTransport against it.

The tests use a self-contained server that starts in a background thread
and shuts down automatically after tests complete.

All tests in this module are marked with @pytest.mark.slow and will only
run when the --run-slow flag is passed to pytest.
"""

import asyncio
import socket
import threading
import time

import pytest
import pytest_asyncio

# Check if FastMCP is available
try:
    from fastmcp import FastMCP
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False

from gatekit.transport.http import StreamableHttpTransport
from gatekit.protocol.messages import MCPRequest, MCPNotification


# Mark all tests in this module as slow
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not FASTMCP_AVAILABLE,
        reason="FastMCP not installed - run 'pip install fastmcp>=2.0.0' to enable these tests"
    ),
]


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def create_test_server() -> "FastMCP":
    """Create a simple test MCP server with basic tools."""
    mcp = FastMCP("gatekit-test-server")

    @mcp.tool
    def echo(message: str) -> str:
        """Echo back the message."""
        return f"Echo: {message}"

    @mcp.tool
    def add(a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b

    @mcp.tool
    def greet(name: str, greeting: str = "Hello") -> str:
        """Generate a greeting for someone."""
        return f"{greeting}, {name}!"

    return mcp


def wait_for_server(url: str, timeout: float = 10.0) -> bool:
    """Wait for the HTTP server to be ready.

    Args:
        url: The server URL to check
        timeout: Maximum time to wait in seconds

    Returns:
        True if server is ready, False if timeout
    """
    import httpx

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # Send an initialize request with proper MCP headers
            # FastMCP requires Accept header with both json and event-stream
            response = httpx.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "id": "health",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "clientInfo": {"name": "health-check", "version": "0.1.0"},
                        "capabilities": {}
                    }
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=2.0,
                follow_redirects=True,  # Handle 307 redirects
            )
            # Any response means server is up (including error responses)
            # 200 = success, 400 = bad request (server is running), 406 = accept issue
            if response.status_code in (200, 202, 400, 406):
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.1)

    return False


@pytest.fixture(scope="module")
def http_mcp_server():
    """Start a real FastMCP HTTP server for testing.

    This fixture starts the server in a background thread and waits
    for it to be ready before yielding the URL.

    Yields:
        str: The server URL (e.g., "http://127.0.0.1:18123/mcp/")
    """
    port = find_free_port()
    # FastMCP serves at /mcp/ with trailing slash
    url = f"http://127.0.0.1:{port}/mcp/"

    mcp = create_test_server()

    # Server startup flag
    server_error = None

    def run_server():
        nonlocal server_error
        try:
            # Run the server synchronously in this thread
            # FastMCP.run() is blocking
            mcp.run(
                transport="streamable-http",
                host="127.0.0.1",
                port=port,
            )
        except Exception as e:
            server_error = e

    # Start server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    if not wait_for_server(url, timeout=15.0):
        if server_error:
            pytest.fail(f"FastMCP server failed to start: {server_error}")
        pytest.fail(f"FastMCP server at {url} failed to start within timeout")

    yield url

    # Server thread is daemon, so it will be terminated when tests finish


async def initialize_mcp_session(transport: StreamableHttpTransport, request_id: str = "init") -> None:
    """Perform full MCP initialization sequence.

    This follows the MCP protocol:
    1. Send initialize request
    2. Receive initialize response
    3. Send notifications/initialized notification

    Args:
        transport: The connected transport
        request_id: Request ID for the initialize request
    """
    # Send initialize request
    init_request = MCPRequest(
        jsonrpc="2.0",
        method="initialize",
        id=request_id,
        params={
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "gatekit-test", "version": "0.1.0"},
            "capabilities": {}
        }
    )
    response = await transport.send_and_receive(init_request)
    assert response.result is not None, f"Initialize failed: {response.error}"

    # Send initialized notification to complete the handshake
    initialized = MCPNotification(
        jsonrpc="2.0",
        method="notifications/initialized",
        params={}
    )
    await transport.send_notification(initialized)


@pytest_asyncio.fixture
async def connected_transport(http_mcp_server):
    """Create a connected transport to the FastMCP server.

    Args:
        http_mcp_server: The server URL from the http_mcp_server fixture

    Yields:
        StreamableHttpTransport: Connected transport instance
    """
    transport = StreamableHttpTransport(
        url=http_mcp_server,
        request_timeout=30.0,
    )
    await transport.connect()

    try:
        yield transport
    finally:
        await transport.disconnect()


@pytest_asyncio.fixture
async def initialized_transport(http_mcp_server):
    """Create a fully initialized transport to the FastMCP server.

    This fixture connects and completes the MCP initialization handshake,
    so tests can immediately start making requests.

    Args:
        http_mcp_server: The server URL from the http_mcp_server fixture

    Yields:
        StreamableHttpTransport: Connected and initialized transport instance
    """
    transport = StreamableHttpTransport(
        url=http_mcp_server,
        request_timeout=30.0,
    )
    await transport.connect()
    await initialize_mcp_session(transport, "fixture-init")

    try:
        yield transport
    finally:
        await transport.disconnect()


# =============================================================================
# Basic Connectivity Tests
# =============================================================================


@pytest.mark.asyncio
async def test_connect_and_disconnect(http_mcp_server):
    """Test basic connect and disconnect to real FastMCP server."""
    transport = StreamableHttpTransport(url=http_mcp_server)

    # Initially not connected
    assert not transport.is_connected()

    # Connect
    await transport.connect()
    assert transport.is_connected()

    # Disconnect
    await transport.disconnect()
    assert not transport.is_connected()


@pytest.mark.asyncio
async def test_multiple_connect_disconnect_cycles(http_mcp_server):
    """Test multiple connect/disconnect cycles are safe."""
    transport = StreamableHttpTransport(url=http_mcp_server)

    for _ in range(3):
        await transport.connect()
        assert transport.is_connected()
        await transport.disconnect()
        assert not transport.is_connected()


# =============================================================================
# Initialize Tests
# =============================================================================


@pytest.mark.asyncio
async def test_initialize_request(connected_transport):
    """Test initialize request against real FastMCP server."""
    request = MCPRequest(
        jsonrpc="2.0",
        method="initialize",
        id="init-1",
        params={
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "gatekit-test", "version": "0.1.0"},
            "capabilities": {}
        }
    )

    response = await connected_transport.send_and_receive(request)

    assert response.id == "init-1"
    assert response.jsonrpc == "2.0"
    assert response.result is not None
    assert response.error is None
    assert "protocolVersion" in response.result


@pytest.mark.asyncio
async def test_initialized_notification(connected_transport):
    """Test sending initialized notification after initialize."""
    # First initialize
    init_request = MCPRequest(
        jsonrpc="2.0",
        method="initialize",
        id="init-notify-1",
        params={
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "gatekit-test", "version": "0.1.0"},
            "capabilities": {}
        }
    )

    await connected_transport.send_and_receive(init_request)

    # Send initialized notification
    from gatekit.protocol.messages import MCPNotification

    notification = MCPNotification(
        jsonrpc="2.0",
        method="notifications/initialized",
        params={}
    )

    # This should not raise an error
    await connected_transport.send_notification(notification)


# =============================================================================
# Tool Discovery Tests
# =============================================================================


@pytest.mark.asyncio
async def test_tools_list(initialized_transport):
    """Test tools/list request to discover available tools."""
    # Request tools list
    tools_request = MCPRequest(
        jsonrpc="2.0",
        method="tools/list",
        id="tools-list-1",
        params={}
    )

    response = await initialized_transport.send_and_receive(tools_request)

    assert response.id == "tools-list-1"
    assert response.result is not None
    assert "tools" in response.result
    assert isinstance(response.result["tools"], list)

    # Verify our test tools are present
    tool_names = [tool["name"] for tool in response.result["tools"]]
    assert "echo" in tool_names
    assert "add" in tool_names
    assert "greet" in tool_names


# =============================================================================
# Tool Call Tests
# =============================================================================


@pytest.mark.asyncio
async def test_tool_call_echo(initialized_transport):
    """Test calling the echo tool on real FastMCP server."""
    # Call echo tool
    tool_request = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="tool-echo-1",
        params={
            "name": "echo",
            "arguments": {"message": "Hello from Gatekit!"}
        }
    )

    response = await initialized_transport.send_and_receive(tool_request)

    assert response.id == "tool-echo-1"
    assert response.error is None
    assert response.result is not None

    # Check the tool result
    content = response.result.get("content", [])
    assert len(content) > 0
    # FastMCP returns content as text
    text_content = content[0].get("text", "")
    assert "Echo: Hello from Gatekit!" in text_content


@pytest.mark.asyncio
async def test_tool_call_add(initialized_transport):
    """Test calling the add tool on real FastMCP server."""
    # Call add tool
    tool_request = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="tool-add-1",
        params={
            "name": "add",
            "arguments": {"a": 5, "b": 3}
        }
    )

    response = await initialized_transport.send_and_receive(tool_request)

    assert response.id == "tool-add-1"
    assert response.error is None
    assert response.result is not None

    # Check the tool result
    content = response.result.get("content", [])
    assert len(content) > 0
    text_content = content[0].get("text", "")
    assert "8" in text_content


@pytest.mark.asyncio
async def test_tool_call_with_default_args(initialized_transport):
    """Test calling tool with default arguments."""
    # Call greet tool with default greeting
    tool_request = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="tool-greet-1",
        params={
            "name": "greet",
            "arguments": {"name": "World"}
        }
    )

    response = await initialized_transport.send_and_receive(tool_request)

    assert response.id == "tool-greet-1"
    assert response.error is None
    assert response.result is not None

    content = response.result.get("content", [])
    assert len(content) > 0
    text_content = content[0].get("text", "")
    assert "Hello, World!" in text_content


# =============================================================================
# Session Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_session_id_acquired(connected_transport):
    """Test that session ID is acquired from server."""
    # Before initialize, session may or may not be set
    assert connected_transport._session_id is None

    # Perform full initialization sequence
    await initialize_mcp_session(connected_transport, "init-session-1")

    # FastMCP provides session IDs - verify we have one
    assert connected_transport._session_id is not None

    session_after_init = connected_transport._session_id

    # Send another request to verify session is maintained
    tools_request = MCPRequest(
        jsonrpc="2.0",
        method="tools/list",
        id="session-tools-1",
        params={}
    )

    response = await connected_transport.send_and_receive(tools_request)
    assert response.result is not None

    # Session should remain consistent
    assert connected_transport._session_id == session_after_init


@pytest.mark.asyncio
async def test_session_preserved_across_requests(initialized_transport):
    """Test that session state is preserved across multiple requests."""
    initial_session = initialized_transport._session_id
    assert initial_session is not None  # FastMCP provides session IDs

    # Send multiple requests
    for i in range(5):
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/list",
            id=f"session-preserve-{i}",
            params={}
        )

        response = await initialized_transport.send_and_receive(request)

        # Verify session ID hasn't changed
        assert initialized_transport._session_id == initial_session

        # Verify response is valid
        assert response.id == f"session-preserve-{i}"
        assert response.result is not None


# =============================================================================
# Concurrent Request Tests
# =============================================================================


@pytest.mark.asyncio
async def test_concurrent_requests(initialized_transport):
    """Test sending multiple concurrent requests to real server."""
    # Create concurrent tool calls
    num_requests = 5
    requests = [
        MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=f"concurrent-{i}",
            params={
                "name": "add",
                "arguments": {"a": i, "b": 10}
            }
        )
        for i in range(num_requests)
    ]

    # Send all requests concurrently
    tasks = [
        initialized_transport.send_and_receive(req)
        for req in requests
    ]

    responses = await asyncio.gather(*tasks)

    # Verify all completed
    assert len(responses) == num_requests

    # Check each response matches its request
    for i, response in enumerate(responses):
        assert response.id == f"concurrent-{i}"
        assert response.error is None
        assert response.result is not None


@pytest.mark.asyncio
async def test_concurrent_mixed_requests(initialized_transport):
    """Test concurrent requests with different methods."""
    # Create mixed requests
    requests = [
        MCPRequest(
            jsonrpc="2.0",
            method="tools/list",
            id="mixed-tools-1",
            params={}
        ),
        MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="mixed-echo-1",
            params={
                "name": "echo",
                "arguments": {"message": "test1"}
            }
        ),
        MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="mixed-add-1",
            params={
                "name": "add",
                "arguments": {"a": 1, "b": 2}
            }
        ),
    ]

    # Send concurrently
    tasks = [
        initialized_transport.send_and_receive(req)
        for req in requests
    ]

    responses = await asyncio.gather(*tasks)

    # Verify all completed with correct IDs
    response_ids = {r.id for r in responses}
    assert response_ids == {"mixed-tools-1", "mixed-echo-1", "mixed-add-1"}

    for response in responses:
        assert response.error is None
        assert response.result is not None


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
async def test_invalid_method_returns_error(initialized_transport):
    """Test that invalid method returns JSON-RPC error."""
    # Send invalid method request
    invalid_request = MCPRequest(
        jsonrpc="2.0",
        method="nonexistent/method",
        id="invalid-method-1",
        params={}
    )

    response = await initialized_transport.send_and_receive(invalid_request)

    assert response.id == "invalid-method-1"
    assert response.error is not None
    assert "code" in response.error
    assert "message" in response.error


@pytest.mark.asyncio
async def test_invalid_tool_name_returns_error(initialized_transport):
    """Test that calling non-existent tool returns error."""
    # Call non-existent tool
    tool_request = MCPRequest(
        jsonrpc="2.0",
        method="tools/call",
        id="invalid-tool-1",
        params={
            "name": "nonexistent_tool",
            "arguments": {}
        }
    )

    response = await initialized_transport.send_and_receive(tool_request)

    assert response.id == "invalid-tool-1"
    # Should get an error (either in error field or as isError in result)
    has_error = (
        response.error is not None or
        (response.result and response.result.get("isError", False))
    )
    assert has_error


# =============================================================================
# Metrics Tests
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_tracking(connected_transport):
    """Test that transport tracks request metrics."""
    # Get initial metrics
    initial_metrics = connected_transport.get_metrics()
    initial_sent = initial_metrics["requests_sent"]
    initial_completed = initial_metrics["requests_completed"]

    # Send a request
    request = MCPRequest(
        jsonrpc="2.0",
        method="initialize",
        id="metrics-test-1",
        params={
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "gatekit-test", "version": "0.1.0"},
            "capabilities": {}
        }
    )

    await connected_transport.send_and_receive(request)

    # Check metrics were updated
    updated_metrics = connected_transport.get_metrics()

    assert updated_metrics["requests_sent"] > initial_sent
    assert updated_metrics["requests_completed"] > initial_completed


# =============================================================================
# Context Manager Tests
# =============================================================================


@pytest.mark.asyncio
async def test_context_manager_usage(http_mcp_server):
    """Test using HTTP transport as async context manager."""
    async with StreamableHttpTransport(
        url=http_mcp_server,
        request_timeout=30.0,
    ) as transport:
        assert transport.is_connected()

        # Send a request
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="context-manager-1",
            params={
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "gatekit-test", "version": "0.1.0"},
                "capabilities": {}
            }
        )

        response = await transport.send_and_receive(request)
        assert response.result is not None

    # Should be disconnected after context exits
    assert not transport.is_connected()
