"""Unit tests for MCP protocol message validation."""

import pytest

# Import the classes we'll implement
from gatekit.protocol.validation import MessageValidator, ValidationError
from gatekit.protocol.messages import (
    MCPRequest,
    MCPResponse,
    SenderContext,
    MessageSender,
)
from gatekit.protocol.errors import MCPErrorCodes


class TestMessageValidator:
    """Test the MessageValidator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.validator = MessageValidator()

    def test_validate_valid_request(self):
        """Test validating a valid JSON-RPC request."""
        valid_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "req-1",
            "params": {"clientInfo": {"name": "test-client"}},
        }

        request = self.validator.validate_request(valid_data)

        assert isinstance(request, MCPRequest)
        assert request.jsonrpc == "2.0"
        assert request.method == "initialize"
        assert request.id == "req-1"
        assert request.params == {"clientInfo": {"name": "test-client"}}

    def test_validate_request_without_params(self):
        """Test validating request without params field."""
        valid_data = {"jsonrpc": "2.0", "method": "tools/list", "id": 42}

        request = self.validator.validate_request(valid_data)

        assert isinstance(request, MCPRequest)
        assert request.jsonrpc == "2.0"
        assert request.method == "tools/list"
        assert request.id == 42
        assert request.params is None

    def test_validate_request_missing_jsonrpc(self):
        """Test validation fails when jsonrpc field is missing."""
        invalid_data = {"method": "initialize", "id": "req-1"}

        with pytest.raises(ValidationError, match="Missing required field: jsonrpc"):
            self.validator.validate_request(invalid_data)

    def test_validate_request_missing_method(self):
        """Test validation fails when method field is missing."""
        invalid_data = {"jsonrpc": "2.0", "id": "req-1"}

        with pytest.raises(ValidationError, match="Missing required field: method"):
            self.validator.validate_request(invalid_data)

    def test_validate_request_missing_id(self):
        """Test validation fails when id field is missing."""
        invalid_data = {"jsonrpc": "2.0", "method": "initialize"}

        with pytest.raises(ValidationError, match="Missing required field: id"):
            self.validator.validate_request(invalid_data)

    def test_validate_request_wrong_jsonrpc_version(self):
        """Test validation fails for wrong JSON-RPC version."""
        invalid_data = {"jsonrpc": "1.0", "method": "initialize", "id": "req-1"}

        with pytest.raises(ValidationError, match="Invalid jsonrpc version"):
            self.validator.validate_request(invalid_data)

    def test_validate_request_invalid_id_type(self):
        """Test validation fails for invalid ID type."""
        invalid_data = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": [],  # Lists are not allowed
        }

        with pytest.raises(
            ValidationError, match="Request ID must be a string or integer"
        ):
            self.validator.validate_request(invalid_data)

    def test_validate_request_empty_method(self):
        """Test validation fails for empty method string."""
        invalid_data = {"jsonrpc": "2.0", "method": "", "id": "req-1"}

        with pytest.raises(ValidationError, match="Method cannot be empty"):
            self.validator.validate_request(invalid_data)

    def test_validate_valid_response(self):
        """Test validating a valid JSON-RPC response."""
        valid_data = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {"tools": [{"name": "echo"}]},
        }

        response = self.validator.validate_response(valid_data)

        assert isinstance(response, MCPResponse)
        assert response.jsonrpc == "2.0"
        assert response.id == "req-1"
        assert response.result == {"tools": [{"name": "echo"}]}
        assert response.error is None

    def test_validate_error_response(self):
        """Test validating an error response."""
        valid_data = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "error": {"code": -32600, "message": "Invalid Request"},
        }

        response = self.validator.validate_response(valid_data)

        assert isinstance(response, MCPResponse)
        assert response.jsonrpc == "2.0"
        assert response.id == "req-1"
        assert response.result is None
        assert response.error == {"code": -32600, "message": "Invalid Request"}

    def test_validate_response_missing_jsonrpc(self):
        """Test validation fails when jsonrpc field is missing."""
        invalid_data = {"id": "req-1", "result": {}}

        with pytest.raises(ValidationError, match="Missing required field: jsonrpc"):
            self.validator.validate_response(invalid_data)

    def test_validate_response_missing_id(self):
        """Test validation fails when id field is missing."""
        invalid_data = {"jsonrpc": "2.0", "result": {}}

        with pytest.raises(ValidationError, match="Missing required field: id"):
            self.validator.validate_response(invalid_data)

    def test_validate_response_with_both_result_and_error(self):
        """Test validation fails when both result and error are present."""
        invalid_data = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {"data": "value"},
            "error": {"code": -32600, "message": "Invalid Request"},
        }

        with pytest.raises(
            ValidationError,
            match="Response must have exactly one of 'result' or 'error'",
        ):
            self.validator.validate_response(invalid_data)

    def test_validate_response_with_neither_result_nor_error(self):
        """Test validation fails when neither result nor error are present."""
        invalid_data = {"jsonrpc": "2.0", "id": "req-1"}

        with pytest.raises(
            ValidationError,
            match="Response must have exactly one of 'result' or 'error'",
        ):
            self.validator.validate_response(invalid_data)

    def test_result_response_with_null_id_fails(self):
        """Test that a successful response with null ID is rejected."""
        invalid_data = {"jsonrpc": "2.0", "id": None, "result": {"data": "success"}}

        with pytest.raises(
            ValidationError, match="Result response must have non-null id"
        ):
            self.validator.validate_response(invalid_data)

    def test_error_response_non_parse_with_null_id_fails(self):
        """Test that non-parse error response with null ID is rejected."""
        invalid_data = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": MCPErrorCodes.METHOD_NOT_FOUND,
                "message": "Method not found",
            },
        }

        with pytest.raises(
            ValidationError, match="Null id only permitted for parse error"
        ):
            self.validator.validate_response(invalid_data)

    def test_parse_error_response_with_null_id_passes(self):
        """Test that parse error response with null ID is allowed."""
        valid_data = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": MCPErrorCodes.PARSE_ERROR, "message": "Parse error"},
        }

        response = self.validator.validate_response(valid_data)
        assert response.id is None
        assert response.error["code"] == MCPErrorCodes.PARSE_ERROR

    def test_create_error_response(self):
        """Test creating a standardized error response."""
        from gatekit.protocol.errors import create_error_response

        response = create_error_response(
            request_id="req-1", code=-32600, message="Invalid Request"
        )

        assert isinstance(response, MCPResponse)
        assert response.jsonrpc == "2.0"
        assert response.id == "req-1"
        assert response.result is None
        assert response.error == {"code": -32600, "message": "Invalid Request"}

    def test_create_error_response_with_data(self):
        """Test creating error response with additional data."""
        from gatekit.protocol.errors import create_error_response

        error_data = {"field": "method", "received": "unknown"}

        response = create_error_response(
            request_id=42, code=-32601, message="Method not found", data=error_data
        )

        assert response.id == 42
        assert response.error == {
            "code": -32601,
            "message": "Method not found",
            "data": error_data,
        }


class TestMessageValidationEdgeCases:
    """Test edge cases and error conditions in message validation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.validator = MessageValidator()

    def test_validate_request_with_none_data(self):
        """Test validation fails gracefully with None input."""
        with pytest.raises(ValidationError, match="Invalid message data"):
            self.validator.validate_request(None)

    def test_validate_request_with_empty_dict(self):
        """Test validation fails with empty dictionary."""
        with pytest.raises(ValidationError, match="Missing required field"):
            self.validator.validate_request({})

    def test_validate_request_with_non_dict(self):
        """Test validation fails with non-dictionary input."""
        with pytest.raises(ValidationError, match="Invalid message data"):
            self.validator.validate_request("not a dict")

    def test_validate_large_message(self):
        """Test validation handles reasonably large messages."""
        large_params = {"data": "x" * 10000}  # 10KB of data

        valid_data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "params": large_params,
        }

        request = self.validator.validate_request(valid_data)
        assert request.params == large_params

    def test_validate_request_with_various_id_types(self):
        """Test validation with different valid ID types."""
        # String ID
        data1 = {"jsonrpc": "2.0", "method": "test", "id": "string-123"}
        request1 = self.validator.validate_request(data1)
        assert request1.id == "string-123"

        # Integer ID
        data2 = {"jsonrpc": "2.0", "method": "test", "id": 42}
        request2 = self.validator.validate_request(data2)
        assert request2.id == 42

        # Float ID (should fail per best practices)
        data3 = {"jsonrpc": "2.0", "method": "test", "id": 3.14}
        with pytest.raises(
            ValidationError, match="Request ID must be a string or integer"
        ):
            self.validator.validate_request(data3)

    def test_method_with_leading_whitespace_fails(self):
        """Test that method names with leading whitespace are rejected."""
        invalid_data = {"jsonrpc": "2.0", "method": "  test", "id": "req-1"}

        with pytest.raises(
            ValidationError, match="Method name cannot start or end with whitespace"
        ):
            self.validator.validate_request(invalid_data)

    def test_method_with_trailing_whitespace_fails(self):
        """Test that method names with trailing whitespace are rejected."""
        invalid_data = {"jsonrpc": "2.0", "method": "test  ", "id": "req-1"}

        with pytest.raises(
            ValidationError, match="Method name cannot start or end with whitespace"
        ):
            self.validator.validate_request(invalid_data)

    def test_request_with_valid_sender_context(self):
        """Test that valid sender context is parsed correctly."""
        data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "sender_context": {
                "sender": "client",
                "identifier": "client-123",
                "metadata": {"version": "1.0"},
            },
        }

        request = self.validator.validate_request(data)
        assert request.sender_context is not None
        assert request.sender_context.sender == MessageSender.CLIENT
        assert request.sender_context.identifier == "client-123"
        assert request.sender_context.metadata == {"version": "1.0"}

    def test_sender_context_invalid_sender_value_fails(self):
        """Test that invalid sender value is rejected."""
        data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "sender_context": {"sender": "unknown"},
        }

        with pytest.raises(ValidationError, match="must be 'client' or 'server'"):
            self.validator.validate_request(data)

    def test_request_with_too_many_param_keys_fails(self):
        """Test that params with too many keys is rejected."""
        # Create params with 1001 keys (exceeds 1000 limit)
        excessive_params = {f"key_{i}": i for i in range(1001)}

        data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "params": excessive_params,
        }

        with pytest.raises(ValidationError, match="exceeds maximum of 1000 keys"):
            self.validator.validate_request(data)

    def test_malformed_message_detection(self):
        """Test that message with both method and result is detected as malformed."""
        malformed_data = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "method": "test",
            "result": {"data": "value"},
        }

        with pytest.raises(ValidationError) as exc_info:
            self.validator.determine_message_type(malformed_data)

        assert str(exc_info.value.error_type) == "malformed_message"
        assert "both request fields" in str(exc_info.value)

    def test_validate_request_mcp_methods(self):
        """Test validation with known MCP methods."""
        mcp_methods = [
            "initialize",
            "tools/list",
            "tools/call",
            "resources/list",
            "resources/read",
        ]

        for method in mcp_methods:
            data = {"jsonrpc": "2.0", "method": method, "id": f"req-{method}"}

            request = self.validator.validate_request(data)
            assert request.method == method


