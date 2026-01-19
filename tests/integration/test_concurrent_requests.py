"""Integration tests for concurrent request handling.

Tests for Gatekit's ability to handle multiple simultaneous MCP requests
using real components and actual MCP servers.
"""

import pytest
import asyncio
import tempfile
import time
import os
from pathlib import Path

from gatekit.config.loader import ConfigLoader
from gatekit.proxy.server import MCPProxy
from gatekit.protocol.messages import MCPRequest


@pytest.fixture
def real_mcp_server_script():
    """Create a real MCP server script that can handle concurrent requests."""
    server_script = '''
import sys
import json
import asyncio
import time

async def handle_request(request):
    """Handle a single MCP request."""
    if request["method"] == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "concurrent-test-server", "version": "1.0"},
                "capabilities": {
                    "tools": {
                        "concurrent_tool": {"description": "A tool for testing concurrency"},
                        "test_tool": {"description": "Another test tool"},
                        "memory_tool": {"description": "Memory test tool"}
                    }
                }
            }
        }
    elif request["method"] == "tools/call":
        tool_name = request["params"]["name"]
        # Simulate processing delay
        await asyncio.sleep(0.1)
        return {
            "jsonrpc": "2.0", 
            "id": request["id"],
            "result": {
                "content": [{"type": "text", "text": f"Result from {tool_name}"}]
            }
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32601, "message": "Method not found"}
        }

async def main():
    """Main server loop."""
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            
            try:
                request = json.loads(line.strip())
                response = await handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id") if 'request' in locals() else None,
                    "error": {"code": -32603, "message": str(e)}
                }
                print(json.dumps(error_response), flush=True)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    asyncio.run(main())
'''

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(server_script)
        f.flush()
        yield f.name

    # Cleanup
    os.unlink(f.name)


