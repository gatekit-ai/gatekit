"""Real TLS integration tests for HTTP transport.

These tests verify TLS configuration works end-to-end by:
1. Generating self-signed certificates
2. Starting a FastMCP server with HTTPS
3. Testing various TLS scenarios

All tests are marked @pytest.mark.slow.
"""

import asyncio
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

# Check if FastMCP is available
try:
    from fastmcp import FastMCP
    import uvicorn

    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False

from gatekit.transport.http import StreamableHttpTransport
from gatekit.transport.errors import HttpConnectionError
from gatekit.protocol.messages import MCPRequest, MCPNotification


def is_openssl_available() -> bool:
    """Check if openssl is available on the system."""
    try:
        subprocess.run(
            ["openssl", "version"], capture_output=True, check=True, timeout=10
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


# Mark all tests in this module as slow and skip if dependencies missing
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not FASTMCP_AVAILABLE,
        reason="FastMCP not installed - run 'pip install fastmcp>=2.0.0 uvicorn' to enable these tests",
    ),
    pytest.mark.skipif(
        not is_openssl_available(), reason="openssl not available on system"
    ),
]


def find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


def generate_self_signed_cert(cert_dir: Path) -> tuple[Path, Path]:
    """Generate a self-signed certificate for testing.

    Returns:
        Tuple of (cert_path, key_path)
    """
    cert_path = cert_dir / "server.crt"
    key_path = cert_dir / "server.key"

    # Use openssl to generate self-signed cert
    # Include subjectAltName for localhost and 127.0.0.1
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",  # No password
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )

    return cert_path, key_path


@pytest.fixture(scope="module")
def tls_certs(tmp_path_factory):
    """Generate self-signed certificates for TLS testing."""
    cert_dir = tmp_path_factory.mktemp("certs")
    cert_path, key_path = generate_self_signed_cert(cert_dir)
    return {"cert": cert_path, "key": key_path}


def create_tls_test_server() -> "FastMCP":
    """Create a simple test MCP server with basic tools for TLS testing."""
    mcp = FastMCP("tls-test-server")

    @mcp.tool
    def echo(message: str) -> str:
        """Echo back the message with TLS prefix."""
        return f"TLS Echo: {message}"

    @mcp.tool
    def add(a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b

    return mcp


def wait_for_https_server(url: str, timeout: float = 15.0) -> bool:
    """Wait for the HTTPS server to be ready.

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
            # Use verify=False just to check if server is up
            response = httpx.get(
                url.replace("/mcp", "/"),
                verify=False,
                timeout=2.0,
            )
            # Any response means server is up
            return True
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
            pass
        time.sleep(0.2)

    return False


@pytest.fixture(scope="module")
def https_server(tls_certs):
    """Start HTTPS MCP server with self-signed cert."""
    port = find_free_port()

    # Create server
    mcp = create_tls_test_server()

    # Get the ASGI app from FastMCP
    app = mcp.http_app()

    # Run with SSL
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        ssl_keyfile=str(tls_certs["key"]),
        ssl_certfile=str(tls_certs["cert"]),
        log_level="warning",
    )
    server = uvicorn.Server(config)

    # Start server in background thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # FastMCP serves at /mcp/ with trailing slash
    url = f"https://127.0.0.1:{port}/mcp/"

    # Wait for server to be ready
    if not wait_for_https_server(url, timeout=15.0):
        pytest.fail(f"HTTPS server at {url} failed to start within timeout")

    yield {
        "url": url,
        "port": port,
    }

    # Server thread is daemon, so it will be terminated when tests finish


async def initialize_mcp_session(
    transport: StreamableHttpTransport, request_id: str = "tls-init"
) -> None:
    """Perform full MCP initialization sequence.

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
            "clientInfo": {"name": "tls-test", "version": "0.1.0"},
            "capabilities": {},
        },
    )
    response = await transport.send_and_receive(init_request)
    assert response.result is not None, f"Initialize failed: {response.error}"

    # Send initialized notification to complete the handshake
    initialized = MCPNotification(
        jsonrpc="2.0", method="notifications/initialized", params={}
    )
    await transport.send_notification(initialized)


# =============================================================================
# TLS Verification Tests
# =============================================================================


@pytest.mark.asyncio
async def test_tls_verify_false_connects(https_server):
    """tls_verify=False allows connection to self-signed cert server."""
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Insecure but should work
    )

    await transport.connect()
    try:
        assert transport.is_connected()

        # Send a request to verify it works
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="tls-test-1",
            params={
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "tls-test", "version": "0.1"},
                "capabilities": {},
            },
        )
        response = await transport.send_and_receive(request)
        assert response.result is not None
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_verify_true_rejects_self_signed(https_server):
    """tls_verify=True (default) rejects self-signed certificates.

    Note: httpx/TLS verification happens when the first request is made,
    not at client creation time. So we need to attempt a request to trigger
    the TLS verification failure.
    """
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=True,  # Default - should reject self-signed
    )

    # Connect succeeds (just creates the client)
    await transport.connect()

    try:
        # But the first request should fail because cert isn't trusted
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="tls-reject-test",
            params={
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "tls-test", "version": "0.1"},
                "capabilities": {},
            },
        )

        with pytest.raises(HttpConnectionError) as exc_info:
            await transport.send_and_receive(request)

        # Error should mention certificate/SSL
        error_msg = str(exc_info.value).lower()
        assert any(
            term in error_msg for term in ["ssl", "certificate", "verify", "tls"]
        ), f"Expected SSL/certificate error, got: {exc_info.value}"
    finally:
        await transport.disconnect()


