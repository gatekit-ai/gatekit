"""Tests for StdioServer with cross-platform anyio-based I/O.

This module tests the stdio server functionality using anyio's cross-platform
file handling, which works on both Unix and Windows.
"""

import json
import pytest
import tempfile
import os

from gatekit.proxy.stdio_server import StdioServer
from gatekit.protocol.messages import MCPResponse, MCPNotification


class TestStdioServerInitialization:
    """Test StdioServer initialization and lifecycle."""

    @pytest.mark.asyncio
    async def test_start_and_stop_with_temp_files(self):
        """Test starting and stopping the server with temp files."""
        # Create temp files for stdin/stdout
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            # Open files for the server
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)

            # Test start
            await server.start()
            assert server.is_running()

            # Test stop
            await server.stop()
            assert not server.is_running()

            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_start_already_running_raises_error(self):
        """Test that starting an already running server raises error."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)

            await server.start()
            with pytest.raises(RuntimeError, match="already running"):
                await server.start()

            await server.stop()
            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_stop_not_running_is_safe(self):
        """Test that stopping a non-running server is safe."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)

            # Should not raise error
            await server.stop()
            assert not server.is_running()

            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)


class TestStdioServerMessageReading:
    """Test message reading functionality."""

    @pytest.mark.asyncio
    async def test_read_valid_request(self):
        """Test reading a valid JSON-RPC request."""
        request_data = {
            "jsonrpc": "2.0",
            "method": "test_method",
            "id": 1,
            "params": {"test": "value"},
        }

        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                # Write request to stdin file
                stdin_f.write(json.dumps(request_data) + "\n")
                stdin_f.flush()
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            # Open for reading
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
            await server.start()

            # Read the message
            message = await server.read_message()

            assert message is not None
            assert message.method == "test_method"
            assert message.id == 1
            assert message.params == {"test": "value"}

            await server.stop()
            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_read_notification(self):
        """Test reading a notification (no id)."""
        notification_data = {
            "jsonrpc": "2.0",
            "method": "test_notification",
            "params": {"test": "value"},
        }

        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_f.write(json.dumps(notification_data) + "\n")
                stdin_f.flush()
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
            await server.start()

            message = await server.read_message()

            # Should be a notification
            assert message is not None
            assert message.method == "test_notification"
            assert message.params == {"test": "value"}
            assert not hasattr(message, 'id') or message.id is None

            await server.stop()
            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_read_skips_empty_lines(self):
        """Test that empty lines are skipped."""
        request_data = {"jsonrpc": "2.0", "method": "test", "id": 1}

        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                # Write empty lines then a valid request
                stdin_f.write("\n\n")
                stdin_f.write(json.dumps(request_data) + "\n")
                stdin_f.flush()
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
            await server.start()

            message = await server.read_message()

            assert message is not None
            assert message.method == "test"
            assert message.id == 1

            await server.stop()
            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)


class TestStdioServerMessageWriting:
    """Test message writing functionality."""

    @pytest.mark.asyncio
    async def test_write_response(self):
        """Test writing a response."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
            await server.start()

            response = MCPResponse(
                jsonrpc="2.0",
                id=1,
                result={"status": "ok"},
            )
            await server.write_response(response)

            await server.stop()
            stdin_file.close()
            stdout_file.close()

            # Read what was written
            with open(stdout_name, 'r', encoding='utf-8') as f:
                content = f.read()

            response_data = json.loads(content.strip())
            assert response_data["jsonrpc"] == "2.0"
            assert response_data["id"] == 1
            assert response_data["result"]["status"] == "ok"
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_write_error_response(self):
        """Test writing an error response."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
            await server.start()

            response = MCPResponse(
                jsonrpc="2.0",
                id=1,
                error={"code": -32600, "message": "Invalid request"},
            )
            await server.write_response(response)

            await server.stop()
            stdin_file.close()
            stdout_file.close()

            with open(stdout_name, 'r', encoding='utf-8') as f:
                content = f.read()

            response_data = json.loads(content.strip())
            assert response_data["jsonrpc"] == "2.0"
            assert response_data["id"] == 1
            assert response_data["error"]["code"] == -32600
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_write_notification(self):
        """Test writing a notification."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
            await server.start()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="test_notification",
                params={"test": "value"},
            )
            await server.write_notification(notification)

            await server.stop()
            stdin_file.close()
            stdout_file.close()

            with open(stdout_name, 'r', encoding='utf-8') as f:
                content = f.read()

            notification_data = json.loads(content.strip())
            assert notification_data["jsonrpc"] == "2.0"
            assert notification_data["method"] == "test_notification"
            assert notification_data["params"]["test"] == "value"
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)


class TestStdioServerAsyncContextManager:
    """Test async context manager functionality."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using StdioServer as async context manager."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            async with StdioServer(
                stdin_file=stdin_file, stdout_file=stdout_file
            ) as server:
                assert server.is_running()

            # Should be stopped after exiting context
            assert not server.is_running()

            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)


class TestStdioServerRuntimeErrors:
    """Test runtime error handling."""

    @pytest.mark.asyncio
    async def test_read_message_not_running(self):
        """Test reading message when server not running."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)

            with pytest.raises(RuntimeError, match="not running"):
                await server.read_message()

            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)

    @pytest.mark.asyncio
    async def test_write_response_not_running(self):
        """Test writing response when server not running."""
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdin_f:
            with tempfile.NamedTemporaryFile(
                mode='w+', encoding='utf-8', delete=False
            ) as stdout_f:
                stdin_name = stdin_f.name
                stdout_name = stdout_f.name

        try:
            stdin_file = open(stdin_name, 'r', encoding='utf-8')
            stdout_file = open(stdout_name, 'w', encoding='utf-8')

            server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)

            response = MCPResponse(jsonrpc="2.0", id=1, result={"status": "ok"})

            with pytest.raises(RuntimeError, match="not running"):
                await server.write_response(response)

            stdin_file.close()
            stdout_file.close()
        finally:
            os.unlink(stdin_name)
            os.unlink(stdout_name)
