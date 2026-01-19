"""MCP protocol message validation.

This module provides validation functionality for MCP protocol messages
following JSON-RPC 2.0 specification.
"""

import json
import re
from enum import Enum
from typing import Any, List, Union, Optional

from .messages import (
    MCPRequest,
    MCPResponse,
    MCPNotification,
    SenderContext,
    MessageSender,
)
from .errors import MCPErrorCodes
from dataclasses import dataclass


class ValidationErrorType(Enum):
    """Enumeration of validation error types for consistent error classification."""

    INVALID_STRUCTURE = "invalid_structure"
    INVALID_BATCH = "invalid_batch"
    MALFORMED_BATCH_ITEM = "malformed_batch_item"
    MALFORMED_MESSAGE = "malformed_message"
    UNKNOWN_TYPE = "unknown_type"
    MISSING_FIELD = "missing_field"
    INVALID_VERSION = "invalid_version"
    INVALID_METHOD = "invalid_method"
    INVALID_ID = "invalid_id"
    INVALID_PARAMS = "invalid_params"
    INVALID_RESPONSE = "invalid_response"
    INVALID_NOTIFICATION = "invalid_notification"
    INVALID_ERROR = "invalid_error"
    INVALID_SENDER_CONTEXT = "invalid_sender_context"
    SIZE_LIMIT = "size_limit"
    DEPTH_LIMIT = "depth_limit"
    WIDTH_LIMIT = "width_limit"
    JSON_ERROR = "json_error"
    PARSE_ERROR = "parse_error"

    def __str__(self) -> str:
        """Return the string value of the error type."""
        return self.value


