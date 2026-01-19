"""Unit tests for MCP protocol error codes and error handling."""

import pytest

# Import the classes we'll implement
from gatekit.protocol.errors import (
    MCPErrorCodes,
    create_error_response_dict,
    create_error_dict,
)


class TestMCPErrorCodes:
    """Test the MCPErrorCodes class with standard JSON-RPC and Gatekit-specific codes."""

    def test_standard_jsonrpc_error_codes(self):
        """Test that standard JSON-RPC error codes are defined correctly."""
        # Standard JSON-RPC 2.0 error codes
        assert MCPErrorCodes.PARSE_ERROR == -32700
        assert MCPErrorCodes.INVALID_REQUEST == -32600
        assert MCPErrorCodes.METHOD_NOT_FOUND == -32601
        assert MCPErrorCodes.INVALID_PARAMS == -32602
        assert MCPErrorCodes.INTERNAL_ERROR == -32603

    def test_gatekit_specific_error_codes(self):
        """Test that Gatekit-specific error codes are defined correctly."""
        # Gatekit-specific error codes (in -32000 to -32099 range)
        assert MCPErrorCodes.SECURITY_VIOLATION == -32000
        assert MCPErrorCodes.CONFIGURATION_ERROR == -32001
        assert MCPErrorCodes.PLUGIN_LOADING_ERROR == -32002
        assert MCPErrorCodes.PERMISSION_ERROR == -32003
        assert MCPErrorCodes.UPSTREAM_UNAVAILABLE == -32004
        assert MCPErrorCodes.AUDITING_FAILURE == -32005

    def test_error_code_ranges(self):
        """Test that error codes follow JSON-RPC conventions."""
        # Standard errors should be in -32768 to -32000 range
        standard_codes = [
            MCPErrorCodes.PARSE_ERROR,
            MCPErrorCodes.INVALID_REQUEST,
            MCPErrorCodes.METHOD_NOT_FOUND,
            MCPErrorCodes.INVALID_PARAMS,
            MCPErrorCodes.INTERNAL_ERROR,
        ]

        for code in standard_codes:
            assert -32768 <= code <= -32000

        # Implementation-defined errors should be in -32099 to -32000 range
        custom_codes = [
            MCPErrorCodes.SECURITY_VIOLATION,
            MCPErrorCodes.CONFIGURATION_ERROR,
            MCPErrorCodes.PLUGIN_LOADING_ERROR,
            MCPErrorCodes.PERMISSION_ERROR,
            MCPErrorCodes.UPSTREAM_UNAVAILABLE,
            MCPErrorCodes.AUDITING_FAILURE,
        ]

        for code in custom_codes:
            assert -32099 <= code <= -32000

    def test_error_codes_are_unique(self):
        """Test that all error codes are unique."""
        codes = [
            MCPErrorCodes.PARSE_ERROR,
            MCPErrorCodes.INVALID_REQUEST,
            MCPErrorCodes.METHOD_NOT_FOUND,
            MCPErrorCodes.INVALID_PARAMS,
            MCPErrorCodes.INTERNAL_ERROR,
            MCPErrorCodes.SECURITY_VIOLATION,
            MCPErrorCodes.CONFIGURATION_ERROR,
            MCPErrorCodes.PLUGIN_LOADING_ERROR,
            MCPErrorCodes.PERMISSION_ERROR,
            MCPErrorCodes.UPSTREAM_UNAVAILABLE,
            MCPErrorCodes.AUDITING_FAILURE,
        ]

        # All codes should be unique
        assert len(codes) == len(set(codes))

    def test_error_codes_are_integers(self):
        """Test that all error codes are integers."""
        codes = [
            MCPErrorCodes.PARSE_ERROR,
            MCPErrorCodes.INVALID_REQUEST,
            MCPErrorCodes.METHOD_NOT_FOUND,
            MCPErrorCodes.INVALID_PARAMS,
            MCPErrorCodes.INTERNAL_ERROR,
            MCPErrorCodes.SECURITY_VIOLATION,
            MCPErrorCodes.CONFIGURATION_ERROR,
            MCPErrorCodes.PLUGIN_LOADING_ERROR,
            MCPErrorCodes.PERMISSION_ERROR,
            MCPErrorCodes.UPSTREAM_UNAVAILABLE,
            MCPErrorCodes.AUDITING_FAILURE,
        ]

        for code in codes:
            assert isinstance(code, int)


