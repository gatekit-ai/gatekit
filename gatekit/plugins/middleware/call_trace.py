"""Call Trace middleware plugin for Gatekit.

This plugin appends diagnostic trace information to tool responses, demonstrating
Gatekit's middleware capabilities while providing immediate value to users.

Purpose:
    - Demonstrate middleware plugin capabilities (interception, state tracking, content modification)
    - Provide request correlation for audit log lookup
    - Show multi-server routing visibility

Middleware Capabilities Demonstrated:
    - Intercepting requests and responses
    - Tracking state across request/response cycle
    - Modifying response content
    - Extracting and formatting metadata

Use this plugin as a reference implementation when building your own middleware plugins.

Configuration:
    enabled: bool - Enable/disable plugin (default: true)
    priority: int - Execution order, 0-100 (default: 90, runs after other middleware)
    max_param_length: int - Max characters for parameter display (default: 200)
    trace_fields: object - Configure which fields to include in trace output
        server: bool - Show server name (default: true)
        tool: bool - Show tool name (default: true)
        params: bool - Show parameters (default: true)
        response_size: bool - Show response size (default: true)
        duration: bool - Show duration (default: true)
        request_id: bool - Show request ID (default: true)
        timestamp: bool - Show timestamp (default: true)

Example output:
    ---
    🔍 **Gatekit Gateway Trace**
    - Server: filesystem
    - Tool: read_file
    - Params: {"path": "/home/user/projects/gatekit/config/loader.py"}
    - Response: 2.3 KB
    - Duration: 45ms
    - Request ID: 1
    - Timestamp: 2025-01-12T15:30:45Z

    Search your audit logs near timestamp 2025-01-12T15:30:45Z (request_id: 1) to see the audit trail for this request.
    To find audit log locations, open your Gatekit config using `gatekit <path_to_config.yaml>`
    ---
"""

import logging
import time
import json
from typing import Dict, Any, Union, Optional
from datetime import datetime, timezone

from gatekit.plugins.interfaces import MiddlewarePlugin, PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