# =============================================================================
# Full Session Tests over TLS
# =============================================================================


@pytest.mark.asyncio
async def test_tls_full_initialization_sequence(https_server):
    """Full MCP initialization works over TLS."""
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Use insecure for self-signed cert testing
    )

    await transport.connect()
    try:
        # Perform full initialization
        await initialize_mcp_session(transport, "tls-init-full")

        # Session should be established
        assert transport._session_id is not None
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_tool_list_works(https_server):
    """Tool list request works over TLS."""
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Use insecure for self-signed cert testing
    )

    await transport.connect()
    try:
        # Initialize first
        await initialize_mcp_session(transport, "tls-tools-init")

        # Request tools list
        tools_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/list",
            id="tls-tools-list",
            params={},
        )

        response = await transport.send_and_receive(tools_request)

        assert response.id == "tls-tools-list"
        assert response.result is not None
        assert "tools" in response.result
        assert isinstance(response.result["tools"], list)

        # Verify our test tools are present
        tool_names = [tool["name"] for tool in response.result["tools"]]
        assert "echo" in tool_names
        assert "add" in tool_names
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_tool_call_works(https_server):
    """Full tool call works over TLS."""
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Use insecure for self-signed cert testing
    )

    await transport.connect()
    try:
        # Initialize
        await initialize_mcp_session(transport, "tls-tool-init")

        # Call tool
        tool_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="tls-tool-1",
            params={"name": "echo", "arguments": {"message": "Hello TLS!"}},
        )
        response = await transport.send_and_receive(tool_request)

        # Verify tool was called successfully
        assert response.id == "tls-tool-1"
        assert response.error is None
        assert response.result is not None

        # Check the tool result contains our message
        content = response.result.get("content", [])
        assert len(content) > 0
        text_content = content[0].get("text", "")
        assert "TLS Echo: Hello TLS!" in text_content
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_concurrent_requests(https_server):
    """Concurrent requests work correctly over TLS."""
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Use insecure for self-signed cert testing
    )

    await transport.connect()
    try:
        # Initialize
        await initialize_mcp_session(transport, "tls-concurrent-init")

        # Create concurrent tool calls
        num_requests = 5
        requests = [
            MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id=f"tls-concurrent-{i}",
                params={"name": "add", "arguments": {"a": i, "b": 10}},
            )
            for i in range(num_requests)
        ]

        # Send all requests concurrently
        tasks = [transport.send_and_receive(req) for req in requests]

        responses = await asyncio.gather(*tasks)

        # Verify all completed
        assert len(responses) == num_requests

        # Check each response matches its request
        for i, response in enumerate(responses):
            assert response.id == f"tls-concurrent-{i}"
            assert response.error is None
            assert response.result is not None
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_verify_false_logs_warning(https_server, caplog):
    """Verify that tls_verify=False logs a security warning."""
    import logging

    caplog.set_level(logging.WARNING)

    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,
    )

    await transport.connect()
    try:
        # Should have logged a warning about insecurity
        warning_found = any(
            "tls verification disabled" in record.message.lower()
            or "insecure" in record.message.lower()
            for record in caplog.records
        )
        assert warning_found, (
            "Expected warning about TLS verification disabled. "
            f"Log records: {[r.message for r in caplog.records]}"
        )
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_session_preserved_across_requests(https_server):
    """Session state is preserved across multiple TLS requests."""
    transport = StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Use insecure for self-signed cert testing
    )

    await transport.connect()
    try:
        # Initialize
        await initialize_mcp_session(transport, "tls-session-init")

        initial_session = transport._session_id
        assert initial_session is not None

        # Send multiple requests
        for i in range(3):
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/list",
                id=f"tls-session-{i}",
                params={},
            )

            response = await transport.send_and_receive(request)

            # Verify session ID hasn't changed
            assert transport._session_id == initial_session

            # Verify response is valid
            assert response.id == f"tls-session-{i}"
            assert response.result is not None
    finally:
        await transport.disconnect()


@pytest.mark.asyncio
async def test_tls_context_manager_usage(https_server):
    """Test using HTTP transport as async context manager with TLS."""
    async with StreamableHttpTransport(
        url=https_server["url"],
        tls_verify=False,  # Use insecure for self-signed cert testing
        request_timeout=30.0,
    ) as transport:
        assert transport.is_connected()

        # Send a request
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="tls-context-manager-1",
            params={
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "tls-test", "version": "0.1.0"},
                "capabilities": {},
            },
        )

        response = await transport.send_and_receive(request)
        assert response.result is not None

    # Should be disconnected after context exits
    assert not transport.is_connected()
