"""Integration tests for transport layer functionality.

This module tests the transport layer working with real subprocess communication,
demonstrating the complete stdio transport functionality.
"""

import asyncio
import pytest
import tempfile
import os

from gatekit.transport.stdio import StdioTransport
from gatekit.transport.errors import TransportProcessError, TransportDisconnectedError
from gatekit.protocol.messages import MCPRequest


class TestStdioTransportIntegration:
    """Integration tests for StdioTransport with real subprocesses."""

    @pytest.fixture
    def echo_server_script(self):
        """Create a temporary echo server script for testing."""
        script_content = """#!/usr/bin/env python3
import sys
import json

# Simple echo server that responds to MCP requests
for line in sys.stdin:
    try:
        request = json.loads(line.strip())
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {
                "echo": request.get("method", "unknown"),
                "params": request.get("params", {})
            }
        }
        print(json.dumps(response))
        sys.stdout.flush()
    except Exception as e:
        error_response = {
            "jsonrpc": "2.0", 
            "id": request.get("id") if 'request' in locals() else None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }
        print(json.dumps(error_response))
        sys.stdout.flush()
"""

        # Create temporary script file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script_content)
            script_path = f.name

        # Make it executable
        os.chmod(script_path, 0o755)

        yield script_path

        # Cleanup
        os.unlink(script_path)

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    async def test_basic_request_response(self, echo_server_script):
        """Test basic request-response communication with a real subprocess."""
        transport = StdioTransport(["python", echo_server_script])

        try:
            # Connect to the echo server
            await transport.connect()
            assert transport.is_connected()

            # Send a ping request
            request = MCPRequest(jsonrpc="2.0", method="ping", id=1)
            await transport.send_message(request)

            # Receive the response
            response = await transport.receive_message()

            assert response.jsonrpc == "2.0"
            assert response.id == 1
            assert response.result is not None
            assert response.result["echo"] == "ping"

        finally:
            await transport.disconnect()
            assert not transport.is_connected()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    async def test_request_with_parameters(self, echo_server_script):
        """Test request with parameters."""
        transport = StdioTransport(["python", echo_server_script])

        try:
            await transport.connect()

            # Send request with parameters
            request = MCPRequest(
                jsonrpc="2.0",
                method="test_method",
                id=2,
                params={"key": "value", "number": 42},
            )
            await transport.send_message(request)

            # Receive response
            response = await transport.receive_message()

            assert response.jsonrpc == "2.0"
            assert response.id == 2
            assert response.result["echo"] == "test_method"
            assert response.result["params"] == {"key": "value", "number": 42}

        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_multiple_request_response_cycles(self, echo_server_script):
        """Test multiple request-response cycles in sequence."""
        transport = StdioTransport(["python", echo_server_script])

        try:
            await transport.connect()

            # Send multiple requests
            for i in range(5):
                request = MCPRequest(jsonrpc="2.0", method=f"test_{i}", id=i + 100)
                await transport.send_message(request)

                response = await transport.receive_message()

                assert response.jsonrpc == "2.0"
                assert response.id == i + 100
                assert response.result["echo"] == f"test_{i}"

        finally:
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_context_manager_usage(self, echo_server_script):
        """Test using transport as an async context manager."""
        async with StdioTransport(["python", echo_server_script]) as transport:
            assert transport.is_connected()

            request = MCPRequest(jsonrpc="2.0", method="context_test", id=999)
            await transport.send_message(request)

            response = await transport.receive_message()
            assert response.result["echo"] == "context_test"

        # Transport should be disconnected after context exits
        assert not transport.is_connected()


@pytest.mark.asyncio
async def test_transport_error_handling():
    """Test transport error handling with invalid command."""
    transport = StdioTransport(["nonexistent_command"])

    with pytest.raises(
        TransportProcessError, match="Failed to start MCP server process"
    ):
        await transport.connect()

    assert not transport.is_connected()


@pytest.mark.asyncio
async def test_transport_with_failing_process():
    """Test transport with a process that exits immediately."""
    # Use a command that exits immediately
    transport = StdioTransport(["python", "-c", "exit(1)"])

    try:
        await transport.connect()

        # Try to send a message - should fail because process exited
        request = MCPRequest(jsonrpc="2.0", method="test", id=1)

        # Give the process a moment to exit
        await asyncio.sleep(0.2)

        with pytest.raises((TransportDisconnectedError, TransportProcessError)):
            await transport.send_message(request)

    finally:
        await transport.disconnect()
