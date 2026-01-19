"""Unit tests for core routing infrastructure."""

from gatekit.core.routing import (
    RoutedRequest,
    parse_incoming_request,
    prepare_outgoing_response,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse
from gatekit.protocol.errors import MCPErrorCodes


class TestRoutedRequest:
    """Test RoutedRequest data class."""

    def test_routed_request_preserves_context(self):
        """Verify RoutedRequest maintains context through updates."""
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id=1, params={"name": "tool"}
        )
        routed = RoutedRequest(request, "server1", "server1__tool")

        # Create modified request
        modified_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "modified": True},
        )

        # Update request
        updated = routed.update_request(modified_request)

        # Verify context is preserved
        assert updated.target_server == "server1"
        assert updated.namespaced_name == "server1__tool"
        assert updated.request == modified_request

        # Verify original is unchanged
        assert routed.request == request


class TestParseIncomingRequest:
    """Test parse_incoming_request function."""

    def test_parse_handles_double_underscore_in_names(self):
        """Verify only first __ is used for parsing."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "server__tool__with__underscores"},
        )
        routed = parse_incoming_request(request)

        assert routed.target_server == "server"
        assert routed.request.params["name"] == "tool__with__underscores"
        assert routed.namespaced_name == "server__tool__with__underscores"

    def test_parse_tools_call_with_namespace(self):
        """Test parsing tools/call with namespaced tool."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "server1__my_tool", "arguments": {"key": "value"}},
        )
        routed = parse_incoming_request(request)

        assert routed.target_server == "server1"
        assert routed.request.params["name"] == "my_tool"
        assert routed.request.params["arguments"] == {"key": "value"}
        assert routed.namespaced_name == "server1__my_tool"

    def test_parse_tools_call_without_namespace_returns_error(self):
        """Test that tools/call without namespace returns error response."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "my_tool", "arguments": {"key": "value"}},
        )

        result = parse_incoming_request(request)

        assert isinstance(result, MCPResponse)
        assert result.error is not None
        assert result.error["code"] == MCPErrorCodes.INVALID_PARAMS
        assert "my_tool" in result.error["message"]
        assert "not properly namespaced" in result.error["message"]
        assert "server__tool" in result.error["message"]

    def test_parse_resources_call_with_namespace(self):
        """Test parsing resources/read with namespaced URI."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="resources/read",
            id=1,
            params={"uri": "server2__file:///path/to/resource"},
        )
        routed = parse_incoming_request(request)

        assert routed.target_server == "server2"
        assert routed.request.params["uri"] == "file:///path/to/resource"
        assert routed.namespaced_name == "server2__file:///path/to/resource"

    def test_parse_resources_call_without_namespace_returns_error(self):
        """Test that resources/read without namespace returns error response."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="resources/read",
            id=1,
            params={"uri": "file:///path/to/resource"},
        )

        result = parse_incoming_request(request)

        assert isinstance(result, MCPResponse)
        assert result.error is not None
        assert result.error["code"] == MCPErrorCodes.INVALID_PARAMS
        assert "file:///path/to/resource" in result.error["message"]
        assert "not properly namespaced" in result.error["message"]
        assert "server__uri" in result.error["message"]

    def test_parse_prompts_get_with_namespace(self):
        """Test parsing prompts/get with namespaced prompt."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="prompts/get",
            id=1,
            params={"name": "server3__my_prompt"},
        )
        routed = parse_incoming_request(request)

        assert routed.target_server == "server3"
        assert routed.request.params["name"] == "my_prompt"
        assert routed.namespaced_name == "server3__my_prompt"

    def test_parse_prompts_get_without_namespace_returns_error(self):
        """Test that prompts/get without namespace returns error response."""
        request = MCPRequest(
            jsonrpc="2.0", method="prompts/get", id=1, params={"name": "my_prompt"}
        )

        result = parse_incoming_request(request)

        assert isinstance(result, MCPResponse)
        assert result.error is not None
        assert result.error["code"] == MCPErrorCodes.INVALID_PARAMS
        assert "my_prompt" in result.error["message"]
        assert "not properly namespaced" in result.error["message"]
        assert "server__prompt" in result.error["message"]

    def test_parse_non_routable_method(self):
        """Test parsing methods that don't support namespacing."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="initialize",
            id=1,
            params={"protocolVersion": "2024-11-05"},
        )
        routed = parse_incoming_request(request)

        assert routed.target_server is None
        assert routed.request == request
        assert routed.namespaced_name is None

    def test_parse_preserves_sender_context(self):
        """Test that sender_context is preserved."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "server__tool"},
            sender_context={"client": "test"},
        )
        routed = parse_incoming_request(request)

        assert routed.request.sender_context == {"client": "test"}


class TestPrepareOutgoingResponse:
    """Test prepare_outgoing_response function."""

    def test_prepare_response_no_namespacing_needed(self):
        """Test response preparation when no namespacing is needed."""
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id=1, params={"name": "tool"}
        )
        routed = RoutedRequest(request, None, None)

        response = MCPResponse(jsonrpc="2.0", id=1, result={"success": True})

        prepared = prepare_outgoing_response(response, routed)
        assert prepared == response  # Should be unchanged

    def test_prepare_response_renamespace_error_message(self):
        """Test that error messages are re-namespaced."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "my_tool"},  # Clean name
        )
        routed = RoutedRequest(request, "server1", "server1__my_tool")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            error={"code": -32603, "message": "Tool my_tool not found"},
        )

        prepared = prepare_outgoing_response(response, routed)
        assert prepared.error["message"] == "Tool server1__my_tool not found"
        assert prepared.error["code"] == -32603

    def test_prepare_response_error_without_tool_reference(self):
        """Test error messages that don't reference the tool."""
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id=1, params={"name": "my_tool"}
        )
        routed = RoutedRequest(request, "server1", "server1__my_tool")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            error={"code": -32603, "message": "Internal server error"},
        )

        prepared = prepare_outgoing_response(response, routed)
        assert prepared.error["message"] == "Internal server error"  # Unchanged

    def test_prepare_response_success_result(self):
        """Test that success responses are not modified."""
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id=1, params={"name": "my_tool"}
        )
        routed = RoutedRequest(request, "server1", "server1__my_tool")

        response = MCPResponse(jsonrpc="2.0", id=1, result={"output": "Success"})

        prepared = prepare_outgoing_response(response, routed)
        assert prepared == response  # Should be unchanged

    def test_prepare_response_resource_uri_in_error(self):
        """Test re-namespacing resource URIs in error messages."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="resources/read",
            id=1,
            params={"uri": "file:///path"},  # Clean URI
        )
        routed = RoutedRequest(request, "server2", "server2__file:///path")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            error={"code": -32603, "message": "Resource file:///path not accessible"},
        )

        prepared = prepare_outgoing_response(response, routed)
        assert (
            prepared.error["message"] == "Resource server2__file:///path not accessible"
        )

    def test_prepare_response_prompt_name_in_error(self):
        """Test re-namespacing prompt names in error messages."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="prompts/get",
            id=1,
            params={"name": "my_prompt"},  # Clean name
        )
        routed = RoutedRequest(request, "server3", "server3__my_prompt")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            error={"code": -32603, "message": "Prompt my_prompt does not exist"},
        )

        prepared = prepare_outgoing_response(response, routed)
        assert prepared.error["message"] == "Prompt server3__my_prompt does not exist"
