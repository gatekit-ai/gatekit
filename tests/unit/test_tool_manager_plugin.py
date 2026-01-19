"""Tests for the ToolManagerPlugin middleware plugin."""

import pytest

from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestToolManagerPluginConfiguration:
    """Configuration parsing and validation tests."""

    def test_valid_tools_config(self):
        config = {"tools": [{"tool": "read_file"}, {"tool": "list_directory"}]}
        plugin = ToolManagerPlugin(config)
        assert plugin.policy == "allowlist"
        assert plugin.tools == ["read_file", "list_directory"]
        assert plugin.rename_map == {}
        assert plugin.reverse_map == {}

    def test_valid_tools_config_with_renaming(self):
        config = {
            "tools": [
                {
                    "tool": "execute",
                    "display_name": "run_script",
                    "display_description": "Execute scripts",
                },
                {"tool": "query", "display_name": "query_database"},
            ]
        }
        plugin = ToolManagerPlugin(config)
        assert plugin.tools == ["execute", "query"]
        assert plugin.rename_map["execute"] == ("run_script", "Execute scripts")
        assert plugin.rename_map["query"] == ("query_database", None)
        assert plugin.reverse_map["run_script"] == "execute"
        assert plugin.reverse_map["query_database"] == "query"

    def test_empty_tools_blocks_all(self):
        plugin = ToolManagerPlugin({"tools": []})
        assert plugin.tools == []
        assert plugin.policy == "allowlist"

    def test_rejects_legacy_mode_field(self):
        config = {"mode": "allowlist", "tools": [{"tool": "read"}]}
        with pytest.raises(ValueError, match="no longer supported"):
            ToolManagerPlugin(config)

    def test_rejects_legacy_action_field(self):
        config = {"tools": [{"tool": "read_file", "action": "allow"}]}
        with pytest.raises(ValueError, match="Unsupported fields"):
            ToolManagerPlugin(config)

    # Note: test_invalid_display_name_format removed - schema validates pattern
    # See tests/unit/test_schema_validation_coverage.py

    def test_display_description_must_be_string(self):
        config = {"tools": [{"tool": "execute", "display_description": 123}]}
        with pytest.raises(ValueError, match="must be a string"):
            ToolManagerPlugin(config)

    def test_self_mapping_error(self):
        config = {"tools": [{"tool": "execute", "display_name": "execute"}]}
        with pytest.raises(ValueError, match="Cannot rename 'execute' to itself"):
            ToolManagerPlugin(config)

    def test_duplicate_renamed_name_error(self):
        config = {
            "tools": [
                {"tool": "execute", "display_name": "new_tool"},
                {"tool": "query", "display_name": "new_tool"},
            ]
        }
        with pytest.raises(ValueError, match="already renamed to 'new_tool'"):
            ToolManagerPlugin(config)

    def test_duplicate_tool_error(self):
        config = {"tools": [{"tool": "read_file"}, {"tool": "read_file"}]}
        with pytest.raises(ValueError, match="Duplicate entry for tool 'read_file'"):
            ToolManagerPlugin(config)

    def test_missing_tool_field_error(self):
        config = {"tools": [{}]}
        with pytest.raises(
            ValueError, match="Each tool entry must have a 'tool' field"
        ):
            ToolManagerPlugin(config)

    def test_invalid_config_not_dict(self):
        with pytest.raises(TypeError, match="Configuration must be a dictionary"):
            ToolManagerPlugin("not_a_dict")

    def test_missing_tools_field(self):
        with pytest.raises(
            ValueError, match="Configuration must include 'tools' field"
        ):
            ToolManagerPlugin({})

    def test_tools_not_list(self):
        with pytest.raises(TypeError, match="'tools' must be a list"):
            ToolManagerPlugin({"tools": "not_a_list"})

    def test_tool_entry_not_dict(self):
        with pytest.raises(TypeError, match="Each tool entry must be a dictionary"):
            ToolManagerPlugin({"tools": ["read_file"]})

    # Note: test_invalid_tool_name_format removed - schema validates pattern
    # See tests/unit/test_schema_validation_coverage.py

    def test_tool_name_with_hyphens_allowed(self):
        config = {"tools": [{"tool": "read-file"}, {"tool": "list-directory"}]}
        plugin = ToolManagerPlugin(config)
        assert plugin.tools == ["read-file", "list-directory"]

    def test_display_name_with_hyphens_allowed(self):
        config = {"tools": [{"tool": "execute", "display_name": "execute-sql-query"}]}
        plugin = ToolManagerPlugin(config)
        assert plugin.rename_map["execute"] == ("execute-sql-query", None)