class TestErrorResponseCreation:
    """Test utility functions for creating error responses."""

    def test_create_error_response_basic(self):
        """Test creating a basic error response."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.INVALID_REQUEST,
            message="Invalid Request",
        )

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "req-1"
        assert "result" not in response
        assert response["error"]["code"] == MCPErrorCodes.INVALID_REQUEST
        assert response["error"]["message"] == "Invalid Request"
        assert "data" not in response["error"]

    def test_create_error_response_with_data(self):
        """Test creating error response with additional data."""
        error_data = {"field": "method", "received": "unknown_method"}

        response = create_error_response_dict(
            request_id=42,
            code=MCPErrorCodes.METHOD_NOT_FOUND,
            message="Method not found",
            data=error_data,
        )

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 42
        assert response["error"]["code"] == MCPErrorCodes.METHOD_NOT_FOUND
        assert response["error"]["message"] == "Method not found"
        assert response["error"]["data"] == error_data

    def test_create_error_response_string_and_int_ids(self):
        """Test error responses with both string and integer IDs."""
        # String ID
        response1 = create_error_response_dict(
            request_id="string-id",
            code=MCPErrorCodes.PARSE_ERROR,
            message="Parse error",
        )
        assert response1["id"] == "string-id"

        # Integer ID
        response2 = create_error_response_dict(
            request_id=123, code=MCPErrorCodes.PARSE_ERROR, message="Parse error"
        )
        assert response2["id"] == 123

    def test_create_error_response_null_id(self):
        """Test error response with null ID (when request ID is unknown)."""
        response = create_error_response_dict(
            request_id=None, code=MCPErrorCodes.PARSE_ERROR, message="Parse error"
        )

        assert response["id"] is None

    def test_create_error_dict_basic(self):
        """Test creating error dictionary without full response structure."""
        error_dict = create_error_dict(
            code=MCPErrorCodes.INVALID_PARAMS, message="Invalid params"
        )

        assert error_dict["code"] == MCPErrorCodes.INVALID_PARAMS
        assert error_dict["message"] == "Invalid params"
        assert "data" not in error_dict

    def test_create_error_dict_with_data(self):
        """Test creating error dictionary with additional data."""
        error_data = {"expected": "string", "received": "number"}

        error_dict = create_error_dict(
            code=MCPErrorCodes.INVALID_PARAMS, message="Invalid params", data=error_data
        )

        assert error_dict["code"] == MCPErrorCodes.INVALID_PARAMS
        assert error_dict["message"] == "Invalid params"
        assert error_dict["data"] == error_data


class TestStandardErrorScenarios:
    """Test standard error scenarios and their proper error codes."""

    def test_parse_error_scenario(self):
        """Test parse error for malformed JSON."""
        response = create_error_response_dict(
            request_id=None,  # Unknown ID when JSON is malformed
            code=MCPErrorCodes.PARSE_ERROR,
            message="Parse error",
        )

        assert response["error"]["code"] == MCPErrorCodes.PARSE_ERROR
        assert response["id"] is None

    def test_invalid_request_scenario(self):
        """Test invalid request error for malformed JSON-RPC."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.INVALID_REQUEST,
            message="Invalid Request",
            data={"reason": "Missing method field"},
        )

        assert response["error"]["code"] == MCPErrorCodes.INVALID_REQUEST
        assert response["error"]["data"]["reason"] == "Missing method field"

    def test_method_not_found_scenario(self):
        """Test method not found error."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.METHOD_NOT_FOUND,
            message="Method not found",
            data={"method": "unknown/method"},
        )

        assert response["error"]["code"] == MCPErrorCodes.METHOD_NOT_FOUND
        assert response["error"]["data"]["method"] == "unknown/method"

    def test_invalid_params_scenario(self):
        """Test invalid parameters error."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.INVALID_PARAMS,
            message="Invalid params",
            data={"expected": "object", "received": "string"},
        )

        assert response["error"]["code"] == MCPErrorCodes.INVALID_PARAMS
        assert response["error"]["data"]["expected"] == "object"

    def test_internal_error_scenario(self):
        """Test internal error for unexpected exceptions."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.INTERNAL_ERROR,
            message="Internal error",
        )

        assert response["error"]["code"] == MCPErrorCodes.INTERNAL_ERROR

    def test_policy_violation_scenario(self):
        """Test Gatekit policy violation error."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.SECURITY_VIOLATION,
            message="Security violation: Operation not allowed",
            data={
                "handler": "file_access",
                "action": "read",
                "resource": "/etc/passwd",
            },
        )

        assert response["error"]["code"] == MCPErrorCodes.SECURITY_VIOLATION
        assert response["error"]["data"]["handler"] == "file_access"

    def test_upstream_unavailable_scenario(self):
        """Test upstream server unavailable error."""
        response = create_error_response_dict(
            request_id="req-1",
            code=MCPErrorCodes.UPSTREAM_UNAVAILABLE,
            message="Upstream server unavailable",
            data={"reason": "Connection refused"},
        )

        assert response["error"]["code"] == MCPErrorCodes.UPSTREAM_UNAVAILABLE
        assert response["error"]["data"]["reason"] == "Connection refused"


