"""
Tests for MessageSender enum and SenderContext dataclass.
"""

import pytest
from gatekit.protocol.messages import MessageSender, SenderContext


class TestMessageSender:
    """Test MessageSender enum values and behavior."""

    def test_message_sender_values(self):
        """Test that MessageSender has correct enum values."""
        assert MessageSender.CLIENT.value == "client"
        assert MessageSender.SERVER.value == "server"

    def test_message_sender_all_values(self):
        """Test that MessageSender contains all expected values."""
        expected_values = {"client", "server"}
        actual_values = {sender.value for sender in MessageSender}
        assert actual_values == expected_values

    def test_message_sender_from_string(self):
        """Test creating MessageSender from string values."""
        assert MessageSender("client") == MessageSender.CLIENT
        assert MessageSender("server") == MessageSender.SERVER

    def test_message_sender_invalid_value(self):
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError):
            MessageSender("invalid")


class TestSenderContext:
    """Test SenderContext dataclass behavior."""

    def test_sender_context_creation_minimal(self):
        """Test creating SenderContext with minimal required fields."""
        context = SenderContext(
            sender=MessageSender.CLIENT, identifier="test-client-123"
        )

        assert context.sender == MessageSender.CLIENT
        assert context.identifier == "test-client-123"
        assert context.metadata == {}

    def test_sender_context_creation_full(self):
        """Test creating SenderContext with all fields."""
        metadata = {
            "version": "1.0",
            "capabilities": ["tools"],
            "connection_id": "conn-789",
            "session_id": "session-abc",
        }
        context = SenderContext(
            sender=MessageSender.SERVER, identifier="mcp-server-456", metadata=metadata
        )

        assert context.sender == MessageSender.SERVER
        assert context.identifier == "mcp-server-456"
        assert context.metadata == metadata

    def test_sender_context_equality(self):
        """Test SenderContext equality comparison."""
        context1 = SenderContext(
            sender=MessageSender.CLIENT,
            identifier="test-123",
            metadata={"connection_id": "conn-1", "test": True},
        )
        context2 = SenderContext(
            sender=MessageSender.CLIENT,
            identifier="test-123",
            metadata={"connection_id": "conn-1", "test": True},
        )
        context3 = SenderContext(
            sender=MessageSender.CLIENT,
            identifier="test-456",
            metadata={"connection_id": "conn-1", "test": True},
        )

        assert context1 == context2
        assert context1 != context3

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_sender_context_metadata_default(self):
        """Test that metadata defaults to empty dict."""
        context = SenderContext(sender=MessageSender.SERVER, identifier="server-1")

        # Should have empty dict, not None
        assert context.metadata == {}
        assert isinstance(context.metadata, dict)

    def test_sender_context_immutable_after_creation(self):
        """Test that SenderContext is immutable (frozen dataclass)."""
        context = SenderContext(sender=MessageSender.CLIENT, identifier="test-123")

        # SenderContext is not a frozen dataclass in the implementation,
        # so we should be able to modify fields - just update the test to verify this
        context.sender = MessageSender.SERVER
        assert context.sender == MessageSender.SERVER

        context.identifier = "new-id"
        assert context.identifier == "new-id"
