"""Unit tests for shared MCP handshake utilities."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gatekit.tui.utils.mcp_handshake import handshake_upstream, fetch_tools_list
from gatekit.transport.stdio import StdioTransport
from gatekit.protocol.messages import MCPResponse


@pytest.mark.asyncio
async def test_handshake_success_discovers_identity_and_tools():
    """Test successful handshake returns identity and tools payload."""
    # Mock command
    command = ["npx", "-y", "@modelcontextprotocol/server-everything"]

    # Mock initialize response with identity
    init_response = MCPResponse(
        jsonrpc="2.0",
        id="gatekit-handshake",
        result={
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "serverInfo": {
                "name": "test-server",
                "version": "1.0.0",
            },
        },
    )

    # Mock tools/list response
    tools_response = MCPResponse(
        jsonrpc="2.0",
        id="gatekit-tools-probe",
        result={
            "tools": [
                {"name": "tool1", "description": "Test tool 1"},
                {"name": "tool2", "description": "Test tool 2"},
            ],
        },
    )

    with patch.object(
        StdioTransport, "connect", new_callable=AsyncMock
    ) as mock_connect, patch.object(
        StdioTransport, "send_and_receive", new_callable=AsyncMock
    ) as mock_send, patch.object(
        StdioTransport, "send_notification", new_callable=AsyncMock
    ) as mock_send_notification, patch.object(
        StdioTransport, "disconnect", new_callable=AsyncMock
    ) as mock_disconnect:
        # Setup mock to return init response first, then tools response
        mock_send.side_effect = [init_response, tools_response]

        # Call handshake_upstream
        identity, tools_payload = await handshake_upstream(command, timeout=5.0)

        # Verify results
        assert identity == "test-server"
        assert tools_payload is not None
        assert tools_payload["status"] == "ok"
        assert len(tools_payload["tools"]) == 2
        assert tools_payload["tools"][0]["name"] == "tool1"

        # Verify transport lifecycle
        mock_connect.assert_called_once()
        assert mock_send.call_count == 2
        mock_disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handshake_timeout_returns_error_payload_with_stderr():
    """Test handshake timeout returns error payload with stderr for diagnostics."""
    command = ["npx", "-y", "@modelcontextprotocol/server-everything"]

    with patch.object(
        StdioTransport, "connect", new_callable=AsyncMock
    ) as mock_connect, patch.object(
        StdioTransport, "send_and_receive", new_callable=AsyncMock
    ) as mock_send, patch.object(
        StdioTransport, "get_stderr_output", return_value=["Need to install the following packages:", "Ok to proceed? (y)"]
    ), patch.object(
        StdioTransport, "disconnect", new_callable=AsyncMock
    ) as mock_disconnect:
        # Simulate timeout on initialize
        mock_send.side_effect = asyncio.TimeoutError()

        # Call handshake_upstream
        identity, tools_payload = await handshake_upstream(command, timeout=5.0)

        # Verify results - identity is None but we get an error payload with stderr
        assert identity is None
        assert tools_payload is not None
        assert tools_payload["status"] == "error"
        assert "Timeout after 5.0s" in tools_payload["message"]
        # Stderr should be included in the message for diagnostics
        assert "Need to install" in tools_payload["message"]

        # Verify transport lifecycle
        mock_connect.assert_called_once()
        mock_send.assert_called_once()
        mock_disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_handshake_process_error_produces_error_payload():
    """Test process errors produce user-friendly error messages."""
    command = ["nonexistent-command", "arg1"]

    with patch.object(
        StdioTransport, "connect", new_callable=AsyncMock
    ) as mock_connect, patch.object(
        StdioTransport, "disconnect", new_callable=AsyncMock
    ) as mock_disconnect:
        # Simulate "No such file or directory" error
        mock_connect.side_effect = OSError("[Errno 2] No such file or directory: 'nonexistent-command'")

        # Call handshake_upstream
        identity, tools_payload = await handshake_upstream(command, timeout=5.0)

        # Verify results
        assert identity is None
        assert tools_payload is not None
        assert tools_payload["status"] == "error"
        # Error message should be the raw OSError message (user-friendly rewriting happens in test_single_server)
        assert "No such file or directory" in tools_payload["message"]

        # Disconnect should still be called
        mock_disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_tools_list_handles_error_status():
    """Test fetch_tools_list handles errors gracefully."""
    # Create a connected mock transport
    mock_transport = MagicMock(spec=StdioTransport)
    mock_transport.send_and_receive = AsyncMock()

    # Simulate exception during send
    mock_transport.send_and_receive.side_effect = RuntimeError("Connection lost")

    # Call fetch_tools_list
    result = await fetch_tools_list(mock_transport, timeout=5.0)

    # Verify error payload
    assert result["status"] == "error"
    assert "tools/list failed" in result["message"]
    assert "Connection lost" in result["message"]
    assert result["tools"] == []


@pytest.mark.asyncio
async def test_fetch_tools_list_handles_empty_response():
    """Test fetch_tools_list handles empty responses."""
    mock_transport = MagicMock(spec=StdioTransport)
    mock_transport.send_and_receive = AsyncMock()

    # Simulate empty response
    mock_transport.send_and_receive.return_value = None

    # Call fetch_tools_list
    result = await fetch_tools_list(mock_transport, timeout=5.0)

    # Verify empty payload
    assert result["status"] == "empty"
    assert result["message"] == "tools/list returned no response."
    assert result["tools"] == []


@pytest.mark.asyncio
async def test_fetch_tools_list_handles_error_response():
    """Test fetch_tools_list handles JSON-RPC error responses."""
    mock_transport = MagicMock(spec=StdioTransport)
    mock_transport.send_and_receive = AsyncMock()

    # Simulate error response from server
    error_response = MCPResponse(
        jsonrpc="2.0",
        id="gatekit-tools-probe",
        error={"code": -32603, "message": "Cannot read properties of undefined"},
    )
    mock_transport.send_and_receive.return_value = error_response

    # Call fetch_tools_list
    result = await fetch_tools_list(mock_transport, timeout=5.0)

    # Verify error is properly reported
    assert result["status"] == "error"
    assert "tools/list error:" in result["message"]
    assert "Cannot read properties of undefined" in result["message"]
    assert result["tools"] == []


@pytest.mark.asyncio
async def test_fetch_tools_list_handles_invalid_response():
    """Test fetch_tools_list handles invalid response structure."""
    mock_transport = MagicMock(spec=StdioTransport)
    mock_transport.send_and_receive = AsyncMock()

    # Simulate response without 'tools' array
    invalid_response = MCPResponse(
        jsonrpc="2.0",
        id="gatekit-tools-probe",
        result={"invalid": "structure"},
    )
    mock_transport.send_and_receive.return_value = invalid_response

    # Call fetch_tools_list
    result = await fetch_tools_list(mock_transport, timeout=5.0)

    # Verify invalid payload
    assert result["status"] == "invalid"
    assert "missing 'tools' array" in result["message"]
    assert result["tools"] == []
