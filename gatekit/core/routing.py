"""Core routing infrastructure for Gatekit.

This module implements the boundary translation pattern for routing,
ensuring namespacing is parsed once at ingress and preserved throughout
the request lifecycle.
"""

from dataclasses import dataclass
from typing import Optional, Union
import re
from gatekit.protocol.messages import MCPRequest, MCPResponse
from gatekit.protocol.errors import MCPErrorCodes, create_error_response


@dataclass
class RoutedRequest:
    """Carries request and routing context through the system as a unit.

    This class encapsulates both the clean request for processing and
    the routing metadata needed to deliver it and format responses.
    """

    request: MCPRequest  # Clean, denamespaced request for processing
    target_server: Optional[str]  # Target server (None for broadcasts/single-server)
    namespaced_name: Optional[str]  # Original namespaced name for response formatting

    def update_request(self, new_request: MCPRequest) -> "RoutedRequest":
        """Create new RoutedRequest with updated request but same routing context.

        Enforces invariants: request ID and method must remain constant.
        Allows plugins to transform routing parameters (e.g., tool names) as they are trusted components.
        """
        # Enforce invariants - ID and method must remain constant
        if new_request.id != self.request.id:
            raise ValueError(
                f"Cannot change request ID from {self.request.id} to {new_request.id}"
            )
        if new_request.method != self.request.method:
            raise ValueError(
                f"Cannot change request method from {self.request.method} to {new_request.method}"
            )

        # Note: We intentionally allow plugins to modify routing-critical params (name, uri)
        # because plugins are trusted components of Gatekit. This enables legitimate
        # transformations like tool renaming by the tool_manager middleware.
        # The original namespaced_name is preserved for error message formatting.

        return RoutedRequest(
            request=new_request,
            target_server=self.target_server,
            namespaced_name=self.namespaced_name,
        )


def parse_incoming_request(request: MCPRequest) -> Union[RoutedRequest, MCPResponse]:
    """Parse client request once at ingress - single point of namespace extraction.

    Returns:
        RoutedRequest if parsing succeeds
        MCPResponse with error if validation fails
    """
    if request.method == "tools/call" and request.params:
        tool_name = request.params.get("name", "")
        if not tool_name:
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCodes.INVALID_PARAMS,
                message="Tool call missing required 'name' parameter",
            )

        if "__" not in tool_name:
            # ALL tool calls must be namespaced - no special handling for single server
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCodes.INVALID_PARAMS,
                message=f"Tool '{tool_name}' is not properly namespaced. "
                f"All tool calls must use 'server__tool' format (e.g., 'filesystem__{tool_name}')",
            )

        parts = tool_name.split("__", 1)  # Split only on first __
        server_name = parts[0]
        clean_tool = parts[1]

        # Create clean request
        clean_params = {**request.params, "name": clean_tool}
        clean_request = MCPRequest(
            jsonrpc=request.jsonrpc,
            method=request.method,
            id=request.id,
            params=clean_params,
            sender_context=request.sender_context,
        )

        return RoutedRequest(
            request=clean_request,
            target_server=server_name,
            namespaced_name=tool_name,  # Clear field name
        )

    elif request.method == "resources/read" and request.params:
        resource_uri = request.params.get("uri", "")
        if not resource_uri:
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCodes.INVALID_PARAMS,
                message="Resource call missing required 'uri' parameter",
            )

        if "__" not in resource_uri:
            # ALL resource calls must be namespaced - no special handling for single server
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCodes.INVALID_PARAMS,
                message=f"Resource '{resource_uri}' is not properly namespaced. "
                f"All resource calls must use 'server__uri' format",
            )

        parts = resource_uri.split("__", 1)  # Split only on first __
        server_name = parts[0]
        clean_uri = parts[1]

        # Create clean request
        clean_params = {**request.params, "uri": clean_uri}
        clean_request = MCPRequest(
            jsonrpc=request.jsonrpc,
            method=request.method,
            id=request.id,
            params=clean_params,
            sender_context=request.sender_context,
        )

        return RoutedRequest(
            request=clean_request,
            target_server=server_name,
            namespaced_name=resource_uri,
        )

    elif request.method == "prompts/get" and request.params:
        prompt_name = request.params.get("name", "")
        if not prompt_name:
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCodes.INVALID_PARAMS,
                message="Prompt get missing required 'name' parameter",
            )

        if "__" not in prompt_name:
            # ALL prompt gets must be namespaced - no special handling for single server
            return create_error_response(
                request_id=request.id,
                code=MCPErrorCodes.INVALID_PARAMS,
                message=f"Prompt '{prompt_name}' is not properly namespaced. "
                f"All prompt gets must use 'server__prompt' format",
            )

        parts = prompt_name.split("__", 1)  # Split only on first __
        server_name = parts[0]
        clean_prompt = parts[1]

        # Create clean request
        clean_params = {**request.params, "name": clean_prompt}
        clean_request = MCPRequest(
            jsonrpc=request.jsonrpc,
            method=request.method,
            id=request.id,
            params=clean_params,
            sender_context=request.sender_context,
        )

        return RoutedRequest(
            request=clean_request,
            target_server=server_name,
            namespaced_name=prompt_name,
        )

    # All other methods (broadcast methods like tools/list, initialize, etc.)
    # These don't have namespacing and route to all servers
    return RoutedRequest(
        request=request, target_server=None, namespaced_name=None  # Will be broadcast
    )


def prepare_outgoing_response(
    response: MCPResponse, routed: RoutedRequest
) -> MCPResponse:
    """Apply namespace to outgoing response if needed.

    Uses the preserved namespaced_name from the RoutedRequest to
    restore namespacing in error messages or other response fields.
    Uses word boundaries to avoid partial matches (e.g., 'sum' in 'summary').
    """
    if not routed.namespaced_name:
        return response  # No namespacing needed

    # Re-namespace error messages that reference the tool
    if response.error and routed.request.params:
        # Get the clean name from the request params
        clean_name = routed.request.params.get("name") or routed.request.params.get(
            "uri"
        )

        if clean_name:
            error_message = response.error.get("message", "")

            # Use regex with word boundaries to avoid partial matches
            # This ensures we don't replace "sum" in "summary" for example
            # NOTE: \b has limitations with URIs and non-word characters (e.g., dots, slashes)
            # Works well for typical error messages like "Tool foo not found" but may miss
            # edge cases like "foo." or adjacent punctuation. If issues arise, consider
            # tokenization or explicit delimiters instead of word boundaries.
            pattern = r"\b" + re.escape(clean_name) + r"\b"

            # Check if the clean name appears in the message
            if re.search(pattern, error_message):
                # Replace with word boundaries
                new_message = re.sub(pattern, routed.namespaced_name, error_message)

                # Create a new error dict with updated message
                new_error = {**response.error}
                new_error["message"] = new_message

                # Create new response with updated error
                return MCPResponse(
                    jsonrpc=response.jsonrpc,
                    id=response.id,
                    result=response.result,
                    error=new_error,
                )

    return response
