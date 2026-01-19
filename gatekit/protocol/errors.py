"""MCP protocol error codes and error response utilities.

This module defines error codes following JSON-RPC 2.0 specification
and utilities for creating error responses.
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Dict, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .messages import MCPResponse, MCPError, RequestID


class MCPErrorCodes(IntEnum):
    """Standard JSON-RPC 2.0 and Gatekit-specific error codes."""

    # Standard JSON-RPC 2.0 error codes (-32768 to -32000)
    PARSE_ERROR = -32700  # Invalid JSON was received by the server
    INVALID_REQUEST = -32600  # The JSON sent is not a valid Request object
    METHOD_NOT_FOUND = -32601  # The method does not exist / is not available
    INVALID_PARAMS = -32602  # Invalid method parameter(s)
    INTERNAL_ERROR = -32603  # Internal JSON-RPC error

    # Gatekit-specific error codes (-32099 to -32000)
    SECURITY_VIOLATION = -32000  # Request blocked by security handler
    CONFIGURATION_ERROR = -32001  # Configuration file or validation error
    PLUGIN_LOADING_ERROR = -32002  # Plugin initialization or handler error
    PERMISSION_ERROR = -32003  # File system permission error
    UPSTREAM_UNAVAILABLE = -32004  # Upstream server is unavailable
    AUDITING_FAILURE = -32005  # Critical auditing plugin failure


@dataclass
class StartupError:
    """Represents a startup error with user-friendly information.

    This is used to communicate startup failures to MCP clients with
    actionable error messages and fix instructions.
    """

    code: int
    message: str
    details: str
    fix_instructions: str
    error_type: Optional[str] = None
    error_context: Optional[Dict[str, Any]] = None


class AuditingFailureError(Exception):
    """Exception raised when a critical auditing plugin fails.

    This exception is raised when an auditing plugin marked as critical
    fails to log a request or response. It includes guidance for users
    on how to configure non-critical auditing if appropriate.
    """

    pass


def create_error_dict(
    code: int, message: str, data: Optional[Any] = None
) -> Dict[str, Any]:
    """Create an error dictionary for JSON-RPC 2.0 error responses.

    Args:
        code: Error code
        message: Error message
        data: Optional additional error data

    Returns:
        Dict: Error dictionary with code, message, and optional data
    """
    error_dict = {"code": code, "message": message}

    if data is not None:
        error_dict["data"] = data

    return error_dict


def create_error_response_dict(
    request_id: Optional[Union[str, int]],
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> Dict[str, Any]:
    """Create a JSON-RPC 2.0 error response as a dictionary.

    Args:
        request_id: ID from the original request (None only for parse/invalid request errors)
        code: Error code
        message: Error message
        data: Optional additional error data

    Returns:
        Dict: JSON-RPC 2.0 error response dictionary

    Note:
        Per JSON-RPC 2.0 specification, null id is only permitted for
        PARSE_ERROR (-32700) and INVALID_REQUEST (-32600) responses.
    """
    # Validate null id usage per JSON-RPC 2.0 spec
    if request_id is None and code not in (
        MCPErrorCodes.PARSE_ERROR,
        MCPErrorCodes.INVALID_REQUEST,
    ):
        raise ValueError(
            f"Null request_id only allowed for parse error or invalid request, got code: {code}"
        )

    error_dict = create_error_dict(code, message, data)

    return {"jsonrpc": "2.0", "id": request_id, "error": error_dict}


def create_error_response(
    request_id: Optional["RequestID"],
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> "MCPResponse":
    """Create a JSON-RPC 2.0 error response as an MCPResponse object.

    Args:
        request_id: ID from the original request (None only for parse/invalid request errors)
        code: Error code
        message: Error message
        data: Optional additional error data

    Returns:
        MCPResponse: Error response object

    Note:
        This function imports MCPResponse lazily to avoid circular imports.
        The response will have an error field and no result field, ensuring
        mutual exclusivity as required by JSON-RPC 2.0.
        Per JSON-RPC 2.0 specification, null id is only permitted for
        PARSE_ERROR (-32700) and INVALID_REQUEST (-32600) responses.
    """
    from .messages import MCPResponse

    # Validate null id usage per JSON-RPC 2.0 spec
    if request_id is None and code not in (
        MCPErrorCodes.PARSE_ERROR,
        MCPErrorCodes.INVALID_REQUEST,
    ):
        raise ValueError(
            f"Null request_id only allowed for parse error or invalid request, got code: {code}"
        )

    error_dict = create_error_dict(code, message, data)

    return MCPResponse(jsonrpc="2.0", id=request_id, error=error_dict)


def serialize_error(error: Union["MCPError", Dict[str, Any]]) -> Dict[str, Any]:
    """Serialize an error to a dictionary for JSON transmission.

    Args:
        error: Either an MCPError object or an error dictionary

    Returns:
        Dict: Serialized error dictionary containing only 'code', 'message',
              and optional 'data' fields. Extra fields in input dictionaries
              are silently ignored to ensure JSON-RPC 2.0 compliance.

    Raises:
        TypeError: If error is not an MCPError or dictionary
        ValueError: If error dictionary is missing required fields
    """
    if hasattr(error, "to_dict"):
        # MCPError object
        return error.to_dict()
    elif isinstance(error, dict):
        # Validate dictionary structure
        if "code" not in error:
            raise ValueError("Error dictionary missing required 'code' field")
        if "message" not in error:
            raise ValueError("Error dictionary missing required 'message' field")
        if not isinstance(error["code"], int):
            raise ValueError("Error code must be an integer")
        if not isinstance(error["message"], str):
            raise ValueError("Error message must be a string")

        # Return validated copy
        result = {"code": error["code"], "message": error["message"]}
        if "data" in error and error["data"] is not None:
            result["data"] = error["data"]
        return result
    else:
        raise TypeError(
            f"Error must be MCPError object or dictionary, got: {type(error)}"
        )
