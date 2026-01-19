"""Integration tests for race conditions and concurrent behavior.

These tests use real components to verify actual system behavior under
concurrent load and error conditions.
"""

import pytest
import asyncio
import time
import tempfile
import os

from gatekit.config.models import (
    UpstreamConfig,
    ProxyConfig,
    TimeoutConfig,
    PluginsConfig,
    LoggingConfig,
)
from gatekit.server_manager import ServerManager
from gatekit.proxy.server import MCPProxy
from gatekit.protocol.messages import MCPRequest


class TestRequestHandlingUnderFailure:
    """Test how requests are handled when servers fail or are unavailable."""

    @pytest.mark.asyncio
    async def test_request_behavior_during_server_failure(self):
        """Test how requests behave when a server fails to connect.

        Integration test using real components to verify actual behavior
        when servers are unavailable.
        """
        # Create a script that exits immediately (simulating a failed server)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import sys; sys.exit(1)")
            script_path = f.name

        try:
            # Use a real config with a server that will fail
            config = UpstreamConfig(
                name="failing-server",
                transport="stdio",
                command=["python", script_path],
            )

            # Create real server manager and try to connect
            server_manager = ServerManager([config])
            successful, failed = await server_manager.connect_all()

            # Should have failed to connect
            assert successful == 0
            assert failed == 1

            # Create real proxy
            proxy_config = ProxyConfig(
                transport="stdio",
                upstreams=[config],
                timeouts=TimeoutConfig(request_timeout=5),
                plugins=PluginsConfig(),
                logging=LoggingConfig(),
            )
            proxy = MCPProxy(proxy_config, server_manager=server_manager)

            # Create a real request
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="test-1",
                params={"name": "test-tool", "arguments": {}},
            )

            # Request should fail immediately since server is not connected
            start_time = time.time()

            # Create RoutedRequest for the new routing architecture
            from gatekit.core.routing import RoutedRequest

            # Route to the failing server
            routed = RoutedRequest(
                request, "failing-server", "failing-server__test-tool"
            )

            with pytest.raises(Exception) as exc_info:
                await proxy._route_request(routed)

            elapsed = time.time() - start_time

            # Should fail quickly (not timeout after 5 seconds)
            assert elapsed < 1.0, f"Request should fail quickly, took {elapsed}s"

            # Should fail with a meaningful error about server unavailability or no server specified
            error_msg = str(exc_info.value).lower()
            assert (
                "unavailable" in error_msg
                or "unknown" in error_msg
                or "no server" in error_msg
            )

        finally:
            # Cleanup
            os.unlink(script_path)
            await server_manager.disconnect_all()

    @pytest.mark.asyncio
    async def test_concurrent_requests_to_failed_server(self):
        """Test multiple concurrent requests to a failed server."""
        # Create a script that exits immediately
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import sys; sys.exit(1)")
            script_path = f.name

        try:
            config = UpstreamConfig(
                name="failing-server",
                transport="stdio",
                command=["python", script_path],
            )

            server_manager = ServerManager([config])
            await server_manager.connect_all()  # Will fail

            proxy_config = ProxyConfig(
                transport="stdio",
                upstreams=[config],
                timeouts=TimeoutConfig(request_timeout=5),
                plugins=PluginsConfig(),
                logging=LoggingConfig(),
            )
            proxy = MCPProxy(proxy_config, server_manager=server_manager)

            # Create multiple concurrent requests
            from gatekit.core.routing import RoutedRequest

            requests = []
            for i in range(5):
                request = MCPRequest(
                    jsonrpc="2.0",
                    method="tools/call",
                    id=f"concurrent-{i}",
                    params={"name": "test-tool", "arguments": {"index": i}},
                )
                routed = RoutedRequest(
                    request, "failing-server", "failing-server__test-tool"
                )
                requests.append(proxy._route_request(routed))

            # All should fail quickly
            start_time = time.time()
            results = await asyncio.gather(*requests, return_exceptions=True)
            elapsed = time.time() - start_time

            # Should fail quickly (not waiting for the full 5s request timeout)
            # Windows subprocess operations are slower, so allow more headroom
            assert (
                elapsed < 3.0
            ), f"Concurrent requests should fail quickly, took {elapsed}s"

            # All should be exceptions
            assert len(results) == 5
            for result in results:
                assert isinstance(result, Exception)
                error_msg = str(result).lower()
                assert (
                    "unavailable" in error_msg
                    or "unknown" in error_msg
                    or "no server" in error_msg
                )

        finally:
            os.unlink(script_path)
            await server_manager.disconnect_all()


