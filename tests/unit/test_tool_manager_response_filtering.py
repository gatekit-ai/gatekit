"""Tests for ToolManagerPlugin response filtering."""

import pytest

from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
from gatekit.protocol.messages import MCPRequest, MCPResponse


class TestToolsListResponseFiltering:
    """Tests around filtering and renaming tools/list responses."""

    @pytest.fixture
    def plugin(self):
        config = {
            "tools": [
                {"tool": "read_file"},
                {"tool": "write_file"},
                {"tool": "create_directory"},
            ]
        }
        return ToolManagerPlugin(config)

    @pytest.fixture
    def tools_list_request(self):
        return MCPRequest(jsonrpc="2.0", method="tools/list", id="req-1", params={})

    @pytest.fixture
    def tools_list_response_multiple_tools(self):
        return MCPResponse(
            jsonrpc="2.0",
            id="req-1",
            result={
                "tools": [
                    {"name": "read_file", "description": "Read a file"},
                    {"name": "write_file", "description": "Write a file"},
                    {"name": "dangerous_tool", "description": "Danger"},
                    {"name": "create_directory", "description": "Create directory"},
                ]
            },
        )

    @pytest.mark.asyncio
    async def test_tools_list_response_filtering(
        self, plugin, tools_list_request, tools_list_response_multiple_tools
    ):
        decision = await plugin.process_response(
            tools_list_request,
            tools_list_response_multiple_tools,
            server_name="filesystem",
        )
        assert decision.modified_content is not None
        filtered_tools = decision.modified_content.result["tools"]
        tool_names = [tool["name"] for tool in filtered_tools]
        assert set(tool_names) == {"read_file", "write_file", "create_directory"}
        assert decision.metadata == {
            "hidden_count": 1,
            "invalid_count": 0,
            "rename_count": 0,
            "description_override_count": 0,
            "total_tools": 4,
            "policy": "allowlist",
        }

    @pytest.mark.asyncio
    async def test_non_tools_list_responses_unchanged(self, plugin):
        tools_call_request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id="call", params={"name": "read_file"}
        )
        tools_call_response = MCPResponse(
            jsonrpc="2.0", id="call", result={"content": "data"}
        )
        decision = await plugin.process_response(
            tools_call_request, tools_call_response, server_name="filesystem"
        )
        assert decision.modified_content is None
        assert decision.completed_response is None

    @pytest.mark.asyncio
    async def test_malformed_tools_list_response_handling(
        self, plugin, tools_list_request
    ):
        malformed_response = MCPResponse(jsonrpc="2.0", id="req-1", result={})
        decision = await plugin.process_response(
            tools_list_request, malformed_response, server_name="filesystem"
        )
        assert decision.modified_content is None
        assert decision.completed_response is None

    @pytest.mark.asyncio
    async def test_tool_objects_missing_name_field(self, plugin, tools_list_request):
        response_with_invalid_tools = MCPResponse(
            jsonrpc="2.0",
            id="req-1",
            result={
                "tools": [
                    {"name": "read_file", "description": "Read"},
                    {"description": "Missing name"},
                    {"name": "", "description": "Empty"},
                    {"name": "write_file", "description": "Write"},
                ]
            },
        )
        decision = await plugin.process_response(
            tools_list_request, response_with_invalid_tools, server_name="filesystem"
        )
        assert decision.modified_content is not None
        tool_names = [
            tool["name"] for tool in decision.modified_content.result["tools"]
        ]
        assert tool_names == ["read_file", "write_file"]
        assert decision.metadata["invalid_count"] == 2

    @pytest.mark.asyncio
    async def test_hides_all_when_allowlist_empty(self, tools_list_request):
        plugin = ToolManagerPlugin({"tools": []})
        response_with_tools = MCPResponse(
            jsonrpc="2.0",
            id="req-1",
            result={"tools": [{"name": "read_file"}, {"name": "write_file"}]},
        )
        decision = await plugin.process_response(
            tools_list_request, response_with_tools, server_name="filesystem"
        )
        assert decision.modified_content is not None
        assert decision.modified_content.result["tools"] == []
        assert decision.metadata["hidden_count"] == 2

    @pytest.mark.asyncio
    async def test_filtering_preserves_additional_attributes(
        self, plugin, tools_list_request
    ):
        response_with_rich_tools = MCPResponse(
            jsonrpc="2.0",
            id="req-1",
            result={
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file from disk",
                        "inputSchema": {"type": "object"},
                        "custom": "value",
                    },
                    {"name": "blocked", "description": "Blocked"},
                ]
            },
        )
        decision = await plugin.process_response(
            tools_list_request, response_with_rich_tools, server_name="filesystem"
        )
        assert decision.modified_content is not None
        tool = decision.modified_content.result["tools"][0]
        assert tool["name"] == "read_file"
        assert tool["description"] == "Read a file from disk"
        assert tool["inputSchema"] == {"type": "object"}
        assert tool["custom"] == "value"