class ValidationError(Exception):
    """Raised when message validation fails.

    Attributes:
        message: Error message
        error_type: Optional categorization of the error type
        cause: Optional original exception that caused this error
    """

    def __init__(
        self,
        message: str,
        error_type: Optional[Union[ValidationErrorType, str]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        # Accept ValidationErrorType enum or string, normalize to enum
        if isinstance(error_type, str):
            try:
                self.error_type = ValidationErrorType(error_type)
            except ValueError:
                # For unknown string values, keep as is
                self.error_type = error_type
        else:
            self.error_type = error_type
        self.cause = cause


@dataclass
class ValidationLimits:
    """Configuration object for message validation limits.

    Attributes:
        max_message_size: Maximum message size in bytes
        max_depth: Maximum nesting depth for structures (starting from 0 for root object)
                   With default value of 64, maximum effective depth is 64 levels including root
        max_object_keys: Maximum number of keys in a single object
        max_batch_element_size: Maximum size for individual batch elements in bytes
    """

    max_message_size: int = 1024 * 1024  # 1MB default
    max_depth: int = 64
    max_object_keys: int = 1000
    max_batch_element_size: int = 256 * 1024  # 256KB default

    def __post_init__(self):
        """Validate limits are sensible."""
        if self.max_message_size <= 0:
            raise ValueError("max_message_size must be positive")
        if self.max_depth <= 0:
            raise ValueError("max_depth must be positive")
        if self.max_object_keys <= 0:
            raise ValueError("max_object_keys must be positive")
        if self.max_batch_element_size <= 0:
            raise ValueError("max_batch_element_size must be positive")
        if self.max_batch_element_size > self.max_message_size:
            raise ValueError("max_batch_element_size cannot exceed max_message_size")


class MessageValidator:
    """Validates MCP protocol messages according to JSON-RPC 2.0 specification."""

    # Regex for validating method names (no control chars, no leading/trailing whitespace)
    METHOD_NAME_PATTERN = re.compile(
        r"^[^\x00-\x1F\x7F\s]+[^\x00-\x1F\x7F]*[^\x00-\x1F\x7F\s]+$|^[^\x00-\x1F\x7F\s]+$"
    )

    def __init__(self, limits: Optional[ValidationLimits] = None):
        """Initialize validator with configuration.

        Args:
            limits: Validation limits configuration object
        """
        self.limits = limits or ValidationLimits()

    def determine_message_type(self, data: dict) -> str:
        """Determine the type of JSON-RPC message.

        Args:
            data: Dictionary containing message data

        Returns:
            str: One of 'request', 'response', 'notification', or 'malformed'

        Raises:
            ValidationError: If message type cannot be determined
        """
        if not isinstance(data, dict):
            raise ValidationError(
                "Message must be a dictionary",
                error_type=ValidationErrorType.INVALID_STRUCTURE,
            )

        has_id = "id" in data
        has_method = "method" in data
        has_result = "result" in data
        has_error = "error" in data

        # Check for malformed messages (suspicious combinations)
        if has_method and (has_result or has_error):
            # Has both request-like and response-like fields
            raise ValidationError(
                "Message has both request fields (method) and response fields (result/error)",
                error_type=ValidationErrorType.MALFORMED_MESSAGE,
            )

        # Check for response (has id and either result or error)
        if has_id and (has_result or has_error):
            return "response"

        # Check for notification (has method but no id)
        if has_method and not has_id:
            return "notification"

        # Check for request (has method and id)
        if has_method and has_id:
            return "request"

        raise ValidationError(
            "Unable to determine message type",
            error_type=ValidationErrorType.UNKNOWN_TYPE,
        )

    def validate_request(self, data: dict) -> MCPRequest:
        """Validate and convert dict to MCPRequest.

        Args:
            data: Dictionary containing request data

        Returns:
            MCPRequest: Validated request object

        Raises:
            ValidationError: If validation fails
        """
        # Validate input type
        if data is None or not isinstance(data, dict):
            raise ValidationError(
                "Invalid message data", error_type=ValidationErrorType.INVALID_STRUCTURE
            )

        # Check message size and depth
        self._ensure_size_limit(data)
        self._check_depth(data)

        self._validate_required_fields(data, ["jsonrpc", "method", "id"])
        self._validate_jsonrpc_version(data.get("jsonrpc"))
        self._validate_method_name(data.get("method"))
        self._validate_request_id(data.get("id"))

        # Optional params validation - must be dict or array or omitted
        params = data.get("params")
        if params is not None and not isinstance(params, (dict, list)):
            raise ValidationError(
                "Request params must be an object, array, or omitted",
                error_type=ValidationErrorType.INVALID_PARAMS,
            )

        # Validate and populate sender context if present
        validated_data = dict(data)
        if "sender_context" in data:
            validated_data["sender_context"] = self._validate_sender_context(
                data["sender_context"]
            )

        return MCPRequest.from_dict(validated_data)

    def validate_response(self, data: dict) -> MCPResponse:
        """Validate and convert dict to MCPResponse.

        Args:
            data: Dictionary containing response data

        Returns:
            MCPResponse: Validated response object

        Raises:
            ValidationError: If validation fails
        """
        if data is None or not isinstance(data, dict):
            raise ValidationError(
                "Invalid message data", error_type=ValidationErrorType.INVALID_STRUCTURE
            )

        # Check message size and depth
        self._ensure_size_limit(data)
        self._check_depth(data)

        self._validate_required_fields(data, ["jsonrpc", "id"])
        self._validate_jsonrpc_version(data.get("jsonrpc"))
        self._validate_response_id(data.get("id"))

        # Must have EXACTLY one of result or error
        has_result = "result" in data
        has_error = "error" in data

        if has_result == has_error:  # Both true or both false
            raise ValidationError(
                "Response must have exactly one of 'result' or 'error'",
                error_type=ValidationErrorType.INVALID_RESPONSE,
            )

        # Validate error object structure if present
        if has_error:
            self._validate_error_object(data["error"])

        # Validate ID null rules per JSON-RPC 2.0 spec
        response_id = data.get("id")
        if response_id is None:
            if has_result:
                raise ValidationError(
                    "Result response must have non-null id",
                    error_type=ValidationErrorType.INVALID_ID,
                )
            # has_error is guaranteed true here due to exactly-one-of check
            error_code = data["error"].get("code")
            if error_code not in (
                MCPErrorCodes.PARSE_ERROR,
                MCPErrorCodes.INVALID_REQUEST,
            ):
                raise ValidationError(
                    "Null id only permitted for parse error or invalid request responses",
                    error_type=ValidationErrorType.INVALID_ID,
                )

        return MCPResponse.from_dict(data)

    def validate_notification(self, data: dict) -> MCPNotification:
        """Validate and convert dict to MCPNotification.

        Args:
            data: Dictionary containing notification data

        Returns:
            MCPNotification: Validated notification object

        Raises:
            ValidationError: If validation fails
        """
        # Validate input type
        if data is None or not isinstance(data, dict):
            raise ValidationError(
                "Invalid message data", error_type=ValidationErrorType.INVALID_STRUCTURE
            )

        # Check message size and depth
        self._ensure_size_limit(data)
        self._check_depth(data)

        self._validate_required_fields(data, ["jsonrpc", "method"])
        self._validate_jsonrpc_version(data.get("jsonrpc"))
        self._validate_method_name(data.get("method"))

        # Notifications must NOT have an id field
        if "id" in data:
            raise ValidationError(
                "Notification must not have an id field",
                error_type=ValidationErrorType.INVALID_NOTIFICATION,
            )

        # Optional params validation - must be dict or array or omitted
        params = data.get("params")
        if params is not None and not isinstance(params, (dict, list)):
            raise ValidationError(
                "Notification params must be an object, array, or omitted",
                error_type=ValidationErrorType.INVALID_PARAMS,
            )

        # Validate and populate sender context if present
        validated_data = dict(data)
        if "sender_context" in data:
            validated_data["sender_context"] = self._validate_sender_context(
                data["sender_context"]
            )

        return MCPNotification.from_dict(validated_data)

    def validate_batch(self, data: Any) -> List[Union[MCPRequest, MCPNotification]]:
        """Validate a batch of requests/notifications.

        Args:
            data: List of request/notification dictionaries

        Returns:
            List of validated MCPRequest/MCPNotification objects

        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(data, list):
            raise ValidationError(
                "Batch must be an array", error_type=ValidationErrorType.INVALID_BATCH
            )

        if len(data) == 0:
            raise ValidationError(
                "Batch cannot be empty", error_type=ValidationErrorType.INVALID_BATCH
            )

        # Check overall batch size
        try:
            json_str = json.dumps(data)
            if len(json_str.encode("utf-8")) > self.limits.max_message_size:
                raise ValidationError(
                    f"Batch size exceeds maximum of {self.limits.max_message_size} bytes",
                    error_type=ValidationErrorType.SIZE_LIMIT,
                )
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"Invalid JSON in batch: {e}",
                error_type=ValidationErrorType.JSON_ERROR,
                cause=e,
            )

        results = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValidationError(
                    f"Batch item {i} must be an object",
                    error_type=ValidationErrorType.INVALID_BATCH,
                )

            # Check individual element size
            try:
                item_json = json.dumps(item)
                if len(item_json.encode("utf-8")) > self.limits.max_batch_element_size:
                    raise ValidationError(
                        f"Batch item {i} exceeds maximum element size of {self.limits.max_batch_element_size} bytes",
                        error_type=ValidationErrorType.SIZE_LIMIT,
                    )
            except (TypeError, ValueError) as e:
                if "exceeds maximum" not in str(e):
                    raise ValidationError(
                        f"Batch item {i} is not JSON serializable: {e}",
                        error_type=ValidationErrorType.JSON_ERROR,
                        cause=e,
                    )
                raise

            try:
                msg_type = self.determine_message_type(item)
                if msg_type == "request":
                    results.append(self.validate_request(item))
                elif msg_type == "notification":
                    results.append(self.validate_notification(item))
                else:
                    raise ValidationError(
                        f"Batch item {i} must be a request or notification",
                        error_type=ValidationErrorType.INVALID_BATCH,
                    )
            except ValidationError as e:
                # Preserve specific error types from malformed messages
                if e.error_type == ValidationErrorType.MALFORMED_MESSAGE:
                    raise ValidationError(
                        f"Batch item {i} is malformed: {e}",
                        error_type=ValidationErrorType.MALFORMED_BATCH_ITEM,
                        cause=e,
                    )
                # Re-raise with batch context
                raise ValidationError(
                    f"Batch item {i}: {e}",
                    error_type=ValidationErrorType.INVALID_BATCH,
                    cause=e,
                )

        return results

    def validate_json_string(self, json_str: str) -> dict:
        """Validate JSON string and parse to dict.

        Args:
            json_str: JSON string to validate

        Returns:
            dict: Parsed JSON data

        Raises:
            ValidationError: If JSON is invalid or too large
        """
        # Check message size
        if len(json_str.encode("utf-8")) > self.limits.max_message_size:
            raise ValidationError(
                f"Message size exceeds maximum of {self.limits.max_message_size} bytes",
                error_type=ValidationErrorType.SIZE_LIMIT,
            )

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValidationError(
                f"Invalid JSON: {e}",
                error_type=ValidationErrorType.PARSE_ERROR,
                cause=e,
            )

    # Helper methods

    def _ensure_size_limit(self, data: Any) -> None:
        """Check that message size is within limits.

        Args:
            data: Data to check

        Raises:
            ValidationError: If size exceeds limit or data is not JSON serializable
        """
        try:
            json_str = json.dumps(data)
            if len(json_str.encode("utf-8")) > self.limits.max_message_size:
                raise ValidationError(
                    f"Message size exceeds maximum of {self.limits.max_message_size} bytes",
                    error_type=ValidationErrorType.SIZE_LIMIT,
                )
        except (TypeError, ValueError) as e:
            # Don't silently ignore serialization failures - they indicate
            # non-serializable objects that would cause failures later
            raise ValidationError(
                f"Message contains non-JSON serializable data: {e}",
                error_type=ValidationErrorType.JSON_ERROR,
                cause=e,
            )

    def _check_depth(self, obj: Any, current_depth: int = 0) -> None:
        """Check that nested structure depth is within limits.

        Depth is calculated starting from 0 for the root object. With default
        max_depth=64, this allows structures up to 64 levels deep including root.

        Args:
            obj: Object to check
            current_depth: Current nesting depth (0 for root)

        Raises:
            ValidationError: If depth exceeds limit
        """
        if current_depth > self.limits.max_depth:
            raise ValidationError(
                f"Structure depth exceeds maximum of {self.limits.max_depth}",
                error_type=ValidationErrorType.DEPTH_LIMIT,
            )

        if isinstance(obj, dict):
            # Also check for excessively wide objects
            if len(obj) > self.limits.max_object_keys:
                raise ValidationError(
                    f"Object exceeds maximum of {self.limits.max_object_keys} keys",
                    error_type=ValidationErrorType.WIDTH_LIMIT,
                )
            for value in obj.values():
                self._check_depth(value, current_depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._check_depth(item, current_depth + 1)

    def _validate_required_fields(self, data: dict, required_fields: list) -> None:
        """Validate that all required fields are present.

        Args:
            data: Dictionary to check
            required_fields: List of required field names

        Raises:
            ValidationError: If a required field is missing
        """
        for field in required_fields:
            if field not in data:
                raise ValidationError(
                    f"Missing required field: {field}",
                    error_type=ValidationErrorType.MISSING_FIELD,
                )

    def _validate_jsonrpc_version(self, version: Any) -> None:
        """Validate JSON-RPC version.

        Args:
            version: Version value to validate

        Raises:
            ValidationError: If version is not "2.0"
        """
        if version != "2.0":
            raise ValidationError(
                "Invalid jsonrpc version (must be '2.0')",
                error_type=ValidationErrorType.INVALID_VERSION,
            )

    def _validate_method_name(self, method: Any) -> None:
        """Validate method name.

        Args:
            method: Method name to validate

        Raises:
            ValidationError: If method name is invalid
        """
        if not isinstance(method, str):
            raise ValidationError(
                "Method must be a string", error_type=ValidationErrorType.INVALID_METHOD
            )
        if not method:
            raise ValidationError(
                "Method cannot be empty", error_type=ValidationErrorType.INVALID_METHOD
            )
        if not self.METHOD_NAME_PATTERN.match(method):
            # Provide more specific error message based on what's wrong
            if any(ord(c) <= 0x1F or ord(c) == 0x7F for c in method):
                raise ValidationError(
                    "Method name contains control characters (ASCII 0x00-0x1F or 0x7F)",
                    error_type=ValidationErrorType.INVALID_METHOD,
                )
            elif method.startswith(" ") or method.endswith(" "):
                raise ValidationError(
                    "Method name cannot start or end with whitespace",
                    error_type=ValidationErrorType.INVALID_METHOD,
                )
            else:
                raise ValidationError(
                    "Method name contains invalid characters (control chars or leading/trailing whitespace not allowed)",
                    error_type=ValidationErrorType.INVALID_METHOD,
                )

    def _validate_request_id(self, request_id: Any) -> None:
        """Validate request ID.

        Args:
            request_id: ID to validate

        Raises:
            ValidationError: If ID is invalid
        """
        if not isinstance(request_id, (str, int)):
            raise ValidationError(
                "Request ID must be a string or integer (not float)",
                error_type=ValidationErrorType.INVALID_ID,
            )

    def _validate_response_id(self, response_id: Any) -> None:
        """Validate response ID.

        Args:
            response_id: ID to validate

        Raises:
            ValidationError: If ID is invalid
        """
        # Response ID can be null for parse errors or invalid request errors
        if response_id is not None and not isinstance(response_id, (str, int)):
            raise ValidationError(
                "Response ID must be a string, integer, or null (for parse/invalid request errors)",
                error_type=ValidationErrorType.INVALID_ID,
            )

    def _validate_error_object(self, error: Any) -> None:
        """Validate error object structure.

        Args:
            error: Error object to validate

        Raises:
            ValidationError: If error object is invalid
        """
        if not isinstance(error, dict):
            raise ValidationError(
                "Error must be an object", error_type=ValidationErrorType.INVALID_ERROR
            )

        # Required fields
        if "code" not in error:
            raise ValidationError(
                "Error object missing 'code' field",
                error_type=ValidationErrorType.INVALID_ERROR,
            )
        if "message" not in error:
            raise ValidationError(
                "Error object missing 'message' field",
                error_type=ValidationErrorType.INVALID_ERROR,
            )

        # Type validation
        if not isinstance(error["code"], int):
            raise ValidationError(
                "Error code must be an integer",
                error_type=ValidationErrorType.INVALID_ERROR,
            )
        if not isinstance(error["message"], str):
            raise ValidationError(
                "Error message must be a string",
                error_type=ValidationErrorType.INVALID_ERROR,
            )

    def _validate_sender_context(self, data: Any) -> Optional[SenderContext]:
        """Validate and parse sender context from inbound data.

        Args:
            data: Sender context data to validate

        Returns:
            SenderContext object or None

        Raises:
            ValidationError: If sender context is invalid
        """
        if data is None:
            return None

        if not isinstance(data, dict):
            raise ValidationError(
                "sender_context must be an object",
                error_type=ValidationErrorType.INVALID_SENDER_CONTEXT,
            )

        # Validate required sender field
        if "sender" not in data:
            raise ValidationError(
                "sender_context missing required 'sender' field",
                error_type=ValidationErrorType.INVALID_SENDER_CONTEXT,
            )

        sender_str = data.get("sender")
        if sender_str not in ["client", "server"]:
            raise ValidationError(
                f"sender_context.sender must be 'client' or 'server', got: {sender_str}",
                error_type=ValidationErrorType.INVALID_SENDER_CONTEXT,
            )

        # Parse sender enum
        sender = (
            MessageSender.CLIENT if sender_str == "client" else MessageSender.SERVER
        )

        # Validate optional fields
        identifier = data.get("identifier")
        if identifier is not None and not isinstance(identifier, str):
            raise ValidationError(
                "sender_context.identifier must be a string",
                error_type=ValidationErrorType.INVALID_SENDER_CONTEXT,
            )

        metadata = data.get("metadata")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValidationError(
                    "sender_context.metadata must be an object",
                    error_type=ValidationErrorType.INVALID_SENDER_CONTEXT,
                )
            # Validate that metadata contains only JSON-serializable values
            self._validate_json_serializable(metadata, "sender_context.metadata")

        return SenderContext(
            sender=sender, identifier=identifier, metadata=metadata or {}
        )

    def _validate_json_serializable(self, obj: Any, context: str = "value") -> None:
        """Validate that an object is JSON serializable.

        Args:
            obj: Object to validate
            context: Context description for error messages

        Raises:
            ValidationError: If object contains non-serializable data
        """
        try:
            # Attempt to serialize the object
            json.dumps(obj)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"{context} contains non-JSON serializable data: {e}",
                error_type=ValidationErrorType.JSON_ERROR,
                cause=e,
            )
