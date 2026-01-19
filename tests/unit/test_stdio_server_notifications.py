"""Test notification support in stdio server with cross-platform anyio-based I/O."""

import pytest
import json
import tempfile
import os

from gatekit.proxy.stdio_server import StdioServer
from gatekit.protocol.messages import MCPRequest, MCPNotification


@pytest.mark.asyncio
async def test_read_message_handles_notification():
    """Test that read_message correctly identifies and validates notifications."""
    notification_data = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
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

        # Read the message
        message = await server.read_message()

        # Verify it's a notification
        assert isinstance(message, MCPNotification)
        assert message.method == "notifications/initialized"
        assert message.params == {}

        await server.stop()
        stdin_file.close()
        stdout_file.close()
    finally:
        os.unlink(stdin_name)
        os.unlink(stdout_name)


@pytest.mark.asyncio
async def test_read_message_handles_request():
    """Test that read_message correctly identifies and validates requests."""
    request_data = {"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}}

    with tempfile.NamedTemporaryFile(
        mode='w+', encoding='utf-8', delete=False
    ) as stdin_f:
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdout_f:
            stdin_f.write(json.dumps(request_data) + "\n")
            stdin_f.flush()
            stdin_name = stdin_f.name
            stdout_name = stdout_f.name

    try:
        stdin_file = open(stdin_name, 'r', encoding='utf-8')
        stdout_file = open(stdout_name, 'w', encoding='utf-8')

        server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
        await server.start()

        # Read the message
        message = await server.read_message()

        # Verify it's a request
        assert isinstance(message, MCPRequest)
        assert message.method == "tools/list"
        assert message.id == 1
        assert message.params == {}

        await server.stop()
        stdin_file.close()
        stdout_file.close()
    finally:
        os.unlink(stdin_name)
        os.unlink(stdout_name)


@pytest.mark.asyncio
async def test_read_request_filters_notifications():
    """Test that read_request filters out notifications and only returns requests."""
    # Send a notification first, then a request
    notification_data = {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {"token": "test"},
    }
    request_data = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {"name": "test_tool"},
    }

    with tempfile.NamedTemporaryFile(
        mode='w+', encoding='utf-8', delete=False
    ) as stdin_f:
        with tempfile.NamedTemporaryFile(
            mode='w+', encoding='utf-8', delete=False
        ) as stdout_f:
            # Write notification then request
            stdin_f.write(json.dumps(notification_data) + "\n")
            stdin_f.write(json.dumps(request_data) + "\n")
            stdin_f.flush()
            stdin_name = stdin_f.name
            stdout_name = stdout_f.name

    try:
        stdin_file = open(stdin_name, 'r', encoding='utf-8')
        stdout_file = open(stdout_name, 'w', encoding='utf-8')

        server = StdioServer(stdin_file=stdin_file, stdout_file=stdout_file)
        await server.start()

        # read_request should skip the notification and return the request
        message = await server.read_request()

        # Verify it's the request, not the notification
        assert isinstance(message, MCPRequest)
        assert message.method == "tools/call"
        assert message.id == 1

        await server.stop()
        stdin_file.close()
        stdout_file.close()
    finally:
        os.unlink(stdin_name)
        os.unlink(stdout_name)


@pytest.mark.asyncio
async def test_write_notification():
    """Test writing notifications to stdout."""
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

        # Create a notification to send
        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/progress",
            params={"token": "test", "value": 50},
        )

        # Write the notification
        await server.write_notification(notification)

        await server.stop()
        stdin_file.close()
        stdout_file.close()

        # Read from stdout file to verify it was written correctly
        with open(stdout_name, 'r', encoding='utf-8') as f:
            content = f.read()

        notification_data = json.loads(content.strip())

        # Verify the notification format
        assert notification_data["jsonrpc"] == "2.0"
        assert notification_data["method"] == "notifications/progress"
        assert notification_data["params"] == {"token": "test", "value": 50}
        assert "id" not in notification_data  # Notifications don't have IDs
    finally:
        os.unlink(stdin_name)
        os.unlink(stdout_name)


@pytest.mark.asyncio
async def test_notification_without_params():
    """Test reading a notification without params field."""
    notification_data = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
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

        assert isinstance(message, MCPNotification)
        assert message.method == "notifications/cancelled"
        # params should be None or empty when not provided
        assert message.params is None or message.params == {}

        await server.stop()
        stdin_file.close()
        stdout_file.close()
    finally:
        os.unlink(stdin_name)
        os.unlink(stdout_name)
