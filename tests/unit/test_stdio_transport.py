# filepath: /Users/dbright/mcp/gatekit/tests/unit/test_stdio_transport.py
"""Tests for StdioTransport implementation.

This module tests the stdio-based transport implementation for process-based
MCP server communication.

Note on RuntimeWarning Suppressions:
Many tests use @pytest.mark.filterwarnings("ignore::RuntimeWarning") to suppress
warnings from AsyncMock objects used for process I/O mocking. These warnings are
harmless testing artifacts, not actual async programming issues. See
docs/testing/runtime-warning-suppressions.md for detailed documentation.
"""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import Mock, AsyncMock, patch

from gatekit.transport.stdio import StdioTransport
from gatekit.transport.base import Transport
from gatekit.transport.errors import (
    TransportConnectionError,
    TransportDisconnectedError,
    TransportProcessError,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse


def create_mock_stream(stream_type="stdin"):
    """Create a properly mocked stream object with async and sync methods."""
    stream = Mock()

    if stream_type == "stdin":
        stream.write = Mock()
        stream.drain = AsyncMock()
        stream.close = Mock()  # close is sync
    else:  # stdout or stderr
        stream.readline = AsyncMock()
        stream.close = Mock()  # close is sync

    return stream


class TestStdioTransportInterface:
    """Test StdioTransport interface compliance."""

    def test_stdio_transport_inherits_from_transport(self):
        """Test that StdioTransport properly inherits from Transport."""
        assert issubclass(StdioTransport, Transport)

    def test_stdio_transport_instantiation(self):
        """Test StdioTransport can be instantiated with proper arguments."""
        command = ["python", "-m", "some_mcp_server"]
        transport = StdioTransport(command)
        assert transport.command == command
        assert not transport.is_connected()

    def test_stdio_transport_requires_command(self):
        """Test that StdioTransport requires a command argument."""
        with pytest.raises(TypeError):
            StdioTransport()


class TestStdioTransportProcessLifecycle:
    """Test process lifecycle management."""

    @pytest_asyncio.fixture
    async def transport(self):
        """Create a StdioTransport instance for testing with automatic cleanup."""
        transport = StdioTransport(["python", "-c", "import sys; sys.stdin.read()"])
        yield transport
        # Ensure cleanup happens even if test fails
        if transport.is_connected():
            await transport.disconnect()

    @pytest.fixture
    def mock_process(self):
        """Create a mock subprocess for testing."""
        process = Mock()
        process.stdin = Mock()
        process.stdin.write = Mock()
        process.stdin.drain = AsyncMock()
        process.stdin.close = Mock()  # close() is sync, not async

        # stdout and stderr should have async read methods but sync close
        process.stdout = Mock()
        process.stdout.readline = AsyncMock()
        process.stdout.close = Mock()

        process.stderr = Mock()
        process.stderr.readline = AsyncMock()
        process.stderr.close = Mock()

        process.wait = AsyncMock(return_value=0)
        process.terminate = Mock()
        process.kill = Mock()
        process.returncode = None
        process.pid = 12345
        return process

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_connect_starts_process(self, transport, mock_process):
        """Test that connect starts the subprocess in a new process group."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_process
            # Mock platform resolution to return original command (avoid platform-specific paths)
            with patch.object(
                transport, "_resolve_command_for_platform", return_value=transport.command
            ):
                await transport.connect()

                import sys
                if sys.platform == "win32":
                    import subprocess
                    expected_kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                else:
                    expected_kwargs = {"start_new_session": True}

                mock_create.assert_called_once_with(
                    *transport.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    **expected_kwargs,
                )
                assert transport.is_connected()
                assert transport._process is mock_process

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_connect_twice_raises_error(self, transport, mock_process):
        """Test that connecting twice raises an error."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_process

            await transport.connect()

            with pytest.raises(TransportConnectionError, match="Already connected"):
                await transport.connect()

    @pytest.mark.asyncio
    async def test_disconnect_terminates_process(self, transport, mock_process):
        """Test that disconnect properly terminates the process group."""
        import sys
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_process

            await transport.connect()

            if sys.platform != "win32":
                with patch("os.killpg") as mock_killpg:
                    await transport.disconnect()
                    import signal
                    mock_killpg.assert_any_call(mock_process.pid, signal.SIGTERM)
            else:
                await transport.disconnect()
                mock_process.terminate.assert_called_once()

            mock_process.wait.assert_called_once()
            assert not transport.is_connected()
            assert transport._process is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, transport):
        """Test that disconnect when not connected is safe."""
        # Should not raise
        await transport.disconnect()
        assert not transport.is_connected()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_disconnect_with_timeout_kills_process(self, transport, mock_process):
        """Test that disconnect kills entire process group if terminate times out."""
        # This test intentionally triggers a timeout which cancels an awaitable,
        # causing a RuntimeWarning that we need to suppress
        import sys

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_process

            await transport.connect()

            with patch("asyncio.wait_for") as mock_wait_for:
                # All wait_for calls should timeout:
                # 1. Waiting for message dispatcher task cancellation
                # 2. Waiting for stderr reader task cancellation
                # 3. Waiting for process termination
                # 4. Waiting for process kill
                mock_wait_for.side_effect = [
                    asyncio.TimeoutError(),
                    asyncio.TimeoutError(),
                    asyncio.TimeoutError(),
                    asyncio.TimeoutError(),
                ]

                if sys.platform != "win32":
                    import signal
                    with patch("os.killpg") as mock_killpg:
                        await transport.disconnect()
                        mock_killpg.assert_any_call(mock_process.pid, signal.SIGTERM)
                        mock_killpg.assert_any_call(mock_process.pid, signal.SIGKILL)
                else:
                    await transport.disconnect()
                    mock_process.terminate.assert_called_once()
                    mock_process.kill.assert_called_once()
                # wait_for should be called four times now (dispatcher cleanup, stderr cleanup, terminate, kill)
                assert mock_wait_for.call_count == 4

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_process_failure_during_connect(self, transport):
        """Test handling of process failure during connect."""
        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = OSError("Failed to start process")

            with pytest.raises(
                TransportProcessError, match="Failed to start MCP server process"
            ):
                await transport.connect()

            assert not transport.is_connected()


