"""JSON auditing plugin for Gatekit MCP gateway.

This module provides the JsonAuditingPlugin class that logs MCP requests and responses
in JSON Lines format for structured logging, debugging, and integration with log
aggregation systems.
"""

import json
from typing import Dict, Any, List
from datetime import datetime, timezone
from gatekit.plugins.auditing.base import BaseAuditingPlugin
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.plugins.interfaces import ProcessingPipeline


class JsonAuditingPlugin(BaseAuditingPlugin):
    """JSON Lines auditing plugin for structured logging.

    Logs MCP requests and responses in JSON Lines format for structured logging,
    debugging, and integration with log aggregation systems (ELK, Splunk, etc.).

    Features:
    - JSON Lines format (one JSON object per line)
    - Configurable body inclusion and size limits
    - Machine-readable structured format
    - Compatible with standard log aggregation tools
    """

    # TUI Display Metadata
    DISPLAY_NAME = "JSON Lines"
    DESCRIPTION = "Log all MCP messages in JSON Lines format for debugging and auditing."

    # describe_status() and get_status_file_path() inherited from BaseAuditingPlugin

    @classmethod
    def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
        """Return actions with log viewing capability."""
        if config and config.get("enabled", False):
            output_file = config.get("output_file", "")
            try:
                import os

                if output_file and os.path.exists(output_file):
                    return ["View Logs", "Configure"]
            except (OSError, IOError):
                pass
            return ["Configure"]
        return ["Setup"]

    # Type annotations for class attributes
    include_request_body: bool
    include_response_body: bool
    include_notification_body: bool
    max_body_size: int

    def __init__(self, config: Dict[str, Any]):
        """Initialize JSON auditing plugin with configuration.

        Args:
            config: Plugin configuration dictionary with JSON-specific options:
                   - include_request_body: Include full request parameters (default: False)
                   - include_response_body: Include full response result/error (default: False)
                   - include_notification_body: Include full notification parameters (default: False)
                   - max_body_size: Maximum size in bytes for logged message bodies (default: 10240, 0 = unlimited)
                   Plus all BaseAuditingPlugin options (output_file, etc.)

        Raises:
            ValueError: If configuration is invalid
            TypeError: If configuration has wrong types
        """
        # Initialize base class first
        super().__init__(config)

        # Check for deprecated configuration
        if "redact_request_fields" in config:
            import logging

            logging.getLogger(__name__).warning(
                "Configuration option 'redact_request_fields' has been removed. "
                "Data redaction should be handled by security plugins in the processing pipeline, "
                "not by auditing plugins. Please remove this option from your configuration."
            )

        # JSON-specific configuration
        self.include_request_body = config.get("include_request_body", False)
        self.include_response_body = config.get("include_response_body", False)
        self.include_notification_body = config.get("include_notification_body", False)
        self.max_body_size = config.get("max_body_size", 10240)  # Default 10KB

        # Validate configuration
        self._validate_config()

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for JSON Lines Auditing configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/json-lines-auditing.json",
            "type": "object",
            "description": "JSON Lines audit logging plugin configuration",
            "properties": {
                # Note: enabled is injected by framework (auditing plugins don't have priority)
                # See gatekit/config/framework_fields.py
                "output_file": {
                    "type": "string",
                    "description": "Path to JSONL log file (supports date formatting)",
                    "default": "logs/gatekit_audit.jsonl",
                    "minLength": 1,
                    "x-widget": "file-path",
                },
                "include_request_body": {
                    "type": "boolean",
                    "description": "Include request body in logs",
                    "default": False,
                },
                "include_response_body": {
                    "type": "boolean",
                    "description": "Include response body in logs",
                    "default": False,
                },
                "include_notification_body": {
                    "type": "boolean",
                    "description": "Include notification body in logs",
                    "default": False,
                },
                "max_body_size": {
                    "type": "integer",
                    "description": "Maximum size in bytes for logged message bodies (0 = unlimited, minimum 50 if set)",
                    "default": 10240,
                    "minimum": 0,
                    "maximum": 1048576,
                },
            },
            "required": ["output_file"],
            "additionalProperties": False,
        }

    def _validate_config(self):
        """Validate JSON configuration.

        Note: Type validation for booleans and integers is handled by JSON Schema.
        This method only handles business logic that schema cannot express.
        """
        # Validate required output_file
        if not self.raw_output_file:
            raise ValueError(
                "output_file is required for JSON Lines auditing plugin"
            )

        # Enforce minimum of 50 bytes when set (0 means unlimited)
        # This is semantic validation that JSON Schema min/max cannot express
        if self.max_body_size > 0 and self.max_body_size < 50:
            raise ValueError(
                f"max_body_size must be at least 50 bytes when set (got {self.max_body_size}). "
                "Use 0 for unlimited."
            )

    def _truncate_body(self, body: Any) -> Any:
        """Truncate message body if it exceeds max_body_size.

        Args:
            body: The message body to potentially truncate

        Returns:
            The original body or a truncated version with a marker.
            Always includes actual content from the original body when truncating,
            falling back to a truncated string representation if structured
            truncation cannot preserve any content.
        """
        if self.max_body_size == 0:  # 0 means unlimited
            return body

        # Convert to JSON string to measure size
        try:
            body_str = json.dumps(body, separators=(",", ":"))
            if len(body_str) <= self.max_body_size:
                return body

            # Need to truncate - try to preserve structure first
            truncation_marker = "...[truncated]"
            # Leave room for JSON structure overhead; minimum 50 bytes guaranteed by validation
            available_size = self.max_body_size - len(truncation_marker) - 20

            if isinstance(body, str):
                # Simple string truncation
                return body[:available_size] + truncation_marker
            elif isinstance(body, dict):
                # For dict, try to include as many fields as possible
                truncated: Dict[str, Any] = {}
                current_size = 2  # For {}
                for key, value in body.items():
                    key_value_str = json.dumps({key: value}, separators=(",", ":"))[
                        1:-1
                    ]  # Remove outer {}
                    if (
                        current_size + len(key_value_str) + 1 < available_size
                    ):  # +1 for comma
                        truncated[key] = value
                        current_size += len(key_value_str) + 1
                    else:
                        truncated["_truncated"] = True
                        break

                # If we couldn't fit any actual content (only _truncated marker),
                # fall back to truncated string representation
                if len(truncated) == 1 and "_truncated" in truncated:
                    return body_str[:available_size] + truncation_marker

                return truncated
            elif isinstance(body, list):
                # For list, include as many items as possible
                truncated_list: List[Any] = []
                current_size = 2  # For []
                for item in body:
                    item_str = json.dumps(item, separators=(",", ":"))
                    if (
                        current_size + len(item_str) + 1 < available_size
                    ):  # +1 for comma
                        truncated_list.append(item)
                        current_size += len(item_str) + 1
                    else:
                        truncated_list.append(truncation_marker)
                        break

                # If we couldn't fit any actual content (only truncation marker),
                # fall back to truncated string representation
                if len(truncated_list) == 1 and truncated_list[0] == truncation_marker:
                    return body_str[:available_size] + truncation_marker

                return truncated_list
            else:
                # For other types, convert to string and truncate
                return str(body)[:available_size] + truncation_marker
        except (TypeError, ValueError):
            # If we can't serialize, return as-is
            return body

    def _get_error_details(self, response: MCPResponse) -> tuple[str, int, str]:
        """Extract and normalize error details from response.

        Args:
            response: MCP response that may contain error

        Returns:
            Tuple of (event_type, error_code, error_message)
        """
        if not (hasattr(response, "error") and response.error):
            return "RESPONSE", 0, ""

        # Extract error details from dict
        error_code = response.error.get("code", 0)
        error_message = response.error.get("message", "")

        # Ensure error_code is an integer, default to 0 if None or invalid type
        if not isinstance(error_code, int):
            error_code = 0

        # Classify error type based on JSON-RPC spec
        # Server errors: -32000 to -32099
        # Protocol/client errors: other negative codes
        if -32099 <= error_code <= -32000:
            event_type = "UPSTREAM_ERROR"
        else:
            event_type = "ERROR"

        return event_type, error_code, error_message

    def _format_request_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted request data into JSON log entry.

        Args:
            data: Dictionary containing extracted request data

        Returns:
            str: JSON-formatted log message
        """
        # Build base log data from extracted common data
        log_data = {
            "timestamp": data["timestamp"],
            "event_type": data["event_type"],
            "request_id": data.get("request_id"),
            "server_name": data["server_name"],
            "method": data.get("method"),
            "pipeline_outcome": (
                data.get("pipeline_outcome").value
                if data.get("pipeline_outcome")
                else "allowed"
            ),
            "security_evaluated": data.get("security_evaluated", False),
            "modified": data.get("modified", False),
            "pipeline": data.get("pipeline", {}),
            "reason": data["reason"] if data["reason"] else "",
        }

        # Add tool name if present
        if "tool_name" in data:
            log_data["tool"] = data["tool_name"]

        # Add request body if configured
        if self.include_request_body and "params" in data and data["params"]:
            log_data["request_body"] = self._truncate_body(data["params"])

        return self._format_json_output(log_data)

    def _format_response_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted response data into JSON log entry.

        Args:
            data: Dictionary containing extracted response data

        Returns:
            str: JSON-formatted log message
        """
        # Determine detailed event type based on response_status and error info
        event_type = data["event_type"]
        if event_type == "RESPONSE" and data.get("response_status") == "error":
            # Classify error type based on JSON-RPC error code
            error_code = data.get("error_code", 0)
            if isinstance(error_code, int):
                if error_code == -32700:
                    event_type = "PARSE_ERROR"
                elif error_code == -32600:
                    event_type = "INVALID_REQUEST_ERROR"
                elif error_code == -32601:
                    event_type = "METHOD_NOT_FOUND_ERROR"
                elif error_code == -32602:
                    event_type = "INVALID_PARAMS_ERROR"
                elif error_code == -32603:
                    event_type = "INTERNAL_ERROR"
                elif -32099 <= error_code <= -32000:
                    event_type = "UPSTREAM_ERROR"
                else:
                    event_type = "APPLICATION_ERROR"
            else:
                event_type = "APPLICATION_ERROR"

        # Build base log data
        log_data = {
            "timestamp": data["timestamp"],
            "event_type": event_type,
            "request_id": data.get("request_id"),
            "server_name": data["server_name"],
            "method": data.get("method", ""),
            "pipeline_outcome": (
                data.get("pipeline_outcome").value
                if data.get("pipeline_outcome")
                else "allowed"
            ),
            "security_evaluated": data.get("security_evaluated", False),
            "modified": data.get("modified", False),
            "response_status": data.get("response_status", "success"),
            "pipeline": data.get("pipeline", {}),
            "reason": data["reason"] if data["reason"] else "",
        }

        # Add tool name if present
        if "tool_name" in data:
            log_data["tool"] = data["tool_name"]

        # Add error details if present
        if "error_code" in data:
            log_data["error_code"] = data["error_code"]
            log_data["error_message"] = data.get("error_message", "")

        # Add duration if available
        if "duration_ms" in data:
            log_data["duration_ms"] = data["duration_ms"]

        # Add response body if configured
        if self.include_response_body and "response_body" in data:
            log_data["response_body"] = data["response_body"]

        return self._format_json_output(log_data)

    def _format_notification_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted notification data into JSON log entry.

        Args:
            data: Dictionary containing extracted notification data

        Returns:
            str: JSON-formatted log message
        """
        # Build base log data
        log_data = {
            "timestamp": data["timestamp"],
            "event_type": data["event_type"],
            "request_id": data.get("request_id"),
            "server_name": data["server_name"],
            "method": data.get("method"),
            "pipeline_outcome": (
                data.get("pipeline_outcome").value
                if data.get("pipeline_outcome")
                else "allowed"
            ),
            "security_evaluated": data.get("security_evaluated", False),
            "modified": data.get("modified", False),
            "pipeline": data.get("pipeline", {}),
            "reason": data["reason"] if data["reason"] else "",
        }

        # Add notification body if configured
        if self.include_notification_body and "notification_body" in data:
            log_data["notification_body"] = data["notification_body"]

        return self._format_json_output(log_data)

    def _format_json_output(self, log_data: Dict[str, Any]) -> str:
        """Format log data as JSON output.

        Args:
            log_data: Log data dictionary

        Returns:
            str: JSON-formatted string

        Raises:
            TypeError: If the data cannot be serialized to JSON
        """
        try:
            result = json.dumps(
                log_data,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            # Always add newline for proper JSON Lines framing
            result += "\n"
            return result
        except (TypeError, ValueError) as e:
            # If serialization fails, try to create a safe version
            safe_log_data = {
                "error": "JSON serialization failed",
                "error_details": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": log_data.get("event_type", "UNKNOWN"),
            }
            # Add safe fields that we know can be serialized
            for key in [
                "request_id",
                "method",
                "pipeline_outcome",
                "server_name",
            ]:
                if key in log_data and isinstance(
                    log_data[key], (str, int, float, bool, type(None))
                ):
                    safe_log_data[key] = log_data[key]

            result = json.dumps(
                safe_log_data,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            # Always add newline for proper JSON Lines framing
            result += "\n"
            return result

    # Override log methods to add message bodies when configured

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        """Log response with optional body included."""
        duration_ms = self._calculate_duration(getattr(request, "id", None))
        data = self._extract_common_response_data(
            request, response, pipeline, server_name
        )
        if duration_ms is not None:
            data["duration_ms"] = duration_ms

        # Add response body if configured
        # SECURITY: Use pipeline.final_content for body data when available
        # This ensures redacted content is logged instead of original sensitive data
        if self.include_response_body:
            response_for_body = (
                pipeline.final_content
                if pipeline.final_content and isinstance(pipeline.final_content, MCPResponse)
                else response
            )
            if response_for_body:
                if hasattr(response_for_body, "result") and response_for_body.result is not None:
                    data["response_body"] = self._truncate_body(response_for_body.result)
                elif hasattr(response_for_body, "error") and response_for_body.error is not None:
                    data["response_body"] = self._truncate_body(response_for_body.error)

        self._safe_log(self._format_response_entry(data))

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        """Log notification with optional body included."""
        data = self._extract_common_notification_data(
            notification, pipeline, server_name
        )

        # Add notification body if configured
        # SECURITY: Use pipeline.final_content for body data when available
        # This ensures redacted content is logged instead of original sensitive data
        if self.include_notification_body:
            notification_for_body = (
                pipeline.final_content
                if pipeline.final_content and isinstance(pipeline.final_content, MCPNotification)
                else notification
            )
            if notification_for_body:
                if hasattr(notification_for_body, "params") and notification_for_body.params is not None:
                    data["notification_body"] = self._truncate_body(notification_for_body.params)

        self._safe_log(self._format_notification_entry(data))


# Handler manifest for handler-based plugin discovery
HANDLERS = {"audit_jsonl": JsonAuditingPlugin}