class TestMessageSizeValidation:
    """Test message size validation for DoS protection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.validator = MessageValidator()

    def test_validate_oversized_message_fails(self):
        """Test that extremely large messages are rejected."""
        # Create a message larger than reasonable limit (1MB)
        oversized_data = "x" * (1024 * 1024 + 1)  # > 1MB

        invalid_data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "params": {"large_data": oversized_data},
        }

        with pytest.raises(ValidationError, match="Message size exceeds maximum"):
            self.validator.validate_request(invalid_data)

    def test_validate_reasonable_size_message_passes(self):
        """Test that reasonably sized messages pass validation."""
        # Create a 100KB message (should be fine)
        reasonable_data = "x" * (100 * 1024)  # 100KB

        valid_data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "params": {"data": reasonable_data},
        }

        request = self.validator.validate_request(valid_data)
        assert request.params["data"] == reasonable_data

    def test_batch_with_oversized_element_fails(self):
        """Test that batch with an oversized element is rejected."""
        # Create a large params object
        large_params = {"data": "x" * (300 * 1024)}  # 300KB > 256KB limit

        batch_data = [
            {"jsonrpc": "2.0", "method": "small", "id": "1"},
            {"jsonrpc": "2.0", "method": "large", "id": "2", "params": large_params},
        ]

        with pytest.raises(ValidationError, match="exceeds maximum element size"):
            self.validator.validate_batch(batch_data)

    def test_batch_with_malformed_item(self):
        """Test that batch with malformed item gives specific error type."""
        batch_data = [
            {"jsonrpc": "2.0", "method": "test1", "id": "1"},
            {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "test2",
                "result": {"data": "invalid"},  # Malformed
            },
        ]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate_batch(batch_data)

        assert "malformed" in str(exc_info.value).lower()
        assert str(exc_info.value.error_type) == "malformed_batch_item"


class TestNewBehaviors:
    """Test new behaviors added from QC feedback."""

    def setup_method(self):
        """Set up test instance."""
        from gatekit.protocol.validation import MessageValidator

        self.validator = MessageValidator()

    def test_null_id_with_invalid_request_passes(self):
        """Test that null id with INVALID_REQUEST error code passes validation."""
        from gatekit.protocol.errors import MCPErrorCodes

        response_data = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": MCPErrorCodes.INVALID_REQUEST,
                "message": "Invalid request",
            },
        }

        # Should not raise
        response = self.validator.validate_response(response_data)
        assert response.id is None
        assert response.error["code"] == MCPErrorCodes.INVALID_REQUEST

    def test_null_id_with_method_not_found_fails(self):
        """Test that null id with METHOD_NOT_FOUND error code fails validation."""
        from gatekit.protocol.errors import MCPErrorCodes
        from gatekit.protocol.validation import ValidationError

        response_data = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": MCPErrorCodes.METHOD_NOT_FOUND,
                "message": "Method not found",
            },
        }

        with pytest.raises(
            ValidationError,
            match="Null id only permitted for parse error or invalid request",
        ):
            self.validator.validate_response(response_data)

    def test_non_serializable_metadata_raises_json_error(self):
        """Test that non-serializable metadata raises JSON_ERROR."""
        from gatekit.protocol.validation import ValidationError, ValidationErrorType
        import datetime

        data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "sender_context": {
                "sender": "client",
                "metadata": {
                    "timestamp": datetime.datetime.now()  # Not JSON serializable
                },
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate_request(data)

        assert exc_info.value.error_type == ValidationErrorType.JSON_ERROR
        assert "non-JSON serializable" in str(exc_info.value)

    def test_validation_limits_override(self):
        """Test ValidationLimits with custom limits."""
        from gatekit.protocol.validation import (
            ValidationLimits,
            ValidationError,
            ValidationErrorType,
        )

        # Create validator with tiny size limit (need to set both limits consistently)
        tiny_limits = ValidationLimits(
            max_message_size=1000, max_batch_element_size=500
        )
        validator = MessageValidator(limits=tiny_limits)

        # Create message that exceeds tiny limit
        large_data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "params": {"data": "x" * 2000},  # Will exceed 1000 byte limit
        }

        with pytest.raises(ValidationError) as exc_info:
            validator.validate_request(large_data)

        assert exc_info.value.error_type == ValidationErrorType.SIZE_LIMIT
        assert "exceeds maximum of 1000 bytes" in str(exc_info.value)

    def test_malformed_batch_item_classification(self):
        """Test that malformed message in batch gets MALFORMED_BATCH_ITEM classification."""
        from gatekit.protocol.validation import ValidationError, ValidationErrorType

        batch_data = [
            {"jsonrpc": "2.0", "method": "valid", "id": "1"},
            {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "invalid",  # Has both method and result - malformed
                "result": {"data": "should not have both"},
            },
        ]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate_batch(batch_data)

        assert exc_info.value.error_type == ValidationErrorType.MALFORMED_BATCH_ITEM
        assert "malformed" in str(exc_info.value).lower()

    def test_sender_context_normalization_in_from_dict(self):
        """Test that from_dict normalizes sender_context dict to SenderContext object."""
        from gatekit.protocol.messages import MCPRequest, MessageSender

        data = {
            "jsonrpc": "2.0",
            "method": "test",
            "id": "req-1",
            "sender_context": {
                "sender": "client",
                "identifier": "test-client",
                "metadata": {"key": "value"},
            },
        }

        request = MCPRequest.from_dict(data)

        # Should be normalized to SenderContext object
        assert isinstance(request.sender_context, SenderContext)
        assert request.sender_context.sender == MessageSender.CLIENT
        assert request.sender_context.identifier == "test-client"
        assert request.sender_context.metadata == {"key": "value"}
