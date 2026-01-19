"""Unit tests for MCP protocol message types."""


# Import the classes we'll implement
from gatekit.protocol.messages import (
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPNotification,
    MessageSender,
    SenderContext,
)


class TestMCPRequest:
    """Test MCPRequest dataclass creation and validation."""

    def test_create_valid_request(self):
        """Test creating a valid MCP request."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id="req-1",
            params={"clientInfo": {"name": "test-client"}},
        )

        assert request.jsonrpc == "2.0"
        assert request.method == "initialize"
        assert request.id == "req-1"
        assert request.params == {"clientInfo": {"name": "test-client"}}

    def test_create_request_without_params(self):
        """Test creating request without optional params."""
        request = MCPRequest(jsonrpc="2.0", method="tools/list", id=42)

        assert request.jsonrpc == "2.0"
        assert request.method == "tools/list"
        assert request.id == 42
        assert request.params is None

    def test_request_id_can_be_string_or_int(self):
        """Test that request ID can be either string or integer."""
        # String ID
        request1 = MCPRequest(jsonrpc="2.0", method="test", id="string-id")
        assert request1.id == "string-id"

        # Integer ID
        request2 = MCPRequest(jsonrpc="2.0", method="test", id=123)
        assert request2.id == 123

    def test_request_params_can_be_dict_or_none(self):
        """Test that params can be dict or None."""
        # Dict params
        request1 = MCPRequest(
            jsonrpc="2.0", method="test", id=1, params={"key": "value"}
        )
        assert request1.params == {"key": "value"}

        # None params (default)
        request2 = MCPRequest(jsonrpc="2.0", method="test", id=2)
        assert request2.params is None

class TestMCPResponse:
    """Test MCPResponse dataclass creation and validation."""

    def test_create_success_response(self):
        """Test creating a successful response."""
        response = MCPResponse(
            jsonrpc="2.0", id="req-1", result={"tools": [{"name": "echo"}]}
        )

        assert response.jsonrpc == "2.0"
        assert response.id == "req-1"
        assert response.result == {"tools": [{"name": "echo"}]}
        assert response.error is None

    def test_create_error_response(self):
        """Test creating an error response."""
        error_data = {"code": -32600, "message": "Invalid Request"}

        response = MCPResponse(jsonrpc="2.0", id="req-1", error=error_data)

        assert response.jsonrpc == "2.0"
        assert response.id == "req-1"
        assert response.result is None
        assert response.error == error_data

    def test_response_id_can_be_string_or_int(self):
        """Test that response ID can be either string or integer."""
        # String ID
        response1 = MCPResponse(jsonrpc="2.0", id="string-id", result={})
        assert response1.id == "string-id"

        # Integer ID
        response2 = MCPResponse(jsonrpc="2.0", id=456, result={})
        assert response2.id == 456

    def test_response_with_no_result_or_error(self):
        """Test response with default None values."""
        response = MCPResponse(jsonrpc="2.0", id="test")

        assert response.jsonrpc == "2.0"
        assert response.id == "test"
        assert response.result is None
        assert response.error is None


class TestMCPError:
    """Test MCPError dataclass creation and validation."""

    def test_create_basic_error(self):
        """Test creating a basic error."""
        error = MCPError(code=-32600, message="Invalid Request")

        assert error.code == -32600
        assert error.message == "Invalid Request"
        assert error.data is None

    def test_create_error_with_data(self):
        """Test creating error with additional data."""
        error_data = {"field": "method", "reason": "missing"}

        error = MCPError(code=-32602, message="Invalid params", data=error_data)

        assert error.code == -32602
        assert error.message == "Invalid params"
        assert error.data == error_data

    def test_error_code_types(self):
        """Test that error codes work with different values."""
        # Standard JSON-RPC error
        error1 = MCPError(code=-32700, message="Parse error")
        assert error1.code == -32700

        # Gatekit-specific error
        error2 = MCPError(code=-32000, message="Policy violation")
        assert error2.code == -32000


class TestMessageTypeIntegration:
    """Test integration between different message types."""

    def test_request_response_id_matching(self):
        """Test that request and response IDs can match."""
        request_id = "test-123"

        request = MCPRequest(jsonrpc="2.0", method="tools/list", id=request_id)

        response = MCPResponse(jsonrpc="2.0", id=request_id, result={"tools": []})

        assert request.id == response.id

    def test_error_in_response(self):
        """Test embedding MCPError in MCPResponse."""
        error = MCPError(
            code=-32601, message="Method not found", data={"method": "unknown/method"}
        )

        # Error should be converted to dict for response
        error_dict = {"code": error.code, "message": error.message, "data": error.data}

        response = MCPResponse(jsonrpc="2.0", id="req-1", error=error_dict)

        assert response.error["code"] == error.code
        assert response.error["message"] == error.message
        assert response.error["data"] == error.data


class TestMessageSender:
    """Test MessageSender enum."""

    def test_message_sender_has_client_and_server_values(self):
        """Test that MessageSender enum has CLIENT and SERVER values."""
        assert MessageSender.CLIENT is not None
        assert MessageSender.SERVER is not None

    def test_message_sender_values(self):
        """Test MessageSender enum values."""
        assert MessageSender.CLIENT.value == "client"
        assert MessageSender.SERVER.value == "server"

    def test_message_sender_comparison(self):
        """Test MessageSender enum comparison."""
        assert MessageSender.CLIENT == MessageSender.CLIENT
        assert MessageSender.SERVER == MessageSender.SERVER
        assert MessageSender.CLIENT != MessageSender.SERVER


class TestSenderContext:
    """Test SenderContext dataclass."""

    def test_create_sender_context_with_sender_only(self):
        """Test creating SenderContext with just sender."""
        context = SenderContext(sender=MessageSender.CLIENT)

        assert context.sender == MessageSender.CLIENT
        assert context.metadata == {}

    def test_create_sender_context_with_metadata(self):
        """Test creating SenderContext with metadata."""
        metadata = {"user_id": "12345", "session_id": "abc-def"}
        context = SenderContext(sender=MessageSender.SERVER, metadata=metadata)

        assert context.sender == MessageSender.SERVER
        assert context.metadata == metadata

    def test_sender_context_metadata_is_mutable(self):
        """Test that metadata dict can be modified after creation."""
        context = SenderContext(sender=MessageSender.CLIENT)
        context.metadata["new_key"] = "new_value"

        assert context.metadata["new_key"] == "new_value"

    def test_sender_context_default_metadata_factory(self):
        """Test that each SenderContext gets its own metadata dict."""
        context1 = SenderContext(sender=MessageSender.CLIENT)
        context2 = SenderContext(sender=MessageSender.CLIENT)

        context1.metadata["key1"] = "value1"
        context2.metadata["key2"] = "value2"

        assert "key1" in context1.metadata
        assert "key1" not in context2.metadata
        assert "key2" in context2.metadata
        assert "key2" not in context1.metadata


class TestMCPRequestWithSenderContext:
    """Test MCPRequest with sender_context field."""

    def test_create_request_with_sender_context(self):
        """Test creating MCPRequest with sender_context."""
        context = SenderContext(
            sender=MessageSender.CLIENT, metadata={"user_id": "user123"}
        )
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="req-1",
            params={"name": "get_weather"},
            sender_context=context,
        )

        assert request.sender_context == context
        assert request.sender_context.sender == MessageSender.CLIENT
        assert request.sender_context.metadata["user_id"] == "user123"

    def test_create_request_without_sender_context(self):
        """Test creating MCPRequest without sender_context (backward compatibility)."""
        request = MCPRequest(jsonrpc="2.0", method="tools/list", id="req-2")

        assert request.sender_context is None

    def test_request_sender_context_optional(self):
        """Test that sender_context is optional."""
        # Should work with sender_context
        context = SenderContext(sender=MessageSender.CLIENT)
        request1 = MCPRequest(
            jsonrpc="2.0", method="test", id=1, sender_context=context
        )
        assert request1.sender_context is not None

        # Should work without sender_context
        request2 = MCPRequest(jsonrpc="2.0", method="test", id=2)
        assert request2.sender_context is None


class TestMCPResponseWithSenderContext:
    """Test MCPResponse with sender_context field."""

    def test_create_response_with_sender_context(self):
        """Test creating MCPResponse with sender_context."""
        context = SenderContext(
            sender=MessageSender.SERVER, metadata={"server_version": "1.0.0"}
        )
        response = MCPResponse(
            jsonrpc="2.0", id="req-1", result={"tools": []}, sender_context=context
        )

        assert response.sender_context == context
        assert response.sender_context.sender == MessageSender.SERVER
        assert response.sender_context.metadata["server_version"] == "1.0.0"

    def test_create_response_without_sender_context(self):
        """Test creating MCPResponse without sender_context (backward compatibility)."""
        response = MCPResponse(jsonrpc="2.0", id="req-1", result={"status": "ok"})

        assert response.sender_context is None

    def test_response_sender_context_optional(self):
        """Test that sender_context is optional."""
        # Should work with sender_context
        context = SenderContext(sender=MessageSender.SERVER)
        response1 = MCPResponse(jsonrpc="2.0", id=1, result={}, sender_context=context)
        assert response1.sender_context is not None

        # Should work without sender_context
        response2 = MCPResponse(jsonrpc="2.0", id=2, result={})
        assert response2.sender_context is None


class TestMCPNotification:
    """Test MCPNotification message type."""

    def test_create_basic_notification(self):
        """Test creating a basic MCPNotification."""
        notification = MCPNotification(
            jsonrpc="2.0", method="notifications/initialized"
        )

        assert notification.jsonrpc == "2.0"
        assert notification.method == "notifications/initialized"
        assert notification.params is None
        assert notification.sender_context is None

    def test_create_notification_with_params(self):
        """Test creating MCPNotification with params."""
        params = {"message": "Server ready"}
        notification = MCPNotification(
            jsonrpc="2.0", method="notifications/message", params=params
        )

        assert notification.params == params

    def test_create_notification_with_sender_context(self):
        """Test creating MCPNotification with sender_context."""
        context = SenderContext(
            sender=MessageSender.SERVER, metadata={"timestamp": "2024-01-01T00:00:00Z"}
        )
        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/progress",
            params={"progress": 50},
            sender_context=context,
        )

        assert notification.sender_context == context
        assert notification.sender_context.sender == MessageSender.SERVER

    def test_notification_has_no_id_field(self):
        """Test that MCPNotification does not have an id field."""
        notification = MCPNotification(jsonrpc="2.0", method="notifications/test")

        # Should not have id attribute
        assert not hasattr(notification, "id")


class TestMessageTypesIntegration:
    """Test integration between different message types with sender context."""

    def test_request_response_with_matching_sender_contexts(self):
        """Test request and response with appropriate sender contexts."""
        # Client sends request
        client_context = SenderContext(
            sender=MessageSender.CLIENT, metadata={"client_id": "test-client"}
        )
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/list",
            id="req-1",
            sender_context=client_context,
        )

        # Server sends response
        server_context = SenderContext(
            sender=MessageSender.SERVER, metadata={"response_time": "10ms"}
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id=request.id,
            result={"tools": []},
            sender_context=server_context,
        )

        assert request.sender_context.sender == MessageSender.CLIENT
        assert response.sender_context.sender == MessageSender.SERVER
        assert request.id == response.id

    def test_notification_from_server(self):
        """Test server notification with appropriate sender context."""
        server_context = SenderContext(
            sender=MessageSender.SERVER, metadata={"event_type": "status_update"}
        )
        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/status_changed",
            params={"status": "ready"},
            sender_context=server_context,
        )

        assert notification.sender_context.sender == MessageSender.SERVER
        assert notification.params["status"] == "ready"

    def test_different_metadata_structures(self):
        """Test that different message types can have different metadata structures."""
        # Request with authentication metadata
        request_context = SenderContext(
            sender=MessageSender.CLIENT,
            metadata={
                "auth": {"token": "abc123", "user_id": "user1"},
                "client_info": {"name": "test-client", "version": "1.0"},
            },
        )
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="req-1",
            sender_context=request_context,
        )

        # Response with performance metadata
        response_context = SenderContext(
            sender=MessageSender.SERVER,
            metadata={
                "performance": {"duration_ms": 150, "cache_hit": True},
                "server_load": {"cpu": 45, "memory": 60},
            },
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id="req-1",
            result={"result": "success"},
            sender_context=response_context,
        )

        # Notification with event metadata
        notification_context = SenderContext(
            sender=MessageSender.SERVER,
            metadata={
                "event": {"type": "resource_updated", "resource_id": "res-123"},
                "timestamp": "2024-01-01T10:00:00Z",
            },
        )
        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/resource_updated",
            params={"resource_id": "res-123"},
            sender_context=notification_context,
        )

        # Verify all have different metadata structures but same basic interface
        assert "auth" in request.sender_context.metadata
        assert "performance" in response.sender_context.metadata
        assert "event" in notification.sender_context.metadata

        # But all have the same sender context interface
        assert all(
            hasattr(ctx.sender_context, "sender")
            for ctx in [request, response, notification]
        )
        assert all(
            hasattr(ctx.sender_context, "metadata")
            for ctx in [request, response, notification]
        )
