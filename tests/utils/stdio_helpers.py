"""Utilities for testing stdio-based components with cross-platform support.

This module provides helper functions to create test environments for
stdio components that work on both Unix and Windows.

The implementation uses anyio.wrap_file() with StringIO/file objects,
matching the approach used in the production StdioServer code.
"""

import json
import tempfile
from contextlib import asynccontextmanager
from io import StringIO
from typing import Optional

import anyio


class MockTextFile:
    """A text file-like object backed by StringIO for testing.

    This provides a file interface that can be used with anyio.wrap_file()
    for cross-platform async I/O testing.
    """

    def __init__(self, initial_content: str = ""):
        self._buffer = StringIO(initial_content)
        # Track if we've been closed
        self._closed = False

    def read(self, n: int = -1) -> str:
        return self._buffer.read(n)

    def readline(self) -> str:
        return self._buffer.readline()

    def write(self, data: str) -> int:
        return self._buffer.write(data)

    def flush(self) -> None:
        pass  # StringIO doesn't need flushing

    def seek(self, pos: int, whence: int = 0) -> int:
        return self._buffer.seek(pos, whence)

    def tell(self) -> int:
        return self._buffer.tell()

    def close(self) -> None:
        self._closed = True
        self._buffer.close()

    def getvalue(self) -> str:
        """Get the current content of the buffer."""
        return self._buffer.getvalue()

    def add_content(self, content: str) -> None:
        """Add content to the buffer (for simulating input)."""
        current_pos = self._buffer.tell()
        self._buffer.seek(0, 2)  # Seek to end
        self._buffer.write(content)
        self._buffer.seek(current_pos)  # Restore position


class StdioTestEnvironment:
    """Test environment for StdioServer testing.

    Provides mock stdin/stdout that can be used with the anyio-based StdioServer.
    """

    def __init__(self):
        self.stdin_mock = MockTextFile()
        self.stdout_mock = MockTextFile()
        self._stdin_async = None
        self._stdout_async = None

    async def start(self):
        """Initialize async wrappers."""
        self._stdin_async = anyio.wrap_file(self.stdin_mock)
        self._stdout_async = anyio.wrap_file(self.stdout_mock)

    async def stop(self):
        """Clean up async wrappers."""
        if self._stdin_async:
            await self._stdin_async.aclose()
        if self._stdout_async:
            await self._stdout_async.aclose()

    def add_stdin_content(self, content: str) -> None:
        """Add content to stdin for the server to read."""
        self.stdin_mock.add_content(content)

    def get_stdout_content(self) -> str:
        """Get all content written to stdout."""
        return self.stdout_mock.getvalue()


@asynccontextmanager
async def stdio_test_environment():
    """Create a test environment with mock stdin/stdout for testing.

    This is cross-platform and works on both Unix and Windows.

    Yields:
        Dict with keys:
        - 'stdin_file': Mock stdin file for StdioServer
        - 'stdout_file': Mock stdout file for StdioServer
        - 'send_message': Async function to send a message to stdin
        - 'receive_message': Async function to read a message from stdout
        - 'env': The StdioTestEnvironment instance for direct access

    Example:
        async with stdio_test_environment() as env:
            server = StdioServer(
                stdin_file=env['stdin_file'],
                stdout_file=env['stdout_file']
            )
            await server.start()

            # Send a request
            await env['send_message']({'jsonrpc': '2.0', 'method': 'test', 'id': 1})

            # Read response
            response = await env['receive_message']()
    """
    # Create temporary files for stdin/stdout simulation
    # Using tempfile for real file descriptors that work with anyio
    stdin_file = tempfile.NamedTemporaryFile(
        mode='w+', encoding='utf-8', delete=False, suffix='_stdin.txt'
    )
    stdout_file = tempfile.NamedTemporaryFile(
        mode='w+', encoding='utf-8', delete=False, suffix='_stdout.txt'
    )

    # Track what's been written to stdin for the server to read
    stdin_write_pos = 0

    async def send_message(message: dict) -> None:
        """Send a JSON message to the server's stdin."""
        nonlocal stdin_write_pos
        json_data = json.dumps(message) + "\n"
        stdin_file.write(json_data)
        stdin_file.flush()
        stdin_write_pos = stdin_file.tell()

    async def receive_message() -> Optional[dict]:
        """Read a JSON message from the server's stdout."""
        stdout_file.seek(0)
        content = stdout_file.read()
        if not content:
            return None
        lines = content.strip().split('\n')
        if lines:
            try:
                return json.loads(lines[-1])
            except json.JSONDecodeError:
                return None
        return None

    try:
        # Reset files for reading
        stdin_file.seek(0)
        stdout_file.seek(0)

        yield {
            "stdin_file": stdin_file,
            "stdout_file": stdout_file,
            "send_message": send_message,
            "receive_message": receive_message,
        }
    finally:
        # Cleanup
        import os
        stdin_name = stdin_file.name
        stdout_name = stdout_file.name
        stdin_file.close()
        stdout_file.close()
        try:
            os.unlink(stdin_name)
        except OSError:
            pass
        try:
            os.unlink(stdout_name)
        except OSError:
            pass


async def send_json_message(writer, message: dict) -> None:
    """Send a JSON message through an anyio file wrapper."""
    json_data = json.dumps(message) + "\n"
    await writer.write(json_data)
    await writer.flush()


async def read_json_message(reader) -> Optional[dict]:
    """Read a JSON message from an anyio file wrapper."""
    line = await reader.readline()
    if not line:
        return None

    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None
