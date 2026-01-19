"""Gatekit Protocol Module - MCP message types and protocol handling.

This module provides JSON-RPC 2.0 compliant message types and validation
for the Model Context Protocol (MCP).
"""

from .messages import (
    MessageSender,
    SenderContext,
    MCPRequest,
    MCPResponse,
    MCPNotification,
    MCPError,
    RequestID,
    JSONValue,
    JSONObject,
    JSONPrimitive,
    # TypedDicts for better type safety
    ErrorObject,
    RequestDict,
    ResponseDict,
    NotificationDict,
)

from .validation import (
    MessageValidator,
    ValidationError,
    ValidationErrorType,
    ValidationLimits,
)

from .errors import (
    MCPErrorCodes,
    StartupError,
    AuditingFailureError,
    create_error_response,
    create_error_response_dict,
    create_error_dict,
    serialize_error,
)

__all__ = [
    # Message types
    "MessageSender",
    "SenderContext",
    "MCPRequest",
    "MCPResponse",
    "MCPNotification",
    "MCPError",
    # Type aliases
    "RequestID",
    "JSONValue",
    "JSONObject",
    "JSONPrimitive",
    # TypedDicts for type safety
    "ErrorObject",
    "RequestDict",
    "ResponseDict",
    "NotificationDict",
    # Validation
    "MessageValidator",
    "ValidationError",
    "ValidationErrorType",
    "ValidationLimits",
    # Error handling
    "MCPErrorCodes",
    "StartupError",
    "AuditingFailureError",
    "create_error_response",
    "create_error_response_dict",
    "create_error_dict",
    "serialize_error",
]
