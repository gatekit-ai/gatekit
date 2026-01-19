"""MCP protocol message types and data structures.

This module defines the core message types for the Model Context Protocol (MCP)
following JSON-RPC 2.0 specification.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union, TypedDict

# JSON type aliases for cleaner type hints
JSONPrimitive = Union[str, int, float, bool, None]
JSONValue = Union[JSONPrimitive, Dict[str, "JSONValue"], List["JSONValue"]]
JSONObject = Dict[str, JSONValue]

# JSON-RPC ID type (string or integer only, no float per best practices)
RequestID = Union[str, int]


# TypedDict definitions for structured dictionaries
class ErrorObject(TypedDict, total=False):
    """Typed dictionary for JSON-RPC error objects."""

    code: int
    message: str
    data: Any


class RequestDict(TypedDict, total=False):
    """Typed dictionary for JSON-RPC request messages."""

    jsonrpc: str
    method: str
    id: RequestID
    params: Union[Dict[str, Any], List[Any]]
    sender_context: Any


class ResponseDict(TypedDict, total=False):
    """Typed dictionary for JSON-RPC response messages."""

    jsonrpc: str
    id: Optional[RequestID]
    result: Any
    error: ErrorObject
    sender_context: Any


class NotificationDict(TypedDict, total=False):
    """Typed dictionary for JSON-RPC notification messages."""

    jsonrpc: str
    method: str
    params: Union[Dict[str, Any], List[Any]]
    sender_context: Any


class MessageSender(Enum):
    """Enumeration of possible message senders in MCP communication.

    Values:
        CLIENT: Message originates from the MCP client
        SERVER: Message originates from the MCP server
    """

    CLIENT = "client"
    SERVER = "server"

    def __str__(self) -> str:
        """Return the string value of the sender."""
        return self.value


@dataclass
class SenderContext:
    """Context information about the message sender.

    Attributes:
        sender: The type of sender (MessageSender enum)
        identifier: Optional unique identifier for the sender instance
        metadata: Additional metadata about the sender (always a dict, may be empty)
    """

    sender: MessageSender
    identifier: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPRequest:
    """MCP request message following JSON-RPC 2.0 format.

    Attributes:
        jsonrpc: JSON-RPC version, must be "2.0"
        method: The method name to invoke
        id: Request identifier (string or integer)
        params: Optional parameters for the method call
        sender_context: Optional context information about the sender
    """

    jsonrpc: str
    method: str
    id: RequestID
    params: Optional[Union[Dict[str, Any], List[Any]]] = None
    sender_context: Optional[SenderContext] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPRequest":
        """Create MCPRequest from dictionary."""
        sender_context = data.get("sender_context")
        if sender_context is not None and isinstance(sender_context, dict):
            # Normalize dict to SenderContext if it has the right shape
            if "sender" in sender_context:
                sender_enum = (
                    MessageSender.CLIENT
                    if sender_context["sender"] == "client"
                    else MessageSender.SERVER
                )
                sender_context = SenderContext(
                    sender=sender_enum,
                    identifier=sender_context.get("identifier"),
                    metadata=sender_context.get("metadata") or {},
                )

        return cls(
            jsonrpc=data["jsonrpc"],
            method=data["method"],
            id=data["id"],
            params=data.get("params"),
            sender_context=sender_context,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"jsonrpc": self.jsonrpc, "method": self.method, "id": self.id}
        if self.params is not None:
            result["params"] = self.params
        if self.sender_context is not None:
            result["sender_context"] = self.sender_context
        return result


@dataclass
class MCPResponse:
    """MCP response message following JSON-RPC 2.0 format.

    Attributes:
        jsonrpc: JSON-RPC version, must be "2.0"
        id: Request identifier matching the original request
        result: Method result on success (mutually exclusive with error)
        error: Error information on failure (mutually exclusive with result)
        sender_context: Optional context information about the sender
    """

    jsonrpc: str
    id: Optional[RequestID]
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    sender_context: Optional[SenderContext] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPResponse":
        """Create MCPResponse from dictionary."""
        sender_context = data.get("sender_context")
        if sender_context is not None and isinstance(sender_context, dict):
            # Normalize dict to SenderContext if it has the right shape
            if "sender" in sender_context:
                sender_enum = (
                    MessageSender.CLIENT
                    if sender_context["sender"] == "client"
                    else MessageSender.SERVER
                )
                sender_context = SenderContext(
                    sender=sender_enum,
                    identifier=sender_context.get("identifier"),
                    metadata=sender_context.get("metadata") or {},
                )

        return cls(
            jsonrpc=data["jsonrpc"],
            id=data.get("id"),
            result=data.get("result"),
            error=data.get("error"),
            sender_context=sender_context,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.result is not None:
            result["result"] = self.result
        if self.error is not None:
            result["error"] = self.error
        if self.sender_context is not None:
            result["sender_context"] = self.sender_context
        return result


@dataclass
class MCPNotification:
    """MCP notification message following JSON-RPC 2.0 format.

    Notifications are one-way messages that do not require a response.
    They do not have an 'id' field as per JSON-RPC 2.0 specification.

    Attributes:
        jsonrpc: JSON-RPC version, must be "2.0"
        method: The notification method name
        params: Optional parameters for the notification
        sender_context: Optional context information about the sender
    """

    jsonrpc: str
    method: str
    params: Optional[Union[Dict[str, Any], List[Any]]] = None
    sender_context: Optional[SenderContext] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPNotification":
        """Create MCPNotification from dictionary."""
        sender_context = data.get("sender_context")
        if sender_context is not None and isinstance(sender_context, dict):
            # Normalize dict to SenderContext if it has the right shape
            if "sender" in sender_context:
                sender_enum = (
                    MessageSender.CLIENT
                    if sender_context["sender"] == "client"
                    else MessageSender.SERVER
                )
                sender_context = SenderContext(
                    sender=sender_enum,
                    identifier=sender_context.get("identifier"),
                    metadata=sender_context.get("metadata") or {},
                )

        return cls(
            jsonrpc=data["jsonrpc"],
            method=data["method"],
            params=data.get("params"),
            sender_context=sender_context,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params is not None:
            result["params"] = self.params
        if self.sender_context is not None:
            result["sender_context"] = self.sender_context
        return result


@dataclass
class MCPError:
    """MCP error information structure.

    Attributes:
        code: Error code (integer)
        message: Error message (string)
        data: Optional additional error data
    """

    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = self.data
        return result
