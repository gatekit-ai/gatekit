"""Tool manager middleware plugin implementation."""

import logging
from typing import Dict, Any, List
from gatekit.plugins.interfaces import MiddlewarePlugin, PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


class ToolManagerPlugin(MiddlewarePlugin):
    """Middleware plugin for managing tool visibility and availability.

    This plugin controls which tools are exposed to clients through allowlist
    policies. Tools can be hidden for various reasons including
    context optimization, workflow simplification, or capability management.

    Note: This is NOT a security plugin. Tools are filtered at the middleware
    layer for operational purposes. For security-based tool restrictions,
    implement a separate SecurityPlugin.
    """

    # TUI Display Metadata
    DISPLAY_NAME = "Tool Manager"
    DESCRIPTION = "Control which tools are visible to MCP clients. Filter, rename, and modify tool descriptions."
    DISPLAY_SCOPE = (
        "server_aware"  # Universal plugin requiring per-server configuration
    )

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        """Generate status description from tool configuration."""
        if not config:
            return "Not configured"

        if not config.get("enabled", False):
            return "Optimize tool context for better agent performance"

        parts = []

        # Check for required fields
        if "tools" not in config:
            return "Not configured"

        tools = config["tools"]

        # Describe based on tool count
        tool_count = len(tools)
        rename_count = sum(1 for t in tools if "display_name" in t)

        if tool_count == 0:
            parts.append("Block all tools")
        else:
            parts.append(f"Allow {tool_count} tools")

        if rename_count > 0:
            parts.append(f"rename {rename_count}")

        return ", ".join(parts) if parts else "Not configured"

    @classmethod
    def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
        """Return actions based on configuration state."""
        if config and config.get("enabled", False):
            return ["Configure", "Test"]
        return ["Setup"]

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for Tool Manager configuration.

        Configure which tools are visible to MCP clients (allowlist).

        Empty tool list blocks all tools. Unchecked tools are hidden from the client.
        """
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/tool-manager.json",
            "type": "object",
            "description": "Tool Manager middleware plugin configuration",
            "properties": {
                # Note: enabled and priority are injected by framework
                # See gatekit/config/framework_fields.py
                "tools": {
                    "$ref": "#/$defs/tool_selection",
                    "description": "Select which tools are visible to the MCP client and modify names/descriptions.",
                    "default": [],
                },
            },
            "required": ["tools"],
            "additionalProperties": False,
            "$defs": {
                "tool_selection": {
                    "$id": "https://gatekit.ai/schemas/common/tool-selection.json",
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "title": "Tool Selection",
                    "description": "Array of tool entries with optional display overrides.",
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["tool"],
                        "properties": {
                            "tool": {
                                "type": "string",
                                "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$",
                                "description": "Canonical tool identifier. Must start with a letter and contain only letters, numbers, underscores, or hyphens.",
                            },
                            "display_name": {
                                "type": "string",
                                "pattern": "^[a-zA-Z][a-zA-Z0-9_-]*$",
                                "description": "Optional name override shown to clients. Must start with a letter and contain only letters, numbers, underscores, or hyphens.",
                            },
                            "display_description": {
                                "type": "string",
                                "description": "Optional description override shown to clients.",
                            },
                        },
                    },
                },
            },
        }

    def _parse_tools_config(
        self, tools: List[Dict[str, Any]]
    ) -> tuple[
        List[str], Dict[str, tuple[str, str | None]], Dict[str, str], Dict[str, str]
    ]:
        """Parse `tools` configuration into allowlist, rename, and description maps."""
        if not isinstance(tools, list):
            raise TypeError("'tools' must be a list")

        # Empty list is valid - blocks all tools
        if len(tools) == 0:
            return [], {}, {}, {}

        # First pass: collect all tool names and validate basic structure
        tool_list = []
        all_tool_names = []

        for i, tool_entry in enumerate(tools):
            if not isinstance(tool_entry, dict):
                raise TypeError(
                    f"Each tool entry must be a dictionary, got {type(tool_entry).__name__}"
                )

            if "tool" not in tool_entry:
                raise ValueError("Each tool entry must have a 'tool' field")

            unexpected_fields = set(tool_entry.keys()) - {
                "tool",
                "display_name",
                "display_description",
            }
            if unexpected_fields:
                identifier = tool_entry.get("tool", f"index {i}")
                raise ValueError(
                    f"Unsupported fields in tool entry '{identifier}': {sorted(unexpected_fields)}"
                )

            tool_name = tool_entry["tool"]

            # Validate tool name is a string (schema validates format)
            if not isinstance(tool_name, str):
                raise TypeError(
                    f"Tool name must be a string, got {type(tool_name).__name__}"
                )

            # Check for duplicates
            if tool_name in all_tool_names:
                raise ValueError(f"Duplicate entry for tool '{tool_name}'")
            all_tool_names.append(tool_name)
            tool_list.append(tool_name)

        # Second pass: process display fields and build rename/description maps
        rename_map = {}
        reverse_map = {}
        description_map = {}  # For description-only overrides (no rename)

        for tool_entry in tools:
            tool_name = tool_entry["tool"]

            # Handle optional display fields (schema validates type)
            if "display_description" in tool_entry:
                desc = tool_entry["display_description"]
                if not isinstance(desc, str):
                    raise ValueError(
                        f"Display description for tool '{tool_name}' must be a string, "
                        f"got {type(desc).__name__}"
                    )

            # Handle renaming if present
            if "display_name" in tool_entry:
                new_name = tool_entry["display_name"]

                # Validate new name is a string (schema validates format)
                if not isinstance(new_name, str):
                    raise ValueError(
                        f"Display name must be a string, got {type(new_name).__name__}"
                    )

                # Validate not self-mapping
                if tool_name == new_name:
                    raise ValueError(f"Cannot rename '{tool_name}' to itself")

                # Check for duplicate renamed names
                if new_name in reverse_map:
                    raise ValueError(
                        f"Cannot rename '{tool_name}' to '{new_name}': "
                        f"'{reverse_map[new_name]}' is already renamed to '{new_name}'"
                    )

                # Check for collision with original tool names
                if new_name in all_tool_names and new_name != tool_name:
                    raise ValueError(
                        f"Cannot rename '{tool_name}' to '{new_name}': "
                        f"a tool with name '{new_name}' already exists in the configuration"
                    )

                new_desc = tool_entry.get("display_description")
                rename_map[tool_name] = (new_name, new_desc)
                reverse_map[new_name] = tool_name
            elif "display_description" in tool_entry:
                # Description-only override (no rename)
                description_map[tool_name] = tool_entry["display_description"]

        return tool_list, rename_map, reverse_map, description_map

    def __init__(self, config: Dict[str, Any]):
        """Initialize plugin with configuration."""
        # Validate configuration type first
        if not isinstance(config, dict):
            raise TypeError("Configuration must be a dictionary")

        # Fail fast on legacy fields before super().__init__ mutates anything
        if "mode" in config:
            raise ValueError(
                "'mode' is no longer supported. Remove it to use implicit allowlist semantics."
            )

        # Initialize base class to set priority
        super().__init__(config)

        # Validate required fields
        if "tools" not in config:
            raise ValueError("Configuration must include 'tools' field")

        # Parse tools configuration
        (
            self.tools,
            self.rename_map,
            self.reverse_map,
            self.description_map,
        ) = self._parse_tools_config(config["tools"])
        self.policy = "allowlist"

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Process tool invocations, filtering tools based on policy.

        Args:
            request: The MCP request to process
            server_name: Name of the target server

        Returns:
            PluginResult with completed_response if tool is hidden
        """
        # Only process tools/call requests
        if request.method != "tools/call":
            return PluginResult()  # Pass through unchanged

        tool_name = request.params.get("name") if request.params else None
        if not tool_name:
            return PluginResult()

        # Check if this is a renamed tool
        original_name = self.reverse_map.get(tool_name, tool_name)

        # If renamed, create modified request with original name
        modified_request = None
        if original_name != tool_name:
            modified_params = {**request.params, "name": original_name}
            modified_request = MCPRequest(
                jsonrpc=request.jsonrpc,
                id=request.id,
                method=request.method,
                params=modified_params,
            )

        # Check if tool should be hidden using ORIGINAL name
        should_hide = original_name not in self.tools

        if should_hide:
            # Return error response for hidden tool
            error_response = MCPResponse(
                jsonrpc=request.jsonrpc,
                id=request.id,
                error={
                    "code": -32601,  # Method not found
                    "message": f"Tool '{tool_name}' is not available",
                    "data": {"reason": "hidden_by_policy", "plugin": "tool_manager"},
                },
            )

            return PluginResult(
                completed_response=error_response,
                reason=f"Tool '{tool_name}' (original name '{original_name}') hidden by allowlist policy",
                metadata={
                    "hidden_tool": tool_name,
                    "original_name": original_name,
                    "policy": self.policy,
                },
            )

        # Tool is allowed - return modified request if we renamed it
        if modified_request:
            return PluginResult(
                modified_content=modified_request,
                reason=f"Translated tool name '{tool_name}' to '{original_name}'",
                metadata={"renamed_tool": tool_name, "original_name": original_name},
            )

        # Tool is allowed, pass through
        return PluginResult()

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Filter and rename tools from tools/list responses based on policy.

        Args:
            request: The original MCP request
            response: The MCP response to process
            server_name: Name of the source server

        Returns:
            PluginResult with modified_content if tools were hidden or renamed
        """
        # Only process tools/list responses
        if request.method != "tools/list" or not response.result:
            return PluginResult()

        tools = response.result.get("tools", [])
        if not tools or not isinstance(tools, list):
            return PluginResult()

        # First, filter tools based on configuration
        filtered_tools = []
        hidden_count = 0
        invalid_count = 0

        for tool in tools:
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if not tool_name or not isinstance(tool_name, str) or tool_name == "":
                # Skip tools with invalid names entirely
                invalid_count += 1
                continue

            should_hide = tool_name not in self.tools

            if should_hide:
                hidden_count += 1
                logger.debug(f"Hiding tool '{tool_name}' from tools/list response")
            else:
                filtered_tools.append(tool)

        # Apply renaming and description overrides to filtered tools
        renamed_tools = []
        rename_count = 0
        description_override_count = 0

        for tool in filtered_tools:
            tool_name = tool["name"]  # We know this exists from filtering

            if tool_name in self.rename_map:
                new_name, new_description = self.rename_map[tool_name]

                # Create modified tool with new name/description
                renamed_tool = {**tool}  # Copy all attributes
                renamed_tool["name"] = new_name

                if new_description is not None:
                    renamed_tool["description"] = new_description

                renamed_tools.append(renamed_tool)
                rename_count += 1
                logger.debug(f"Renamed tool '{tool_name}' to '{new_name}'")
            elif tool_name in self.description_map:
                # Description-only override (no rename)
                modified_tool = {**tool}
                modified_tool["description"] = self.description_map[tool_name]
                renamed_tools.append(modified_tool)
                description_override_count += 1
                logger.debug(f"Updated description for tool '{tool_name}'")
            else:
                # Keep tool unchanged
                renamed_tools.append(tool)

        # Return modified response if any changes were made
        if (
            hidden_count > 0
            or invalid_count > 0
            or rename_count > 0
            or description_override_count > 0
        ):
            # Create modified response preserving all original fields
            modified_result = {**response.result, "tools": renamed_tools}

            modified_response = MCPResponse(
                jsonrpc=response.jsonrpc,
                id=response.id,
                result=modified_result,
                error=response.error if hasattr(response, "error") else None,
                sender_context=(
                    response.sender_context
                    if hasattr(response, "sender_context")
                    else None
                ),
            )

            reasons = []
            if hidden_count > 0:
                reasons.append(f"Hidden {hidden_count} tools based on allowlist policy")
            if invalid_count > 0:
                reasons.append(f"Removed {invalid_count} invalid tools")
            if rename_count > 0:
                reasons.append(f"Renamed {rename_count} tools")
            if description_override_count > 0:
                reasons.append(
                    f"Updated descriptions for {description_override_count} tools"
                )

            return PluginResult(
                modified_content=modified_response,
                reason="; ".join(reasons),
                metadata={
                    "hidden_count": hidden_count,
                    "invalid_count": invalid_count,
                    "rename_count": rename_count,
                    "description_override_count": description_override_count,
                    "total_tools": len(tools),
                    "policy": self.policy,
                },
            )

        return PluginResult()


# Handler manifest for policy-based plugin discovery
HANDLERS = {"tool_manager": ToolManagerPlugin}