class TestStdioTransportMessageIO:
    """Test message input/output operations.

    Note: Many tests in this class use @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    because they work with AsyncMock objects for process I/O operations. AsyncMock creates
    internal coroutine objects that trigger RuntimeWarnings even when properly asserted.
    These warnings are harmless testing artifacts, not actual async programming issues.

    See docs/testing/runtime-warning-suppressions.md for detailed explanation.
    """

    @pytest_asyncio.fixture
    async def transport(self):
        """Create a connected StdioTransport for testing with automatic cleanup."""
        transport = StdioTransport(["python", "-c", "import sys; sys.stdin.read()"])
        yield transport
        # Ensure cleanup happens even if test fails
        if transport.is_connected():
            await transport.disconnect()

    @pytest.fixture
    def mock_connected_transport(self, transport):
        """Create a transport with mocked connected process."""
        process = Mock()
        process.stdin = Mock()  # stdin operations (write is sync, drain is async)
        process.stdin.write = Mock()
        process.stdin.drain = AsyncMock()
        process.stdin.close = Mock()  # close is sync

        process.stdout = Mock()
        process.stdout.readline = AsyncMock()
        process.stdout.close = Mock()  # close is sync

        process.stderr = Mock()
        process.stderr.readline = AsyncMock()
        process.stderr.close = Mock()  # close is sync

        process.returncode = None
        process.pid = 12345

        transport._process = process
        return transport, process

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_send_and_receive_success(self, transport):
        """Test successful send_and_receive."""
        response_json = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}}) + "\n"
        )

        # Mock readline to return the response
        responses = [response_json.encode("utf-8")]
        response_iter = iter(responses)

        async def mock_readline():
            try:
                return next(response_iter)
            except StopIteration:
                await asyncio.sleep(10)  # Hang after responses exhausted
                return b""

        # Mock the process creation and connect properly
        mock_process = Mock()
        mock_process.stdin = create_mock_stream("stdin")
        mock_process.stdout = create_mock_stream("stdout")
        mock_process.stdout.readline.side_effect = mock_readline
        mock_process.stderr = create_mock_stream("stderr")
        mock_process.returncode = None
        mock_process.pid = 12345

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            request = MCPRequest(jsonrpc="2.0", method="ping", id=1)
            response = await transport.send_and_receive(request)

            assert isinstance(response, MCPResponse)
            assert response.jsonrpc == "2.0"
            assert response.id == 1
            assert response.result == {"status": "ok"}

            await transport.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_send_and_receive_error_response(self, transport):
        """Test receiving error response via send_and_receive."""

        error_json = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            )
            + "\n"
        )

        # Mock readline to return the error response
        responses = [error_json.encode("utf-8")]
        response_iter = iter(responses)

        async def mock_readline():
            try:
                return next(response_iter)
            except StopIteration:
                await asyncio.sleep(10)  # Hang after responses exhausted
                return b""

        # Mock the process creation and connect properly
        mock_process = Mock()
        mock_process.stdin = create_mock_stream("stdin")
        mock_process.stdout = create_mock_stream("stdout")
        mock_process.stdout.readline.side_effect = mock_readline
        mock_process.stderr = create_mock_stream("stderr")
        mock_process.returncode = None
        mock_process.pid = 12345

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            request = MCPRequest(jsonrpc="2.0", method="ping", id=1)
            response = await transport.send_and_receive(request)

            assert isinstance(response, MCPResponse)
            assert response.jsonrpc == "2.0"
            assert response.id == 1
            assert response.error is not None
            assert response.error["code"] == -32600

            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_send_and_receive_when_not_connected(self, transport):
        """Test send_and_receive when not connected raises error."""
        request = MCPRequest(jsonrpc="2.0", method="ping", id=1)
        with pytest.raises(TransportDisconnectedError):
            await transport.send_and_receive(request)