class TestToolsListDescriptionOverride:
    """Tests for description-only overrides (no rename)."""

    @pytest.fixture
    def plugin_with_description_override(self):
        config = {
            "tools": [
                {"tool": "read_file"},
                {
                    "tool": "query_docs",
                    "display_description": "Custom description for query_docs",
                },
            ]
        }
        return ToolManagerPlugin(config)

    @pytest.fixture
    def tools_list_request(self):
        return MCPRequest(jsonrpc="2.0", method="tools/list", id="desc", params={})

    @pytest.mark.asyncio
    async def test_description_only_override_applied(
        self, plugin_with_description_override, tools_list_request
    ):
        """Test that display_description works without display_name."""
        response = MCPResponse(
            jsonrpc="2.0",
            id="desc",
            result={
                "tools": [
                    {"name": "read_file", "description": "Original read description"},
                    {"name": "query_docs", "description": "Original query description"},
                    {"name": "hidden_tool", "description": "This should be hidden"},
                ]
            },
        )
        decision = await plugin_with_description_override.process_response(
            tools_list_request, response, server_name="server"
        )
        assert decision.modified_content is not None
        tool_map = {
            tool["name"]: tool for tool in decision.modified_content.result["tools"]
        }
        # Name should be unchanged
        assert "query_docs" in tool_map
        # Description should be overridden
        assert tool_map["query_docs"]["description"] == "Custom description for query_docs"
        # read_file should keep original description
        assert tool_map["read_file"]["description"] == "Original read description"
        # hidden_tool should be hidden
        assert "hidden_tool" not in tool_map
        # Check metadata
        assert decision.metadata["description_override_count"] == 1
        assert decision.metadata["hidden_count"] == 1
        assert decision.metadata["rename_count"] == 0


class TestToolsListResponseRenaming:
    """Renaming behaviour tests."""

    @pytest.fixture
    def plugin_with_renaming(self):
        config = {
            "tools": [
                {"tool": "read_file"},
                {
                    "tool": "execute",
                    "display_name": "execute_sql",
                    "display_description": "Execute SQL statements",
                },
                {"tool": "query", "display_name": "query_db"},
            ]
        }
        return ToolManagerPlugin(config)

    @pytest.fixture
    def tools_list_request(self):
        return MCPRequest(jsonrpc="2.0", method="tools/list", id="rename", params={})

    @pytest.mark.asyncio
    async def test_tools_renamed_in_allowlist(
        self, plugin_with_renaming, tools_list_request
    ):
        response = MCPResponse(
            jsonrpc="2.0",
            id="rename",
            result={
                "tools": [
                    {"name": "read_file", "description": "Read"},
                    {"name": "execute", "description": "Run"},
                    {"name": "query", "description": "Query"},
                    {"name": "dangerous_tool", "description": "Danger"},
                ]
            },
        )
        decision = await plugin_with_renaming.process_response(
            tools_list_request, response, server_name="server"
        )
        assert decision.modified_content is not None
        tool_map = {
            tool["name"]: tool for tool in decision.modified_content.result["tools"]
        }
        assert "execute_sql" in tool_map
        assert tool_map["execute_sql"]["description"] == "Execute SQL statements"
        assert "query_db" in tool_map
        assert tool_map["query_db"]["description"] == "Query"
        assert "dangerous_tool" not in tool_map
        assert decision.metadata["rename_count"] == 2
        assert decision.metadata["hidden_count"] == 1
        assert decision.metadata["policy"] == "allowlist"