class CallTracePlugin(MiddlewarePlugin):
    """Middleware plugin for appending diagnostic trace information to tool responses.

    This plugin tracks request timing, extracts tool metadata, and appends a formatted
    trace block to successful tools/call responses. The trace provides visibility into
    Gatekit's processing and helps users correlate requests with audit logs.

    How it works:
        - Stores request start times to calculate duration
        - Processes tools/call responses to append trace information
        - Skips error responses (they use error field, not result)
        - Fails open - exceptions don't break requests

    Known Issues:
        MCP servers that return both `content` and `structuredContent` in their responses
        may not display the trace in Claude Code. The trace is appended to the `content`
        array, but Claude Code appears to prefer displaying `structuredContent` when both
        are present. This affects servers like `memory` and `sequential-thinking`. The
        trace IS recorded in audit logs regardless of client display behavior.
    """

    # TUI Display Metadata
    DISPLAY_NAME = "Call Trace"
    DESCRIPTION = "Append diagnostic trace information to tool responses for debugging and audit log correlation."
    DISPLAY_SCOPE = "global"  # Plugin applies to all servers

    def __init__(self, config: Dict[str, Any]):
        """Initialize the Call Trace plugin.

        Args:
            config: Plugin configuration dictionary with optional keys:
                - max_param_length: Maximum characters for parameter display (default: 200)
                - priority: Plugin execution priority (default: 90)
                - critical: Whether plugin failures should fail closed (default: False)
                - trace_fields: Object containing field visibility flags (all default: True):
                    - server: Show server name
                    - tool: Show tool name
                    - params: Show parameters
                    - response_size: Show response size
                    - duration: Show duration
                    - request_id: Show request ID
                    - timestamp: Show timestamp
        """
        if "priority" not in config:
            config["priority"] = 90

        super().__init__(config)

        self._max_param_length = config.get("max_param_length", 200)
        self._request_times: Dict[Union[str, int], float] = {}

        # Read configuration flags for which fields to display
        trace_fields = config.get("trace_fields", {})
        self._include_server = trace_fields.get("server", True)
        self._include_tool = trace_fields.get("tool", True)
        self._include_params = trace_fields.get("params", True)
        self._include_response_size = trace_fields.get("response_size", True)
        self._include_duration = trace_fields.get("duration", True)
        self._include_request_id = trace_fields.get("request_id", True)
        self._include_timestamp = trace_fields.get("timestamp", True)

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON schema for TUI configuration.

        This schema drives the TUI configuration dialog, showing how to implement
        grouped checkbox configuration options in custom plugins.

        Returns:
            JSON Schema defining the plugin's configuration structure
        """
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/call-trace.json",
            "type": "object",
            "description": "Call Trace middleware plugin configuration",
            "properties": {
                "max_param_length": {
                    "type": "integer",
                    "title": "Max parameter length",
                    "description": "Maximum characters to display for tool parameters (truncated with '...' if longer)",
                    "default": 200,
                    "minimum": 0,
                },
                "trace_fields": {
                    "type": "object",
                    "title": "Trace Fields",
                    "description": "Configure which fields to include in the trace output appended to tool responses",
                    "properties": {
                        "server": {
                            "type": "boolean",
                            "title": "Server name",
                            "description": "Include which server handled the request",
                            "default": True,
                        },
                        "tool": {
                            "type": "boolean",
                            "title": "Tool name",
                            "description": "Include which tool was called",
                            "default": True,
                        },
                        "params": {
                            "type": "boolean",
                            "title": "Parameters",
                            "description": "Include tool call parameters (respects max_param_length setting)",
                            "default": True,
                        },
                        "response_size": {
                            "type": "boolean",
                            "title": "Response size",
                            "description": "Include response size in human-readable format (e.g., '2.3 KB')",
                            "default": True,
                        },
                        "duration": {
                            "type": "boolean",
                            "title": "Duration",
                            "description": "Include request processing time in milliseconds",
                            "default": True,
                        },
                        "request_id": {
                            "type": "boolean",
                            "title": "Request ID",
                            "description": "Include MCP request identifier for audit log correlation",
                            "default": True,
                        },
                        "timestamp": {
                            "type": "boolean",
                            "title": "Timestamp",
                            "description": "Include ISO 8601 timestamp of when request was processed",
                            "default": True,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        }

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Store request start time for duration calculation.

        Args:
            request: The MCP request to process
            server_name: Name of the target server

        Returns:
            PluginResult with empty content (pass through unchanged)
        """
        # Store request start time
        if request.id is not None:
            self._request_times[request.id] = time.time()

        return PluginResult()

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Append trace information to successful tools/call responses.

        Args:
            request: The original MCP request
            response: The MCP response to process
            server_name: Name of the source server

        Returns:
            PluginResult with modified_content containing the trace, or empty for pass-through
        """
        # Clean up request time (whether we trace or not)
        start_time = self._request_times.pop(request.id, None) if request.id is not None else None

        try:
            # Skip error responses - they use error field, not result
            if hasattr(response, "error") and response.error is not None:
                return PluginResult()

            # Only process tools/call methods
            if request.method != "tools/call":
                return PluginResult()

            # Calculate duration
            duration_str = self._calculate_duration(start_time)

            # Extract tool name from request
            tool_name = self._extract_tool_name(request)

            # Format parameters
            params_str = self._format_params(request)

            # Calculate response size
            response_size = self._calculate_response_size(response)

            # Get current timestamp
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            # Format request ID
            request_id_str = str(request.id) if request.id is not None else "N/A"

            # Build trace text
            trace_text = self._build_trace_text(
                server_name=server_name,
                tool_name=tool_name,
                params_str=params_str,
                response_size=response_size,
                duration_str=duration_str,
                request_id_str=request_id_str,
                timestamp=timestamp
            )

            # Create modified response with trace appended
            modified_response = self._append_trace_to_response(response, trace_text)

            return PluginResult(modified_content=modified_response)

        except Exception as e:
            # Fail open - log error but return unmodified response
            logger.warning(f"Call trace plugin error: {e}", exc_info=True)
            return PluginResult()

    def _calculate_duration(self, start_time: Optional[float]) -> str:
        """Calculate request duration from start time.

        Args:
            start_time: The request start time (from time.time())

        Returns:
            Formatted duration string (e.g., "45ms") or "N/A" if not found
        """
        if start_time is None:
            return "N/A"

        duration_ms = int((time.time() - start_time) * 1000)
        return f"{duration_ms}ms"

    def _extract_tool_name(self, request: MCPRequest) -> str:
        """Extract tool name from tools/call request.

        Args:
            request: The MCP request

        Returns:
            Tool name or "[Unknown]" if not found
        """
        if isinstance(request.params, dict):
            return request.params.get("name", "[Unknown]")
        return "[Unknown]"

    def _format_params(self, request: MCPRequest) -> str:
        """Format request parameters as JSON string with truncation.

        Args:
            request: The MCP request

        Returns:
            Formatted and potentially truncated parameter string
        """
        # Extract arguments from params
        if isinstance(request.params, dict) and "arguments" in request.params:
            params = request.params["arguments"]
        else:
            params = {}

        # Serialize to JSON
        params_json = json.dumps(params, ensure_ascii=False)

        # Truncate if needed
        if len(params_json) > self._max_param_length:
            params_json = params_json[:self._max_param_length] + "..."

        return params_json

    def _calculate_response_size(self, response: MCPResponse) -> str:
        """Calculate and format response size.

        Args:
            response: The MCP response

        Returns:
            Human-readable size string (e.g., "2.3 KB")
        """
        # Serialize response to JSON to get accurate size
        response_json = json.dumps(response.result)
        size_bytes = len(response_json.encode("utf-8"))
        return self._format_size(size_bytes)

    def _format_size(self, size_bytes: int) -> str:
        """Format bytes into human-readable size.

        Args:
            size_bytes: Size in bytes

        Returns:
            Formatted size string (e.g., "2.3 KB", "1.5 MB")
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / (1024 ** 2):.1f} MB"
        else:
            return f"{size_bytes / (1024 ** 3):.1f} GB"

    def _build_trace_text(
        self,
        server_name: str,
        tool_name: str,
        params_str: str,
        response_size: str,
        duration_str: str,
        request_id_str: str,
        timestamp: str
    ) -> str:
        """Build the formatted trace text with configurable fields.

        Args:
            server_name: Name of the server that handled the request
            tool_name: Name of the tool that was called
            params_str: Formatted parameters string
            response_size: Formatted response size string
            duration_str: Formatted duration string
            request_id_str: Request ID as string
            timestamp: ISO 8601 timestamp

        Returns:
            Formatted trace text in markdown, with fields included based on configuration
        """
        trace_lines = [
            "---",
            "🔍 **Gatekit Gateway Trace**",
        ]

        # Add fields based on configuration
        if self._include_server:
            trace_lines.append(f"- Server: {server_name}")
        if self._include_tool:
            trace_lines.append(f"- Tool: {tool_name}")
        if self._include_params:
            trace_lines.append(f"- Params: {params_str}")
        if self._include_response_size:
            trace_lines.append(f"- Response: {response_size}")
        if self._include_duration:
            trace_lines.append(f"- Duration: {duration_str}")
        if self._include_request_id:
            trace_lines.append(f"- Request ID: {request_id_str}")
        if self._include_timestamp:
            trace_lines.append(f"- Timestamp: {timestamp}")

        # Add footer with audit log hint if we have timestamp or request_id
        if self._include_timestamp or self._include_request_id:
            trace_lines.append("")
            # Build footer message based on what's included
            if self._include_timestamp and self._include_request_id:
                trace_lines.append(
                    f"Search your audit logs near timestamp {timestamp} "
                    f"(request_id: {request_id_str}) to see the audit trail for this request."
                )
            elif self._include_timestamp:
                trace_lines.append(
                    f"Search your audit logs near timestamp {timestamp} "
                    "to see the audit trail for this request."
                )
            else:  # only request_id
                trace_lines.append(
                    f"Search your audit logs for request_id: {request_id_str} "
                    "to see the audit trail for this request."
                )
            trace_lines.append(
                "To find audit log locations, open your Gatekit config using "
                "`gatekit <path_to_config.yaml>`"
            )

        trace_lines.append("---")
        return "\n".join(trace_lines)

    def _append_trace_to_response(
        self, response: MCPResponse, trace_text: str
    ) -> MCPResponse:
        """Append trace text block to response content.

        Handles both MCP-spec-compliant responses (with content array) and
        non-standard responses (arbitrary JSON structures without content array).

        For spec-compliant responses: Appends trace as additional content block.
        For non-standard responses: Wraps original result in content array with trace.

        Args:
            response: The original response
            trace_text: The formatted trace text

        Returns:
            Modified response with trace appended
        """
        result = response.result

        # Case 1: Standard MCP tools/call response with content array
        if (
            isinstance(result, dict)
            and "content" in result
            and isinstance(result.get("content"), list)
        ):
            modified_result = {
                **result,
                "content": [
                    *result["content"],
                    {"type": "text", "text": trace_text}
                ]
            }
        # Case 2: Non-standard response (dict without content array, e.g., memory server)
        elif isinstance(result, dict):
            # Serialize original result as JSON and wrap in content array
            original_text = json.dumps(result, ensure_ascii=False, indent=2)
            modified_result = {
                "content": [
                    {"type": "text", "text": original_text},
                    {"type": "text", "text": trace_text}
                ]
            }
            logger.debug(
                "Response lacked standard 'content' array structure, "
                "wrapped result in content array for trace appending"
            )
        # Case 3: Non-dict result (list, primitive, etc.)
        else:
            # Serialize whatever it is and wrap in content array
            original_text = json.dumps(result, ensure_ascii=False, indent=2)
            modified_result = {
                "content": [
                    {"type": "text", "text": original_text},
                    {"type": "text", "text": trace_text}
                ]
            }
            logger.debug(
                "Response result was not a dict, "
                "wrapped result in content array for trace appending"
            )

        return MCPResponse(
            jsonrpc=response.jsonrpc,
            id=response.id,
            result=modified_result,
            sender_context=response.sender_context
        )


# Handler registration
HANDLERS = {
    "call_trace": CallTracePlugin
}