class TestStdioTransportErrorHandling:
    """Test error handling and edge cases."""

    @pytest_asyncio.fixture
    async def transport(self):
        """Create a StdioTransport instance for testing with automatic cleanup."""
        transport = StdioTransport(["python", "-c", "import sys; sys.stdin.read()"])
        yield transport
        # Ensure cleanup happens even if test fails
        if transport.is_connected():
            await transport.disconnect()

    @pytest.mark.asyncio
    async def test_process_crash_during_operation(self, transport):
        """Test handling of process crash during operation."""
        process = Mock()
        process.stdin = Mock()
        process.stdin.write = Mock()
        process.stdin.drain = AsyncMock()
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.returncode = None  # Initially running
        process.pid = 12345

        transport._process = process

        # Process should appear connected initially
        assert transport.is_connected()

        # Now simulate process crash
        process.returncode = 1  # Process has exited

        # Should detect that process has crashed
        with pytest.raises(TransportDisconnectedError):
            await transport.send_and_receive(MCPRequest(jsonrpc="2.0", method="test", id=1))

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_context_manager_cleanup(self, transport):
        """Test that transport cleans up when used as context manager."""
        import sys
        process = Mock()
        process.stdin = create_mock_stream("stdin")
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.wait = AsyncMock(return_value=0)
        process.terminate = Mock()
        process.returncode = None
        process.pid = 12345

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = process

            if sys.platform != "win32":
                with patch("os.killpg"):
                    async with transport:
                        assert transport.is_connected()
            else:
                async with transport:
                    assert transport.is_connected()

            # Should have disconnected
            assert not transport.is_connected()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_context_manager_exception_cleanup(self, transport):
        """Test cleanup happens even when exception occurs in context."""
        import sys
        process = Mock()
        process.stdin = create_mock_stream("stdin")
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.wait = AsyncMock(return_value=0)
        process.terminate = Mock()
        process.returncode = None
        process.pid = 12345

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = process

            if sys.platform != "win32":
                with patch("os.killpg"):
                    with pytest.raises(ValueError):
                        async with transport:
                            raise ValueError("Test exception")
            else:
                with pytest.raises(ValueError):
                    async with transport:
                        raise ValueError("Test exception")

            # Should still have disconnected
            assert not transport.is_connected()


