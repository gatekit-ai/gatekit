"""Startup error notifier for communicating startup errors to MCP clients.

This module provides a lightweight notifier that can communicate startup errors
to MCP clients when Gatekit fails to initialize. It sends JSON-RPC error
notifications and exits immediately.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from gatekit.protocol.errors import (
    MCPErrorCodes,
    StartupError,
    create_error_response_dict,
)

if TYPE_CHECKING:
    from gatekit.config.errors import ConfigError

logger = logging.getLogger(__name__)


class StartupErrorNotifier:
    """Notifier for communicating startup errors to MCP clients.

    This notifier sends JSON-RPC error messages to MCP clients when Gatekit
    fails to start, then exits immediately. It doesn't handle requests.
    """

    def __init__(self, startup_error: Optional[StartupError] = None):
        """Initialize the error notifier.

        Args:
            startup_error: The startup error to communicate to clients
        """
        self.startup_error = startup_error
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    async def send_error_response(
        self,
        error: StartupError,
        writer: asyncio.StreamWriter,
        request_id: Optional[Any] = None,
    ) -> None:
        """Send a JSON-RPC error response.

        Args:
            error: The startup error to send
            writer: The stream writer to send the response to
            request_id: The request ID to include in the response
        """
        error_data = {
            "error_type": error.error_type or "startup_error",
            "details": error.details,
            "fix_instructions": error.fix_instructions,
        }

        if error.error_context:
            error_data["error_context"] = error.error_context

        response = create_error_response_dict(
            request_id=request_id,
            code=error.code,
            message=f"Gatekit startup failed: {error.message}",
            data=error_data,
        )

        response_bytes = (json.dumps(response) + "\n").encode()
        writer.write(response_bytes)
        await writer.drain()

    async def _send_error_notification(
        self, error: StartupError, writer: asyncio.StreamWriter
    ) -> None:
        """Send an error notification (not a response) to the MCP client.

        Args:
            error: The startup error to send
            writer: The stream writer to send the notification to
        """
        # Create a notification about the startup failure
        # Notifications don't have an ID and are unsolicited
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/startup_error",  # Custom notification method
            "params": {
                "code": error.code,
                "message": f"Gatekit startup failed: {error.message}",
                "details": error.details,
                "fix_instructions": error.fix_instructions,
                "error_type": error.error_type or "startup_error",
            },
        }

        if error.error_context:
            notification["params"]["error_context"] = error.error_context

        notification_bytes = (json.dumps(notification) + "\n").encode()
        writer.write(notification_bytes)
        await writer.drain()

    async def run_until_shutdown(self) -> None:
        """Wait for initialize request, then send startup error response and exit."""
        if not self.startup_error:
            return

        try:
            # Read one line from stdin to get the initialize request
            line = sys.stdin.readline()
            if not line:
                logger.debug("No input received, exiting")
                return

            try:
                request = json.loads(line.strip())
                request_id = request.get("id", "unknown")
                logger.debug(f"Received request with id: {request_id}")
            except json.JSONDecodeError:
                logger.debug("Invalid JSON received, using default id")
                request_id = "unknown"

            # Create error response with the same ID as the request
            error_data = {
                "error_type": self.startup_error.error_type or "startup_error",
                "details": self.startup_error.details,
                "fix_instructions": self.startup_error.fix_instructions,
            }

            if self.startup_error.error_context:
                error_data["error_context"] = self.startup_error.error_context

            response = {
                "jsonrpc": "2.0",
                "id": request_id,  # Use the same ID from the request
                "error": {
                    "code": self.startup_error.code,
                    "message": f"Gatekit startup failed: {self.startup_error.message}",
                    "data": error_data,
                },
            }

            # Write response to stdout
            response_json = json.dumps(response) + "\n"
            sys.stdout.write(response_json)
            sys.stdout.flush()

            logger.debug(f"Sent startup error response with id: {request_id}")

        except Exception:
            logger.exception("Error in error notifier")
            return

    def categorize_error(self, error: Exception, context: str = "") -> StartupError:
        """Categorize an exception into a user-friendly StartupError.

        Args:
            error: The exception that occurred
            context: Additional context about what was happening

        Returns:
            StartupError with appropriate code and user-friendly messages
        """
        # Handle ConfigError directly - it has all the structured info we need
        from gatekit.config.errors import ConfigError

        if isinstance(error, ConfigError):
            return self._config_error_to_startup_error(error)

        error_str = str(error)

        # Configuration file not found
        if isinstance(error, FileNotFoundError) and "config" in context.lower():
            # Extract path from error message (format: "Configuration file not found: /path")
            file_path = error_str
            if ": " in error_str:
                file_path = error_str.split(": ", 1)[-1]
            return StartupError(
                code=MCPErrorCodes.CONFIGURATION_ERROR,
                message="Configuration file not found",
                details=f"The file '{file_path}' does not exist",
                fix_instructions="Create the file or specify a valid configuration path",
                error_type="configuration_error",
            )

        # Directory not found for log files
        if isinstance(error, FileNotFoundError) and (
            "log" in context.lower() or "/" in error_str
        ):
            # Extract directory path from error
            path_match = error_str
            if "'" in path_match:
                path_match = path_match.split("'")[1]

            dir_path = str(Path(path_match).parent)
            return StartupError(
                code=MCPErrorCodes.CONFIGURATION_ERROR,
                message="Log directory does not exist",
                details=f"The directory {dir_path} does not exist",
                fix_instructions=f"Create the directory with: mkdir -p {dir_path}",
                error_type="directory_not_found",
                error_context={"directory_path": dir_path},
            )

        # Permission denied
        if isinstance(error, PermissionError):
            path = error_str
            if "'" in path:
                path = path.split("'")[1]
            return StartupError(
                code=MCPErrorCodes.PERMISSION_ERROR,
                message="Permission denied",
                details=f"Cannot access {path}",
                fix_instructions="Check file permissions or run with appropriate privileges",
                error_type="permission_error",
                error_context={"path": path},
            )

        # YAML parsing errors
        if isinstance(error, ValueError) and "yaml" in error_str.lower():
            # Try to extract line number
            line_info = ""
            if "line" in error_str.lower():
                import re

                line_match = re.search(r"line\s+(\d+)", error_str, re.IGNORECASE)
                if line_match:
                    line_info = f" at line {line_match.group(1)}"

            return StartupError(
                code=MCPErrorCodes.CONFIGURATION_ERROR,
                message="Configuration error",
                details=f"Invalid YAML syntax{line_info}: {error_str}",
                fix_instructions="Check for missing quotes, incorrect indentation, or syntax errors",
                error_type="yaml_parse_error",
            )

        # Plugin loading errors
        if isinstance(error, ValueError) and (
            "handler" in error_str.lower() or "plugin" in error_str.lower()
        ):
            return StartupError(
                code=MCPErrorCodes.PLUGIN_LOADING_ERROR,
                message="Plugin loading failed",
                details=error_str,
                fix_instructions=(
                    error_str
                    if "Available handlers" in error_str
                    else "Check plugin configuration"
                ),
                error_type="plugin_error",
            )

        # Validation errors (Pydantic/Zod-style)
        if (
            "invalid_union" in error_str.lower()
            or "zoderror" in error_str.lower()
            or "validation" in error_str.lower()
            or "invalid_type" in error_str.lower()
        ):

            # Extract specific validation details
            specific_errors = self._extract_validation_details(error_str)

            if specific_errors:
                return StartupError(
                    code=MCPErrorCodes.CONFIGURATION_ERROR,
                    message="Configuration validation failed",
                    details=f"Validation errors found:\n{chr(10).join(specific_errors)}",
                    fix_instructions="Fix the validation errors listed above. Common issues: check data types, required fields, and valid values.",
                    error_type="validation_error",
                )
            else:
                # Fallback if we can't parse the errors
                return StartupError(
                    code=MCPErrorCodes.CONFIGURATION_ERROR,
                    message="Configuration validation failed",
                    details=error_str,
                    fix_instructions="Check your configuration file for validation errors. The error details above contain the specific issues.",
                    error_type="validation_error",
                )

        # Upstream server errors
        if "upstream" in context.lower() or "command not found" in error_str.lower():
            return StartupError(
                code=MCPErrorCodes.UPSTREAM_UNAVAILABLE,
                message="Upstream server error",
                details=error_str,
                fix_instructions="Ensure the upstream server command is installed and accessible",
                error_type="upstream_error",
            )

        # Generic error fallback
        return StartupError(
            code=MCPErrorCodes.INTERNAL_ERROR,
            message="Startup error",
            details=error_str,
            fix_instructions="Check the error details and Gatekit logs for more information",
            error_type="generic_error",
        )

    def _extract_validation_details(self, error_str: str) -> list:
        """Extract specific validation error details from error string.

        Args:
            error_str: The full error string containing validation details

        Returns:
            List of human-readable validation error messages
        """
        import re
        import json

        errors = []

        try:
            # Look for patterns like: "path": ["field"], "message": "Error message"
            # This handles both Pydantic and Zod-style validation errors

            # Pattern 1: Extract path and message pairs
            path_message_pattern = r'"path":\s*\[(.*?)\].*?"message":\s*"(.*?)"'
            matches = re.findall(path_message_pattern, error_str, re.DOTALL)

            for path_match, message in matches:
                # Parse the path (e.g., '"field"' or '"field", "subfield"')
                try:
                    # Clean up the path string and parse as JSON array
                    path_clean = f"[{path_match}]"
                    path_list = json.loads(path_clean)
                    field_path = " → ".join(str(p) for p in path_list)

                    if field_path:
                        errors.append(f"• Field '{field_path}': {message}")
                    else:
                        errors.append(f"• {message}")
                except (json.JSONDecodeError, ValueError):
                    # If path parsing fails, just use the message
                    errors.append(f"• {message}")

            # Pattern 2: Look for "Expected X, received Y" patterns
            type_error_pattern = r'"expected":\s*"(.*?)".*?"received":\s*"(.*?)"'
            type_matches = re.findall(type_error_pattern, error_str)

            for expected, received in type_matches:
                if expected and received:
                    errors.append(
                        f"• Type error: expected {expected}, but got {received}"
                    )

            # Pattern 3: Look for "Required" field errors
            required_pattern = r'"message":\s*"Required".*?"path":\s*\[(.*?)\]'
            required_matches = re.findall(required_pattern, error_str)

            for path_match in required_matches:
                try:
                    path_clean = f"[{path_match}]"
                    path_list = json.loads(path_clean)
                    field_path = " → ".join(str(p) for p in path_list)
                    errors.append(f"• Missing required field: '{field_path}'")
                except (json.JSONDecodeError, ValueError):
                    errors.append("• Missing required field")

            # Remove duplicates while preserving order
            seen = set()
            unique_errors = []
            for error in errors:
                if error not in seen:
                    seen.add(error)
                    unique_errors.append(error)

            return unique_errors[
                :10
            ]  # Limit to first 10 errors to avoid overwhelming output

        except Exception:
            # If parsing fails completely, return empty list to use fallback
            return []

    def _config_error_to_startup_error(self, config_error: "ConfigError") -> StartupError:
        """Convert a ConfigError to a StartupError with all its structured info.

        Args:
            config_error: The ConfigError to convert

        Returns:
            StartupError with the structured information from ConfigError
        """
        # Build detailed message with location info (don't repeat the message)
        details_parts = []

        if config_error.file_path:
            details_parts.append(f"File: {config_error.file_path}")
        if config_error.line_number:
            details_parts.append(f"Line: {config_error.line_number}")
        if config_error.line_snippet:
            details_parts.append(f"Content: {config_error.line_snippet}")
        if config_error.field_path:
            details_parts.append(f"Field: {config_error.field_path}")

        details = "\n".join(details_parts)

        # Build fix instructions from suggestions
        if config_error.suggestions:
            fix_instructions = "\n".join(
                f"• {suggestion}" for suggestion in config_error.suggestions
            )
        else:
            fix_instructions = "Check configuration file for errors"

        # Map error type to appropriate code
        if config_error.error_type == "yaml_syntax":
            code = MCPErrorCodes.CONFIGURATION_ERROR
        elif config_error.error_type == "missing_plugin":
            code = MCPErrorCodes.PLUGIN_LOADING_ERROR
        elif config_error.error_type == "validation_error":
            code = MCPErrorCodes.CONFIGURATION_ERROR
        else:
            code = MCPErrorCodes.CONFIGURATION_ERROR

        error_context = {}
        if config_error.file_path:
            error_context["file_path"] = str(config_error.file_path)
        if config_error.line_number:
            error_context["line_number"] = config_error.line_number

        return StartupError(
            code=code,
            message=config_error.message,
            details=details,
            fix_instructions=fix_instructions,
            error_type=config_error.error_type,
            error_context=error_context if error_context else None,
        )
