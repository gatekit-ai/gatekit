# filepath: /Users/dbright/mcp/gatekit/tests/unit/test_transport_base.py
"""Tests for the abstract Transport base class.

This module tests the Transport interface contract and ensures proper
abstract method enforcement.
"""

import pytest
from abc import ABC

from gatekit.transport.base import Transport
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestTransportInterface:
    """Test Transport abstract interface requirements."""

    def test_transport_is_abstract_base_class(self):
        """Test that Transport is an abstract base class."""
        assert issubclass(Transport, ABC)

    def test_cannot_instantiate_transport_directly(self):
        """Test that Transport cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            Transport()

    def test_abstract_methods_exist(self):
        """Test that required abstract methods are defined."""
        # Check that abstract methods are properly defined
        abstract_methods = Transport.__abstractmethods__

        expected_methods = {
            "connect",
            "disconnect",
            "send_message",
            "send_notification",
            "receive_message",
            "get_next_notification",
            "is_connected",
            "send_and_receive",
        }

        assert abstract_methods == expected_methods

    def test_concrete_implementation_requires_all_methods(self):
        """Test that concrete implementations must implement all abstract methods."""

        # Missing some methods should fail
        class IncompleteTransport(Transport):
            async def connect(self):
                pass

            # Missing other methods

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteTransport()

    def test_complete_implementation_works(self):
        """Test that complete implementation can be instantiated."""

        class CompleteTransport(Transport):
            async def connect(self):
                pass

            async def disconnect(self):
                pass

            async def send_message(self, message: MCPRequest) -> None:
                pass

            async def send_notification(self, notification: MCPNotification) -> None:
                pass

            async def receive_message(self) -> MCPResponse:
                return MCPResponse(jsonrpc="2.0", id=1, result={})

            async def get_next_notification(self):
                return MCPNotification(jsonrpc="2.0", method="test/notification")

            def is_connected(self) -> bool:
                return True

            async def send_and_receive(self, request: MCPRequest) -> MCPResponse:
                return MCPResponse(jsonrpc="2.0", id=request.id, result={})

        # Should not raise
        transport = CompleteTransport()
        assert isinstance(transport, Transport)
        assert transport.is_connected() is True


class TestTransportMethodSignatures:
    """Test Transport method signatures and contracts."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport for testing method signatures."""

        class MockTransport(Transport):
            def __init__(self):
                self._connected = False

            async def connect(self):
                self._connected = True

            async def disconnect(self):
                self._connected = False

            async def send_message(self, message: MCPRequest) -> None:
                if not self._connected:
                    raise RuntimeError("Not connected")

            async def send_notification(self, notification: MCPNotification) -> None:
                if not self._connected:
                    raise RuntimeError("Not connected")

            async def receive_message(self) -> MCPResponse:
                if not self._connected:
                    raise RuntimeError("Not connected")
                return MCPResponse(jsonrpc="2.0", id=1, result={})

            async def get_next_notification(self):
                if not self._connected:
                    raise RuntimeError("Not connected")
                return MCPNotification(jsonrpc="2.0", method="test/notification")

            def is_connected(self) -> bool:
                return self._connected

            async def send_and_receive(self, request: MCPRequest) -> MCPResponse:
                if not self._connected:
                    raise RuntimeError("Not connected")
                return MCPResponse(jsonrpc="2.0", id=request.id, result={})

        return MockTransport()

    @pytest.mark.asyncio
    async def test_connect_signature(self, mock_transport):
        """Test connect method signature and behavior."""
        assert not mock_transport.is_connected()
        await mock_transport.connect()
        assert mock_transport.is_connected()

    @pytest.mark.asyncio
    async def test_disconnect_signature(self, mock_transport):
        """Test disconnect method signature and behavior."""
        await mock_transport.connect()
        assert mock_transport.is_connected()
        await mock_transport.disconnect()
        assert not mock_transport.is_connected()

    @pytest.mark.asyncio
    async def test_send_message_signature(self, mock_transport):
        """Test send_message method signature."""
        request = MCPRequest(jsonrpc="2.0", method="test", id=1)

        # Should fail when not connected
        with pytest.raises(RuntimeError):
            await mock_transport.send_message(request)

        # Should work when connected
        await mock_transport.connect()
        await mock_transport.send_message(request)  # Should not raise

    @pytest.mark.asyncio
    async def test_receive_message_signature(self, mock_transport):
        """Test receive_message method signature."""
        # Should fail when not connected
        with pytest.raises(RuntimeError):
            await mock_transport.receive_message()

        # Should work when connected
        await mock_transport.connect()
        response = await mock_transport.receive_message()
        assert isinstance(response, MCPResponse)
        assert response.jsonrpc == "2.0"

    def test_is_connected_signature(self, mock_transport):
        """Test is_connected method signature."""
        # Should be synchronous and return bool
        result = mock_transport.is_connected()
        assert isinstance(result, bool)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_notification_signature(self, mock_transport):
        """Test send_notification method signature."""
        notification = MCPNotification(
            jsonrpc="2.0", method="notifications/initialized"
        )

        # Should fail when not connected
        with pytest.raises(RuntimeError):
            await mock_transport.send_notification(notification)

        # Should work when connected
        await mock_transport.connect()
        await mock_transport.send_notification(notification)  # Should not raise

    @pytest.mark.asyncio
    async def test_get_next_notification_signature(self, mock_transport):
        """Test get_next_notification method signature."""
        # Should fail when not connected
        with pytest.raises(RuntimeError):
            await mock_transport.get_next_notification()

        # Should work when connected
        await mock_transport.connect()
        notification = await mock_transport.get_next_notification()
        # Should return MCPNotification
        assert isinstance(notification, MCPNotification)
        assert notification.jsonrpc == "2.0"