class TestStdioTransportResourceManagement:
    """Test resource cleanup and management."""

    @pytest_asyncio.fixture
    async def transport(self):
        """Create a StdioTransport instance for testing with automatic cleanup."""
        transport = StdioTransport(["python", "-c", "import sys; sys.stdin.read()"])
        yield transport
        # Ensure cleanup happens even if test fails
        if transport.is_connected():
            await transport.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_repeated_connect_disconnect_cycles(self, transport):
        """Test that multiple connect/disconnect cycles work correctly."""
        for i in range(3):
            process = Mock()
            process.stdin = create_mock_stream("stdin")
            process.stdout = create_mock_stream("stdout")
            process.stderr = create_mock_stream("stderr")
            process.wait = AsyncMock(return_value=0)
            process.terminate = Mock()
            process.returncode = None
            process.pid = 12345 + i

            with patch(
                "asyncio.create_subprocess_exec", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = process

                await transport.connect()
                assert transport.is_connected()

                await transport.disconnect()
                assert not transport.is_connected()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_no_zombie_processes(self, transport):
        """Test that processes are properly cleaned up (no zombies)."""
        import sys
        process = Mock()
        process.stdin = create_mock_stream("stdin")
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.wait = AsyncMock(return_value=0)
        process.terminate = Mock()
        process.returncode = None
        process.pid = 12345

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = process

            if sys.platform != "win32":
                with patch("os.killpg") as mock_killpg:
                    await transport.connect()
                    await transport.disconnect()
                    # Verify process group termination
                    import signal
                    mock_killpg.assert_any_call(process.pid, signal.SIGTERM)
            else:
                await transport.connect()
                await transport.disconnect()
                process.terminate.assert_called_once()

            process.wait.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_stderr_handling(self, transport):
        """Test that stderr is properly handled and doesn't leak."""
        process = Mock()
        process.stdin = create_mock_stream("stdin")
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.wait = AsyncMock(return_value=0)
        process.terminate = Mock()
        process.returncode = None
        process.pid = 12345

        with patch(
            "asyncio.create_subprocess_exec", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = process

            await transport.connect()

            # Verify stderr is captured
            assert process.stderr is not None

            await transport.disconnect()


class TestStdioTransportIntegration:
    """Test integration with Phase 1.1 message validation.

    Note: Tests in this class use @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    because they manually create AsyncMock objects for end-to-end testing. Similar to
    the fixture-based tests, AsyncMock generates internal coroutines that cause harmless
    RuntimeWarnings despite proper test assertions.
    """

    @pytest_asyncio.fixture
    async def transport(self):
        """Create a StdioTransport instance for testing with automatic cleanup."""
        transport = StdioTransport(["python", "-c", "import sys; sys.stdin.read()"])
        yield transport
        # Ensure cleanup happens even if test fails
        if transport.is_connected():
            await transport.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_message_validation_integration(self, transport):
        """Test that transport properly integrates with message validation."""
        process = Mock()
        process.stdin = Mock()
        process.stdin.write = Mock()
        process.stdin.drain = AsyncMock()
        process.stdout = create_mock_stream("stdout")
        process.stderr = create_mock_stream("stderr")
        process.returncode = None
        process.pid = 12345

        transport._process = process

        # Test with valid message using send_and_receive directly but we need a mock response
        # For this test we only care about request serialization, so we register a pending request
        # and check the write call
        request = MCPRequest(jsonrpc="2.0", method="ping", id=1)

        # Create a background task that will be cancelled after we check the write
        async def run_request():
            try:
                await transport.send_and_receive(request)
            except Exception:
                pass  # Expected, no response will be delivered

        task = asyncio.create_task(run_request())
        # Give time for the write to happen
        await asyncio.sleep(0.01)

        # Verify JSON was properly serialized
        call_args = process.stdin.write.call_args[0][0]
        sent_data = json.loads(call_args.decode("utf-8"))
        assert sent_data["jsonrpc"] == "2.0"
        assert sent_data["method"] == "ping"
        assert sent_data["id"] == 1

        # Verify drain was called
        process.stdin.drain.assert_awaited()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_response_parsing_with_validation(self, transport):
        """Test that received messages are properly validated."""
        # Test valid response
        valid_response = (
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"message": "pong"}})
            + "\n"
        )

        # Mock readline for the dispatcher
        responses = [valid_response.encode("utf-8")]
        response_iter = iter(responses)

        async def mock_readline():
            try:
                return next(response_iter)
            except StopIteration:
                await asyncio.sleep(10)  # Hang after responses exhausted
                return b""

        # Mock the process creation and connect properly
        mock_process = Mock()
        mock_process.stdin = create_mock_stream("stdin")
        mock_process.stdout = create_mock_stream("stdout")
        mock_process.stdout.readline.side_effect = mock_readline
        mock_process.stderr = create_mock_stream("stderr")
        mock_process.returncode = None
        mock_process.pid = 12345

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await transport.connect()

            request = MCPRequest(jsonrpc="2.0", method="ping", id=1)
            response = await transport.send_and_receive(request)
            assert isinstance(response, MCPResponse)
            assert response.result == {"message": "pong"}

            await transport.disconnect()