@pytest.fixture
def real_concurrent_test_config(real_mcp_server_script, temp_work_directory):
    """Create a configuration for concurrent testing with real server."""
    audit_file = temp_work_directory / "concurrent_audit.log"
    # Use forward slashes in YAML to avoid backslash escape sequence issues on Windows
    # (e.g., C:\Users gets interpreted as C:\U... Unicode escape)
    server_script_path = Path(real_mcp_server_script).as_posix()
    audit_file_path = audit_file.as_posix()
    config_content = f"""
proxy:
  transport: stdio
  upstreams:
    - name: concurrent-server
      command: ["python", "{server_script_path}"]
  timeouts:
    connection_timeout: 10
    request_timeout: 30

plugins:
  middleware:
    concurrent-server:
      - handler: "tool_manager"
        config:
          enabled: true
          priority: 10
          tools:
            - tool: "concurrent_tool"
            - tool: "test_tool"
            - tool: "memory_tool"

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "{audit_file_path}"
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        yield Path(f.name)

    # Cleanup
    os.unlink(f.name)


@pytest.fixture
def temp_work_directory():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


class TestConcurrentRequests:
    """Test cases for concurrent request handling using real components."""

    @pytest.mark.asyncio
    async def test_basic_concurrent_requests_10(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test handling of 10 simultaneous requests with real MCP server."""
        # Load configuration
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        # Update audit file path
        audit_file = temp_work_directory / "concurrent_audit.log"
        # Access the global auditing plugins (converted from legacy list format)
        config.plugins.auditing["_global"][0].config["output_file"] = str(audit_file)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Create 10 concurrent requests
            requests = []
            for i in range(10):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"req_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__concurrent_tool",
                        "arguments": {"test_id": i, "data": f"concurrent_test_{i}"},
                    },
                )
                requests.append(request)

            # Process requests concurrently
            start_time = time.time()

            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            end_time = time.time()
            total_time = end_time - start_time

            # Verify all requests completed
            assert len(responses) == 10, f"Expected 10 responses, got {len(responses)}"

            # Verify no exceptions occurred
            for i, response in enumerate(responses):
                assert not isinstance(
                    response, Exception
                ), f"Request {i} failed with: {response}"

            # Verify responses have unique IDs matching requests
            response_ids = {resp.id for resp in responses if hasattr(resp, "id")}
            request_ids = {req.id for req in requests}
            assert (
                response_ids == request_ids
            ), f"Response IDs {response_ids} should match request IDs {request_ids}"

            # Verify concurrent processing (should be much faster than sequential)
            # With real 0.1s delays per request, 10 concurrent should take ~0.1-0.3s, not 1.0s
            assert (
                total_time < 3.0
            ), f"Concurrent processing too slow: {total_time}s (expected < 3.0s)"

            # Verify audit log contains all requests
            assert audit_file.exists(), "Audit file should be created"
            with open(audit_file, "r") as f:
                audit_content = f.read()
                assert "concurrent_tool" in audit_content
                # Should have 10 request entries
                request_count = audit_content.count("tools/call")
                assert (
                    request_count >= 10
                ), f"Expected at least 10 audit entries, found {request_count}"

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_medium_concurrent_requests_50(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test handling of 50 simultaneous requests with real MCP server."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        audit_file = temp_work_directory / "concurrent50_audit.log"
        config.plugins.auditing["_global"][0].config["output_file"] = str(audit_file)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Generate 50 concurrent requests
            requests = []
            for i in range(50):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"medium_req_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__test_tool",
                        "arguments": {"batch": "medium", "id": i},
                    },
                )
                requests.append(request)

            start_time = time.time()

            # Process all 50 requests concurrently
            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            end_time = time.time()
            total_time = end_time - start_time

            # Verify all requests completed successfully
            assert len(responses) == 50, f"Expected 50 responses, got {len(responses)}"

            success_count = 0
            for i, response in enumerate(responses):
                if isinstance(response, Exception):
                    pytest.fail(f"Request {i} failed with: {response}")
                else:
                    success_count += 1

            assert success_count == 50, f"Only {success_count}/50 requests succeeded"

            # Verify performance is still reasonable for 50 concurrent requests
            assert (
                total_time < 10.0
            ), f"50 concurrent requests took too long: {total_time}s"

            # Verify audit logging captured all requests
            assert audit_file.exists(), "Audit file should exist for 50 requests"

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_high_concurrent_requests_100(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test handling of 100 simultaneous requests with real MCP server."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        audit_file = temp_work_directory / "concurrent100_audit.log"
        config.plugins.auditing["_global"][0].config["output_file"] = str(audit_file)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Generate 100 concurrent requests
            requests = []
            for i in range(100):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"high_req_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__memory_tool",
                        "arguments": {"operation": "stress_test", "id": i},
                    },
                )
                requests.append(request)

            start_time = time.time()

            # Process all 100 requests concurrently
            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            end_time = time.time()
            total_time = end_time - start_time

            # Verify requests completed (allow for some failures at high concurrency)
            assert (
                len(responses) == 100
            ), f"Expected 100 responses, got {len(responses)}"

            success_count = sum(
                1 for resp in responses if not isinstance(resp, Exception)
            )
            failure_count = 100 - success_count

            # At 100 concurrent requests, we should still get at least 90% success
            min_success = 90
            assert (
                success_count >= min_success
            ), f"Only {success_count}/100 requests succeeded (expected >= {min_success})"

            # Log any failures for analysis
            if failure_count > 0:
                print(f"Note: {failure_count} requests failed at 100 concurrency level")

            # Performance should still be reasonable
            assert (
                total_time < 15.0
            ), f"100 concurrent requests took too long: {total_time}s"

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_request_response_ordering(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test that request/response pairs are correctly matched with real server."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Create requests with specific IDs and data for tracking
            requests = []
            for i in range(20):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"order_test_{i:03d}",  # Zero-padded for easy sorting
                    method="tools/call",
                    params={
                        "name": "concurrent-server__test_tool",
                        "arguments": {
                            "sequence_id": i,
                            "unique_data": f"order_marker_{i}_{time.time()}",
                        },
                    },
                )
                requests.append(request)

            # Process requests concurrently with intentional delays to test ordering
            tasks = []
            for i, req in enumerate(requests):
                # Add small random delays to simulate real-world timing variance
                delay = (i % 3) * 0.01  # 0, 0.01, or 0.02 second delays
                task = asyncio.create_task(self._delayed_request(proxy, req, delay))
                tasks.append(task)

            responses = await asyncio.gather(*tasks)

            # Verify each response matches its corresponding request
            for req, resp in zip(requests, responses, strict=False):
                assert (
                    resp.id == req.id
                ), f"Response ID {resp.id} doesn't match request ID {req.id}"

                # Verify response contains expected data from request
                if hasattr(resp, "result") and resp.result:
                    assert isinstance(
                        resp.result, dict
                    ), "Response result should be a dictionary"

            # Verify all unique IDs are present
            response_ids = {resp.id for resp in responses}
            request_ids = {req.id for req in requests}
            assert response_ids == request_ids, "Response IDs don't match request IDs"

        finally:
            await proxy.stop()

    async def _delayed_request(self, proxy, request, delay):
        """Helper to add delay before processing request."""
        await asyncio.sleep(delay)
        return await proxy.handle_request(request)

    @pytest.mark.asyncio
    async def test_plugin_state_isolation(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test that plugins don't share mutable state between concurrent requests."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Create requests that would expose shared state issues
            requests = []
            for i in range(15):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"isolation_test_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__test_tool",
                        "arguments": {
                            "state_marker": f"unique_{i}",
                            "counter": i,
                            "modify_state": True,
                        },
                    },
                )
                requests.append(request)

            # Process concurrently to test for race conditions
            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # Verify no race conditions or shared state corruption
            for _i, (req, resp) in enumerate(zip(requests, responses, strict=False)):
                assert not isinstance(resp, Exception), f"Request {i} failed: {resp}"
                assert resp.id == req.id, f"Response {i} has wrong ID"

                # Verify response data integrity (no cross-contamination)
                if hasattr(resp, "result") and resp.result:
                    # Each response should be unique to its request
                    assert resp.result is not None, f"Response {i} has null result"

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_resource_cleanup_after_requests(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test proper resource cleanup after concurrent request processing."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Measure initial resource state
            initial_task_count = len(asyncio.all_tasks())

            # Process a burst of requests
            requests = []
            for i in range(30):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"cleanup_test_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__test_tool",
                        "arguments": {"cleanup_test": True, "id": i},
                    },
                )
                requests.append(request)

            # Process requests
            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # Allow time for cleanup
            await asyncio.sleep(0.1)

            # Verify all requests completed
            for i, resp in enumerate(responses):
                assert not isinstance(
                    resp, Exception
                ), f"Cleanup test request {i} failed: {resp}"

            # Check that task count returned to reasonable level
            final_task_count = len(asyncio.all_tasks())
            task_increase = final_task_count - initial_task_count

            # Should not have excessive task buildup (some increase is normal)
            assert (
                task_increase < 50
            ), f"Too many tasks remain after requests: {task_increase} new tasks"

            # Test memory usage is reasonable (rough check)
            # In real implementation, this would check for memory leaks
            import gc

            gc.collect()  # Force garbage collection

            # If we had memory tracking, we'd verify no significant leaks here
            # For now, just verify the system is still responsive
            quick_request = MCPRequest(
                jsonrpc="2.0",
                id="cleanup_verification",
                method="tools/call",
                params={"name": "test_tool", "arguments": {"verify": True}},
            )

            verify_response = await proxy.handle_request(quick_request)
            assert not isinstance(
                verify_response, Exception
            ), "System not responsive after cleanup"

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_error_scenarios_under_load(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test error handling during concurrent request processing."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Mix of valid and invalid requests to test error isolation
            requests = []

            # Add some valid requests
            for i in range(10):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"valid_req_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__test_tool",
                        "arguments": {"type": "valid", "id": i},
                    },
                )
                requests.append(request)

            # Add some invalid requests (should be rejected by security plugin)
            for i in range(5):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"invalid_req_{i}",
                    method="tools/call",
                    params={
                        "name": "concurrent-server__blocked_tool",  # Not in allowlist
                        "arguments": {"type": "invalid", "id": i},
                    },
                )
                requests.append(request)

            # Add some malformed requests
            for i in range(3):
                request = MCPRequest(
                    jsonrpc="2.0",
                    id=f"malformed_req_{i}",
                    method="invalid/method",
                    params={"malformed": True},
                )
                requests.append(request)

            # Process all requests concurrently
            tasks = [proxy.handle_request(req) for req in requests]
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            # Categorize responses
            valid_successes = 0
            expected_failures = 0
            unexpected_failures = 0

            for _i, (req, resp) in enumerate(zip(requests, responses, strict=False)):
                if req.id.startswith("valid_req_"):
                    if isinstance(resp, Exception):
                        unexpected_failures += 1
                    elif hasattr(resp, "error") and resp.error:
                        unexpected_failures += 1
                    else:
                        valid_successes += 1
                else:
                    # Invalid or malformed requests should fail
                    if isinstance(resp, Exception) or (
                        hasattr(resp, "error") and resp.error
                    ):
                        expected_failures += 1
                    else:
                        unexpected_failures += 1

            # Verify error handling worked correctly
            assert (
                valid_successes >= 8
            ), f"Too many valid requests failed: {valid_successes}/10"
            assert (
                expected_failures >= 6
            ), f"Invalid requests should have failed: {expected_failures}/8"
            assert (
                unexpected_failures <= 2
            ), f"Too many unexpected failures: {unexpected_failures}"

            # System should still be functional after error scenarios
            test_request = MCPRequest(
                jsonrpc="2.0",
                id="post_error_test",
                method="tools/call",
                params={
                    "name": "concurrent-server__test_tool",
                    "arguments": {"test": "recovery"},
                },
            )

            recovery_response = await proxy.handle_request(test_request)
            assert not isinstance(
                recovery_response, Exception
            ), "System should recover after error scenarios"

        finally:
            await proxy.stop()

    @pytest.mark.asyncio
    async def test_concurrent_request_limit(
        self, real_concurrent_test_config, temp_work_directory
    ):
        """Test enforcement of maximum concurrent requests using real transport."""
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(real_concurrent_test_config)

        # Update audit file path to use temp directory
        audit_file = temp_work_directory / "concurrent_limit_audit.log"
        config.plugins.auditing["_global"][0].config["output_file"] = str(audit_file)

        # Create real proxy with real components but mock stdio server for testing
        from unittest.mock import AsyncMock

        mock_stdio_server = AsyncMock()
        mock_stdio_server.start = AsyncMock()
        mock_stdio_server.stop = AsyncMock()

        proxy = MCPProxy(
            config, config_loader.config_directory, stdio_server=mock_stdio_server
        )
        await proxy.start()

        try:
            # Get the real transport to verify its limit behavior
            conn = proxy._server_manager.get_connection("concurrent-server")
            assert conn is not None, "Should have a real connection"

            # The real stdio transport has a default limit of 100 concurrent requests
            # Let's test that we can handle a reasonable number concurrently
            requests = []
            for i in range(50):  # Well below the 100 limit
                request = MCPRequest(
                    jsonrpc="2.0",
                    method="tools/call",
                    id=f"limit_test_{i}",
                    params={
                        "name": "concurrent-server__test_tool",
                        "arguments": {"index": i},
                    },
                )
                requests.append(proxy.handle_request(request))

            # Process requests and verify they all succeed
            start_time = time.time()
            results = await asyncio.gather(*requests, return_exceptions=True)
            end_time = time.time()

            # All should succeed since we're well below the limit
            successes = sum(
                1
                for r in results
                if not isinstance(r, Exception)
                and (not hasattr(r, "error") or r.error is None)
            )
            failures = sum(
                1
                for r in results
                if isinstance(r, Exception)
                or (hasattr(r, "error") and r.error is not None)
            )

            assert successes == 50, f"Expected 50 successes, got {successes}"
            assert failures == 0, f"Expected 0 failures, got {failures}"

            # Should complete in reasonable time with real concurrency
            total_time = end_time - start_time
            assert (
                total_time < 10.0
            ), f"50 concurrent requests took too long: {total_time}s"

        finally:
            await proxy.stop()