class TestAllowlistBehavior:
    """Runtime behaviour tests for allowlist filtering."""

    @pytest.fixture
    def plugin(self):
        config = {
            "tools": [
                {"tool": "read_file"},
                {"tool": "list_directory"},
                {"tool": "execute", "display_name": "run_script"},
            ]
        }
        return ToolManagerPlugin(config)

    @pytest.mark.asyncio
    async def test_allows_listed_tool(self, plugin):
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="allow",
            params={"name": "read_file", "arguments": {}},
        )
        decision = await plugin.process_request(request, server_name="filesystem")
        assert decision.completed_response is None
        assert decision.modified_content is None

    @pytest.mark.asyncio
    async def test_hides_unlisted_tool(self, plugin):
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="deny",
            params={"name": "write_file", "arguments": {}},
        )
        decision = await plugin.process_request(request, server_name="filesystem")
        assert decision.completed_response is not None
        assert decision.completed_response.error["code"] == -32601
        assert "hidden by allowlist" in decision.reason
        assert decision.metadata["policy"] == "allowlist"

    @pytest.mark.asyncio
    async def test_translates_renamed_tool_request(self, plugin):
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="rename",
            params={"name": "run_script", "arguments": {}},
        )
        decision = await plugin.process_request(request, server_name="filesystem")
        assert decision.modified_content is not None
        assert decision.modified_content.params["name"] == "execute"
        assert decision.metadata["original_name"] == "execute"

    @pytest.mark.asyncio
    async def test_filters_tools_list_response(self, plugin):
        request = MCPRequest(jsonrpc="2.0", method="tools/list", id="list", params={})
        response = MCPResponse(
            jsonrpc="2.0",
            id="list",
            result={
                "tools": [
                    {"name": "read_file", "description": "Read"},
                    {"name": "list_directory", "description": "List"},
                    {"name": "execute", "description": "Exec"},
                    {"name": "delete_all", "description": "Danger"},
                ]
            },
        )

        decision = await plugin.process_response(
            request, response, server_name="filesystem"
        )
        assert decision.modified_content is not None
        renamed_tools = decision.modified_content.result["tools"]
        names = [tool["name"] for tool in renamed_tools]
        assert names == ["read_file", "list_directory", "run_script"]
        assert decision.metadata["hidden_count"] == 1
        assert decision.metadata["policy"] == "allowlist"
        assert "Hidden 1 tools" in decision.reason

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_passes_through_invalid_tools_list_payload(self, plugin):
        request = MCPRequest(jsonrpc="2.0", method="tools/list", id="list", params={})
        response = MCPResponse(jsonrpc="2.0", id="list", result={})

        decision = await plugin.process_response(
            request, response, server_name="filesystem"
        )
        assert decision.modified_content is None


class TestEdgeCases:
    """Edge-case handling."""

    @pytest.fixture
    def plugin(self):
        return ToolManagerPlugin({"tools": [{"tool": "test_tool"}]})

    @pytest.mark.asyncio
    async def test_missing_tool_name(self, plugin):
        request = MCPRequest(jsonrpc="2.0", method="tools/call", id="edge-1", params={})
        decision = await plugin.process_request(request, server_name="filesystem")
        assert decision.completed_response is None
        assert decision.modified_content is None

    @pytest.mark.asyncio
    async def test_none_tool_name(self, plugin):
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id="edge-2", params={"name": None}
        )
        decision = await plugin.process_request(request, server_name="filesystem")
        assert decision.completed_response is None
        assert decision.modified_content is None

    @pytest.mark.asyncio
    async def test_notification_passthrough(self, plugin):
        notification = MCPNotification(jsonrpc="2.0", method="tools/updated", params={})
        decision = await plugin.process_notification(
            notification, server_name="filesystem"
        )
        assert decision.completed_response is None
        assert decision.modified_content is None
        assert decision.metadata in (None, {})


class TestSchemaAndStatus:
    """Validate schema helpers and status description."""

    def test_json_schema_only_has_tools(self):
        schema = ToolManagerPlugin.get_json_schema()
        properties = schema["properties"]
        assert "mode" not in properties
        assert "tools" in properties
        tools_field = properties["tools"]
        assert tools_field["$ref"] == "#/$defs/tool_selection"
        tool_def = schema.get("$defs", {}).get("tool_selection", {})
        assert tool_def.get("type") == "array"
        item_schema = tool_def.get("items", {})
        assert "action" not in item_schema.get("properties", {})
        assert item_schema.get("required") == ["tool"]

    def test_describe_status_messages(self):
        base_config = {"enabled": True, "tools": []}
        assert ToolManagerPlugin.describe_status(base_config) == "Block all tools"

        config_with_tools = {
            "enabled": True,
            "tools": [
                {"tool": "read"},
                {"tool": "write", "display_name": "write_safe"},
            ],
        }
        status = ToolManagerPlugin.describe_status(config_with_tools)
        assert status == "Allow 2 tools, rename 1"

    def test_describe_status_not_configured(self):
        assert ToolManagerPlugin.describe_status({}) == "Not configured"
