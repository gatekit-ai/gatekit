"""Operational auditing plugins for Gatekit MCP gateway.

This module provides operational auditing plugins for human-readable log formats
used by operations teams for monitoring and troubleshooting.
"""

from typing import Dict, Any, List
from datetime import datetime
from gatekit.plugins.auditing.base import BaseAuditingPlugin


class LineAuditingPlugin(BaseAuditingPlugin):
    """Line format auditing plugin for operational monitoring.

    Logs MCP requests and responses in single-line human-readable format
    for operational monitoring and quick visual inspection by ops teams.

    Features:
    - Single line per event for easy scanning
    - Human-readable timestamps and status
    - Concise tool and method information
    - Quick visual identification of issues
    """

    # TUI Display Metadata
    DISPLAY_NAME = "Human Readable"
    DESCRIPTION = "Log all MCP messages in human-readable format for quick visual inspection and monitoring."

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
                # Could not check file - continue with default actions (safe fallback)
                pass
            return ["Configure"]
        return ["Setup"]

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for Human Readable Auditing configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/human-readable-auditing.json",
            "type": "object",
            "description": "Human-readable audit logging plugin configuration",
            "properties": {
                # Note: enabled is injected by framework (auditing plugins don't have priority)
                # See gatekit/config/framework_fields.py
                "output_file": {
                    "type": "string",
                    "description": "Path to log file",
                    "default": "logs/gatekit_audit.log",
                    "minLength": 1,
                    "x-widget": "file-path",
                },
            },
            "required": ["output_file"],
            "additionalProperties": False,
        }

    def __init__(self, config: Dict[str, Any]):
        """Initialize Human Readable auditing plugin with configuration.

        Args:
            config: Plugin configuration dictionary.

        Raises:
            ValueError: If output_file is not provided
        """
        super().__init__(config)

        # Validate required output_file
        if not self.raw_output_file:
            raise ValueError(
                "output_file is required for Human Readable auditing plugin"
            )

    def _format_request_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted request data into line log entry.

        Args:
            data: Dictionary containing extracted request data

        Returns:
            str: Line-formatted log message
        """
        # Convert ISO timestamp to human-readable format
        timestamp_dt = datetime.fromisoformat(data["timestamp"].rstrip("Z"))
        timestamp = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        # Validate method exists
        if not data.get("method"):
            return f"{timestamp} - REQUEST: [invalid request - missing method] - {self._sanitize_user_string(data['server_name'])}"

        method = self._sanitize_user_string(data["method"])
        server_name = self._sanitize_user_string(data["server_name"])
        reason = self._sanitize_reason(data.get("reason", ""))

        # Build base message: timestamp - REQUEST: method - tool - server
        if "tool_name" in data:
            tool_name = self._sanitize_user_string(data["tool_name"])
            base_msg = f"{timestamp} - REQUEST: {method} - {tool_name} - {server_name}"
        else:
            base_msg = f"{timestamp} - REQUEST: {method} - {server_name}"

        # Add pipeline outcome with reason where relevant
        pipeline_outcome = data.get("pipeline_outcome")
        if not pipeline_outcome:
            return f"{base_msg} - UNKNOWN"
        elif pipeline_outcome.name == "BLOCKED":
            return f"{base_msg} - BLOCKED - {reason}" if reason else f"{base_msg} - BLOCKED"
        elif pipeline_outcome.name == "NO_SECURITY_EVALUATION":
            return f"{base_msg} - NO_SECURITY"
        elif pipeline_outcome.name == "COMPLETED_BY_MIDDLEWARE":
            return f"{base_msg} - MIDDLEWARE_RESPONSE - {reason}" if reason else f"{base_msg} - MIDDLEWARE_RESPONSE"
        elif pipeline_outcome.name == "ERROR":
            return f"{base_msg} - ERROR - {reason}" if reason else f"{base_msg} - ERROR"
        else:
            return f"{base_msg} - ALLOWED"

    def _format_response_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted response data into line log entry.

        Args:
            data: Dictionary containing extracted response data

        Returns:
            str: Line-formatted log message
        """
        # Convert ISO timestamp to human-readable format
        timestamp_dt = datetime.fromisoformat(data["timestamp"].rstrip("Z"))
        timestamp = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        server_name = self._sanitize_user_string(data["server_name"])
        reason = self._sanitize_reason(data.get("reason", ""))

        # Build base message
        base_msg = f"{timestamp} - RESPONSE - {server_name}"

        # Add pipeline outcome with reason where relevant
        pipeline_outcome = data.get("pipeline_outcome")
        if not pipeline_outcome:
            return f"{base_msg} - UNKNOWN"
        elif pipeline_outcome.name == "BLOCKED":
            return f"{base_msg} - BLOCKED - {reason}" if reason else f"{base_msg} - BLOCKED"
        elif pipeline_outcome.name == "NO_SECURITY_EVALUATION":
            return f"{base_msg} - NO_SECURITY"
        elif pipeline_outcome.name == "COMPLETED_BY_MIDDLEWARE":
            return f"{base_msg} - MIDDLEWARE_RESPONSE - {reason}" if reason else f"{base_msg} - MIDDLEWARE_RESPONSE"
        elif pipeline_outcome.name == "ERROR":
            return f"{base_msg} - ERROR - {reason}" if reason else f"{base_msg} - ERROR"
        elif data.get("response_status") == "error":
            error_code = data.get("error_code", "unknown")
            error_msg = self._sanitize_reason(data.get("error_message", "unknown"))
            return f"{base_msg} - error {error_code}: {error_msg}"
        else:
            duration_info = ""
            if "duration_ms" in data:
                duration_s = data["duration_ms"] / 1000
                duration_info = f" ({duration_s:.3f}s)"
            return f"{base_msg} - success{duration_info}"

    def _format_notification_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted notification data into line log entry.

        Args:
            data: Dictionary containing extracted notification data

        Returns:
            str: Line-formatted log message
        """
        # Convert ISO timestamp to human-readable format
        timestamp_dt = datetime.fromisoformat(data["timestamp"].rstrip("Z"))
        timestamp = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        sanitized_method = self._sanitize_user_string(data.get("method", "unknown"))
        server_name = self._sanitize_user_string(data["server_name"])
        reason = self._sanitize_reason(data.get("reason", ""))

        # Build base message
        base_msg = f"{timestamp} - NOTIFICATION: {sanitized_method} - {server_name}"

        # Add pipeline outcome with reason where relevant
        pipeline_outcome = data.get("pipeline_outcome")
        if not pipeline_outcome:
            return f"{base_msg} - UNKNOWN"
        elif pipeline_outcome.name == "BLOCKED":
            return f"{base_msg} - BLOCKED - {reason}" if reason else f"{base_msg} - BLOCKED"
        elif pipeline_outcome.name == "NO_SECURITY_EVALUATION":
            return f"{base_msg} - NO_SECURITY"
        elif pipeline_outcome.name == "ERROR":
            return f"{base_msg} - ERROR - {reason}" if reason else f"{base_msg} - ERROR"
        else:
            return f"{base_msg} - ALLOWED"


# Handler manifest for handler-based plugin discovery
HANDLERS = {"audit_human_readable": LineAuditingPlugin}