class TestErrorResponseFormat:
    """Test that error responses follow JSON-RPC 2.0 format exactly."""

    def test_error_response_structure(self):
        """Test that error response has correct structure."""
        response = create_error_response_dict(
            request_id="test", code=MCPErrorCodes.INTERNAL_ERROR, message="Test error"
        )

        # Must have these fields
        assert "jsonrpc" in response
        assert "id" in response
        assert "error" in response

        # Must not have result field
        assert "result" not in response

        # Error object must have these fields
        assert "code" in response["error"]
        assert "message" in response["error"]

        # Values must be correct
        assert response["jsonrpc"] == "2.0"

    def test_error_dict_structure(self):
        """Test that error dictionary has correct structure."""
        error_dict = create_error_dict(
            code=MCPErrorCodes.INVALID_REQUEST, message="Invalid request"
        )

        # Must have these fields
        assert "code" in error_dict
        assert "message" in error_dict

        # Should not have extra fields when data is None
        assert len(error_dict) == 2

    def test_error_dict_with_data_structure(self):
        """Test error dictionary structure when data is included."""
        error_dict = create_error_dict(
            code=MCPErrorCodes.INVALID_PARAMS,
            message="Invalid params",
            data={"field": "value"},
        )

        # Must have these fields
        assert "code" in error_dict
        assert "message" in error_dict
        assert "data" in error_dict

        # Should have exactly 3 fields
        assert len(error_dict) == 3


class TestSerializeError:
    """Test serialize_error utility function."""

    def test_serialize_mcp_error_object(self):
        """Test serializing an MCPError object."""
        from gatekit.protocol.messages import MCPError
        from gatekit.protocol.errors import serialize_error

        error = MCPError(
            code=-32600, message="Invalid Request", data={"detail": "missing field"}
        )

        result = serialize_error(error)

        assert result == {
            "code": -32600,
            "message": "Invalid Request",
            "data": {"detail": "missing field"},
        }

    def test_serialize_error_dict(self):
        """Test serializing an error dictionary."""
        from gatekit.protocol.errors import serialize_error

        error_dict = {"code": -32601, "message": "Method not found", "data": None}

        result = serialize_error(error_dict)

        # Should only include non-None fields
        assert result == {"code": -32601, "message": "Method not found"}

    def test_serialize_error_dict_ignores_extra_fields(self):
        """Test that extra fields in error dict are silently ignored."""
        from gatekit.protocol.errors import serialize_error

        error_dict = {
            "code": -32602,
            "message": "Invalid params",
            "data": {"detail": "type error"},
            "extra_field": "should be ignored",
            "another_extra": 123,
        }

        result = serialize_error(error_dict)

        # Should only have standard JSON-RPC error fields
        assert result == {
            "code": -32602,
            "message": "Invalid params",
            "data": {"detail": "type error"},
        }

    def test_serialize_error_dict_missing_code_raises(self):
        """Test that missing code field raises ValueError."""
        from gatekit.protocol.errors import serialize_error

        error_dict = {"message": "Test message"}

        with pytest.raises(ValueError, match="missing required 'code' field"):
            serialize_error(error_dict)

    def test_serialize_error_dict_missing_message_raises(self):
        """Test that missing message field raises ValueError."""
        from gatekit.protocol.errors import serialize_error

        error_dict = {"code": -32600}

        with pytest.raises(ValueError, match="missing required 'message' field"):
            serialize_error(error_dict)

    def test_serialize_error_invalid_type_raises(self):
        """Test that invalid error type raises TypeError."""
        from gatekit.protocol.errors import serialize_error

        with pytest.raises(
            TypeError, match="Error must be MCPError object or dictionary"
        ):
            serialize_error("invalid error type")