class TestConcurrentConnectionManagement:
    """Test concurrent connection operations."""

    @pytest.mark.asyncio
    async def test_concurrent_reconnection_attempts(self):
        """Test multiple concurrent reconnection attempts to the same server."""
        # Create a script that runs briefly then exits
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import time; time.sleep(0.1)")
            script_path = f.name

        try:
            config = UpstreamConfig(
                name="test-server", transport="stdio", command=["python", script_path]
            )

            server_manager = ServerManager([config])

            # Try multiple concurrent reconnections
            tasks = []
            for _i in range(3):
                tasks.append(server_manager.reconnect_server("test-server"))

            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = time.time() - start_time

            # Should complete reasonably quickly
            assert elapsed < 5.0, f"Concurrent reconnections took too long: {elapsed}s"

            # Check results - some may succeed, some may fail, but no exceptions should occur
            for result in results:
                # Result should be boolean, not an exception
                assert isinstance(
                    result, bool
                ), f"Expected boolean result, got {type(result)}: {result}"

        finally:
            os.unlink(script_path)
            await server_manager.disconnect_all()

    @pytest.mark.asyncio
    async def test_connection_state_transitions(self):
        """Test that connection state transitions work correctly under concurrent access."""
        # Create a working echo server script
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                """
import sys
import json

# Handle multiple requests
while True:
    try:
        line = sys.stdin.readline()
        if not line:
            break
        req = json.loads(line)
        
        if req["method"] == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "test", "version": "1.0"},
                    "capabilities": {"tools": {}}
                }
            }
        elif req["method"] == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "tools": []
                }
            }
        elif req["method"] == "resources/list":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "resources": []
                }
            }
        elif req["method"] == "prompts/list":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "prompts": []
                }
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "error": {"code": -32601, "message": "Method not found"}
            }
        
        print(json.dumps(response))
        sys.stdout.flush()
        
    except Exception as e:
        # Exit on error
        break
"""
            )
            script_path = f.name

        try:
            config = UpstreamConfig(
                name="test-server", transport="stdio", command=["python", script_path]
            )

            server_manager = ServerManager([config])

            # Connect initially
            successful, failed = await server_manager.connect_all()
            assert successful == 1

            # Get the connection
            conn = server_manager.get_connection("test-server")
            assert conn is not None

            # Initial state should be connected
            assert conn.status == "connected"

            # Test concurrent state checks
            async def check_status():
                return conn.status

            # Multiple concurrent status checks should all return consistent values
            tasks = [check_status() for _ in range(10)]
            statuses = await asyncio.gather(*tasks)

            # All statuses should be the same
            unique_statuses = set(statuses)
            assert (
                len(unique_statuses) == 1
            ), f"Inconsistent statuses: {unique_statuses}"
            assert "connected" in unique_statuses

        finally:
            os.unlink(script_path)
            await server_manager.disconnect_all()


class TestServerManagerReconnection:
    """Test ServerManager reconnection behavior."""

    @pytest.mark.asyncio
    async def test_reconnection_with_valid_server(self):
        """Test reconnection to a server that can actually connect."""
        # Create a simple working MCP server
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(
                """
import sys
import json

try:
    # Handle multiple requests
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        req = json.loads(line)
        
        if req["method"] == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "test", "version": "1.0"},
                    "capabilities": {"tools": {}}
                }
            }
        elif req["method"] == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "tools": [{"name": "test_tool", "description": "Test tool"}]
                }
            }
        elif req["method"] == "resources/list":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "resources": []
                }
            }
        elif req["method"] == "prompts/list":
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "result": {
                    "prompts": []
                }
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": req["id"],
                "error": {"code": -32601, "message": "Method not found"}
            }
        
        print(json.dumps(response))
        sys.stdout.flush()
    
except Exception as e:
    sys.stderr.write(f"Error: {e}\\n")
    sys.exit(1)
"""
            )
            script_path = f.name

        try:
            config = UpstreamConfig(
                name="working-server",
                transport="stdio",
                command=["python", script_path],
            )

            server_manager = ServerManager([config])

            # Initial connection should succeed
            successful, failed = await server_manager.connect_all()
            assert successful == 1
            assert failed == 0

            conn = server_manager.get_connection("working-server")
            assert conn.status == "connected"

            # Disconnect to test reconnection
            await server_manager.disconnect_all()
            assert conn.status == "disconnected"

            # Reconnect should work
            result = await server_manager.reconnect_server("working-server")
            assert result
            assert conn.status == "connected"

        finally:
            os.unlink(script_path)
            await server_manager.disconnect_all()
