"""CSV auditing plugin for Gatekit MCP gateway.

This module provides the CsvAuditingPlugin class that logs MCP requests and responses
in CSV format for analysis and reporting.
"""

import csv
import io
import json
import threading
from typing import Dict, Any, List
from gatekit.plugins.auditing.base import BaseAuditingPlugin


class CsvAuditingPlugin(BaseAuditingPlugin):
    """CSV auditing plugin for structured logging.

    Logs MCP requests and responses in CSV format for analysis and reporting.
    Provides Excel-compatible format with configurable delimiters and quote styles.

    Features:
    - Excel-compatible CSV format
    - Configurable delimiters and quote styles
    - Automatic header management
    - CSV injection protection
    """

    # TUI Display Metadata
    DISPLAY_NAME = "CSV"
    DESCRIPTION = "Log all MCP messages in CSV format. Excel-compatible with configurable delimiters."

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

    # Type annotations for class attributes
    delimiter: str
    quote_char: str
    quote_style: str
    escape_char: str
    null_value: str
    header_written: bool
    csv_quote_style: int
    field_order: List[str]
    _header_lock: threading.Lock

    def __init__(self, config: Dict[str, Any]):
        """Initialize CSV auditing plugin with configuration.

        Args:
            config: Plugin configuration dictionary with CSV-specific options:
                   - csv_config: Dictionary containing:
                     - delimiter: CSV field delimiter (default: ",")
                     - quote_char: Quote character (default: '"')
                     - quote_style: "minimal", "all", "nonnumeric", "none" (default: "minimal")
                     - null_value: Value for null fields (default: "")
                   Plus all BaseAuditingPlugin options (output_file, etc.)

        Raises:
            ValueError: If configuration is invalid
            TypeError: If configuration has wrong types
        """
        # CSV format requires newlines for structure - preserve them during sanitization
        config = config.copy()
        config["preserve_formatting_newlines"] = True

        # Initialize base class first
        super().__init__(config)

        # CSV-specific configuration
        csv_config = config.get("csv_config", {})
        self.delimiter = csv_config.get("delimiter", ",")
        self.quote_char = csv_config.get("quote_char", '"')
        self.quote_style = csv_config.get("quote_style", "minimal")
        self.escape_char = csv_config.get("escape_char", "\\")
        self.null_value = csv_config.get("null_value", "")

        # Header management
        self.header_written = False
        self._header_lock = threading.Lock()

        # Validate configuration
        self._validate_config()

        # Set up CSV configuration
        self.csv_quote_style = self._get_csv_quote_style()
        self.field_order = self._get_field_order()

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for CSV Auditing configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/csv-auditing.json",
            "type": "object",
            "description": "CSV audit logging plugin configuration",
            "properties": {
                # Note: enabled is injected by framework (auditing plugins don't have priority)
                # See gatekit/config/framework_fields.py
                "output_file": {
                    "type": "string",
                    "description": "Path to CSV log file (supports date formatting)",
                    "default": "logs/gatekit_audit.csv",
                    "minLength": 1,
                    "x-widget": "file-path",
                },
                "csv_config": {
                    "type": "object",
                    "description": "CSV format configuration",
                    "properties": {
                        "delimiter": {
                            "type": "string",
                            "enum": [",", "\t", ";", "|"],
                            "description": "Field delimiter character",
                            "default": ",",
                        },
                        "quote_char": {
                            "type": "string",
                            "description": "Character used to quote fields",
                            "default": '"',
                            "minLength": 1,
                            "maxLength": 1,
                        },
                        "quote_style": {
                            "type": "string",
                            "enum": ["minimal", "all", "nonnumeric", "none"],
                            "description": "When to quote fields",
                            "default": "minimal",
                        },
                        "escape_char": {
                            "type": "string",
                            "description": "Escape character for special values",
                            "default": "\\",
                            "minLength": 1,
                            "maxLength": 1,
                        },
                        "null_value": {
                            "type": "string",
                            "description": "Value to use for null/empty fields",
                            "default": "",
                        },
                    },
                    "additionalProperties": False,
                    "default": {},
                },
            },
            "required": ["output_file"],
            "additionalProperties": False,
        }

    def _validate_config(self):
        """Validate CSV configuration."""
        # Validate required output_file
        if not self.raw_output_file:
            raise ValueError(
                "output_file is required for CSV auditing plugin"
            )

        if not isinstance(self.delimiter, str) or len(self.delimiter) != 1:
            raise ValueError("delimiter must be a single character")

        if not isinstance(self.quote_char, str) or len(self.quote_char) != 1:
            raise ValueError("quote_char must be a single character")

        # Note: quote_style enum validation is handled by JSON schema

    def _get_csv_quote_style(self) -> int:
        """Get CSV quote style constant from configuration."""
        quote_style_map = {
            "minimal": csv.QUOTE_MINIMAL,
            "all": csv.QUOTE_ALL,
            "nonnumeric": csv.QUOTE_NONNUMERIC,
            "none": csv.QUOTE_NONE,
        }
        return quote_style_map[self.quote_style]

    def _get_field_order(self) -> List[str]:
        """Get field order - includes all available fields."""
        return [
            "timestamp",
            "event_type",
            "request_id",
            "server_name",
            "method",
            "tool",
            "pipeline_outcome",
            "security_evaluated",
            "modified",
            "reason",
            "duration_ms",
            "response_status",
            "error_code",
            "error_message",
            "error_classification",
        ]

    def _format_request_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted request data into CSV log entry.

        Args:
            data: Dictionary containing extracted request data

        Returns:
            str: CSV-formatted log message
        """
        csv_row = {
            "timestamp": data["timestamp"],
            "event_type": data["event_type"],
            "request_id": data.get("request_id"),  # Keep as int or None for QUOTE_NONNUMERIC
            "server_name": data["server_name"],
            "method": data.get("method", ""),
            "tool": data.get("tool_name", ""),
            "pipeline_outcome": data["pipeline_outcome"].value,
            "security_evaluated": str(data.get("security_evaluated", False)).lower(),
            "modified": str(data.get("modified", False)).lower(),
            "reason": data["reason"],
            "duration_ms": 0,  # No duration for requests (int for QUOTE_NONNUMERIC)
        }

        return self._format_csv_message(csv_row)

    def _format_response_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted response data into CSV log entry.

        Args:
            data: Dictionary containing extracted response data

        Returns:
            str: CSV-formatted log message
        """
        csv_row = {
            "timestamp": data["timestamp"],
            "event_type": data["event_type"],
            "request_id": data.get("request_id"),  # Keep as int or None for QUOTE_NONNUMERIC
            "server_name": data["server_name"],
            "method": data.get("method", ""),
            "tool": data.get("tool_name", ""),
            "pipeline_outcome": data["pipeline_outcome"].value,
            "security_evaluated": str(data.get("security_evaluated", False)).lower(),
            "modified": str(data.get("modified", False)).lower(),
            "reason": data["reason"],
            "duration_ms": data.get("duration_ms", 0) or 0,  # Keep as int for QUOTE_NONNUMERIC
            "response_status": data.get("response_status", ""),
            "error_code": data.get("error_code"),  # Keep as int or None for QUOTE_NONNUMERIC
            "error_message": data.get("error_message", ""),
            "error_classification": self._classify_error(data.get("error_code"))
            if "error_code" in data
            else "",
        }

        return self._format_csv_message(csv_row)

    def _classify_error(self, error_code: Any) -> str:
        """Classify JSON-RPC error code into category.

        Args:
            error_code: JSON-RPC error code

        Returns:
            str: Error classification (parse_error, invalid_request, method_not_found,
                 invalid_params, internal_error, server_error, or unknown)
        """
        if not isinstance(error_code, int):
            return "unknown"

        if error_code == -32700:
            return "parse_error"
        elif error_code == -32600:
            return "invalid_request"
        elif error_code == -32601:
            return "method_not_found"
        elif error_code == -32602:
            return "invalid_params"
        elif error_code == -32603:
            return "internal_error"
        elif -32099 <= error_code <= -32000:
            return "server_error"
        else:
            return "application_error"

    def _format_notification_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted notification data into CSV log entry.

        Args:
            data: Dictionary containing extracted notification data

        Returns:
            str: CSV-formatted log message
        """
        # Build reason field with notification params included
        reason = data["reason"]
        if "params" in data and data["params"]:
            params_str = json.dumps(data["params"], separators=(",", ":"))
            if reason:
                reason = f"{reason} params={params_str}"
            else:
                reason = f"params={params_str}"

        csv_row = {
            "timestamp": data["timestamp"],
            "event_type": data["event_type"],
            "request_id": None,  # Notifications don't have request IDs (None for QUOTE_NONNUMERIC)
            "server_name": data["server_name"],
            "method": data.get("method", ""),
            "tool": "",  # Notifications aren't tool calls
            "pipeline_outcome": data["pipeline_outcome"].value,
            "security_evaluated": str(data.get("security_evaluated", False)).lower(),
            "modified": str(data.get("modified", False)).lower(),
            "reason": reason,
            "duration_ms": 0,  # No duration for notifications (int for QUOTE_NONNUMERIC)
        }

        return self._format_csv_message(csv_row)

    def _format_csv_value(self, value: Any) -> str:
        """Format values for CSV output with injection protection.

        Args:
            value: Value to format

        Returns:
            str: Formatted value with CSV injection protection
        """
        if value is None:
            return self.null_value
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, dict):
            # Convert dict to JSON string for complex data
            json_str = json.dumps(value, separators=(",", ":"))
            # Truncate if too long for Excel (32767 char limit)
            if len(json_str) > 32000:
                json_str = json_str[:31997] + "..."
            return self._sanitize_csv_injection(json_str)
        elif isinstance(value, list):
            # Convert list to JSON string
            json_str = json.dumps(value, separators=(",", ":"))
            # Truncate if too long for Excel
            if len(json_str) > 32000:
                json_str = json_str[:31997] + "..."
            return self._sanitize_csv_injection(json_str)
        else:
            return self._sanitize_csv_injection(str(value))

    def _sanitize_csv_injection(self, value: str) -> str:
        """Sanitize values to prevent CSV injection attacks and escape newlines.

        Escapes newlines to ensure each CSV record stays on one line, which is
        critical for line-based log analysis tools (grep, awk, etc.) and log
        aggregation systems. Per OWASP Logging Cheat Sheet, CR and LF characters
        should be sanitized to prevent log injection attacks.

        Also prevents CSV formula injection by prefixing dangerous characters
        with a single quote, per OWASP CSV Injection guidance.

        Args:
            value: String value to sanitize

        Returns:
            str: Sanitized value safe from CSV injection with escaped newlines
        """
        if not value:
            return value

        # Escape newlines to keep CSV records on single lines
        # This is critical for line-based tools and log aggregators
        # Order matters: escape backslashes first to avoid double-escaping
        value = value.replace("\\", "\\\\")
        value = value.replace("\r\n", "\\r\\n")
        value = value.replace("\n", "\\n")
        value = value.replace("\r", "\\r")

        # Check if first character could trigger formula execution
        if value[0] in ("=", "+", "-", "@", "\t"):
            # Prefix with single quote to prevent formula execution
            return "'" + value

        return value

    def _check_header_needed(self) -> bool:
        """Check if header needs to be written (for file rotation support).

        Note: While thread-safe within a process, multiple processes writing
        to the same file may still experience header races. For multi-process
        deployments, consider using separate log files per process or a
        centralized logging service.

        Returns:
            bool: True if header should be written
        """
        # If we're writing to a file, check if it's empty or new
        if hasattr(self, "output_file") and self.output_file:
            import os

            try:
                # Check if file exists and has content
                if os.path.exists(self.output_file):
                    file_size = os.path.getsize(self.output_file)
                    return file_size == 0
                else:
                    return True
            except (OSError, IOError):
                # If we can't check file, assume header not needed (safe fallback)
                return False

        # For non-file outputs, use the instance flag
        return not self.header_written

    def _format_csv_message(self, csv_row: Dict[str, Any]) -> str:
        """Format CSV message with header if needed.

        Args:
            csv_row: CSV row data

        Returns:
            str: Formatted CSV message
        """
        output = io.StringIO()

        # Apply null_value handling for ALL fields in field_order
        # This ensures missing fields also get the null_value, not empty strings
        # Preserve int/float types for QUOTE_NONNUMERIC support
        processed_row = {}
        for field in self.field_order:
            v = csv_row.get(field)  # Returns None if field is missing
            # Apply null_value conversion for None or empty strings
            if v is None or v == "":
                processed_row[field] = self.null_value
            elif isinstance(v, (int, float)):
                # Preserve numeric types for QUOTE_NONNUMERIC support
                processed_row[field] = v
            else:
                # Format the value (handles dicts, lists, bools, etc.)
                formatted = self._format_csv_value(v)
                processed_row[field] = formatted

        # Sanitize all string values to prevent CSV injection attacks
        # Preserve int/float types for QUOTE_NONNUMERIC support
        sanitized_row = {
            k: self._sanitize_csv_injection(str(v)) if isinstance(v, str) else v
            for k, v in processed_row.items()
        }

        # Configure writer kwargs based on quote style
        writer_kwargs = {
            "fieldnames": self.field_order,
            "quoting": self.csv_quote_style,
            "delimiter": self.delimiter,
            "quotechar": self.quote_char,
            "lineterminator": "\n",
        }

        # Add escapechar if using QUOTE_NONE
        if self.csv_quote_style == csv.QUOTE_NONE:
            writer_kwargs["escapechar"] = self.escape_char

        writer = csv.DictWriter(output, **writer_kwargs)

        # Thread-safe header writing with file rotation support
        header_needed = False
        with self._header_lock:
            if self._check_header_needed():
                header_needed = True
                self.header_written = True

        # Write header if needed (outside lock to minimize critical section)
        if header_needed:
            writer.writeheader()

        # Write data row with sanitized values
        writer.writerow(sanitized_row)

        # Remove trailing newline since logging system will add it
        result = output.getvalue()
        if result.endswith("\n"):
            result = result[:-1]

        return result


# Handler manifest for handler-based plugin discovery
HANDLERS = {"audit_csv": CsvAuditingPlugin}
