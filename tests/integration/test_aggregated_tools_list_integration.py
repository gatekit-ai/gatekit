"""Integration tests for aggregated tools/list processing.

This module tests the _process_aggregated_tools_list_response functionality
and associated control flow with mock servers to ensure comprehensive coverage
of edge cases and regression prevention.
"""

import pytest
from unittest.mock import AsyncMock, patch
from gatekit.protocol.messages import MCPRequest, MCPResponse
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import PipelineOutcome
from gatekit.transport.base import Transport


class MockMultiServerTransport(Transport):
    """Mock transport that simulates multiple MCP servers responding."""

    def __init__(self, server_responses=None):
        self.server_responses = server_responses or {}
        self.sent_messages = []
        self._connected = False

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    async def send_message(self, message):
        self.sent_messages.append(message)

    async def send_notification(self, notification):
        self.sent_messages.append(notification)

    async def receive_message(self):
        # Not used in these tests
        return None

    async def send_and_receive(self, message):
        self.sent_messages.append(message)
        # Return different responses based on configured server responses
        return self.server_responses.get(
            "default", MCPResponse(jsonrpc="2.0", id=message.id, result={"tools": []})
        )

    async def get_next_notification(self):
        import asyncio

        await asyncio.sleep(10)  # Hang forever since we don't expect notifications
        return None


class TestAggregatedToolsListIntegration:
    """Test aggregated tools/list processing with comprehensive mock scenarios."""

    def create_plugin_config(self):
        """Create plugin configuration dictionary."""
        return {
            "middleware": {
                "_global": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "config": {
                            "tools": [
                                {"tool": "filesystem__read_file"},
                                {"tool": "filesystem__list_directory"},
                                {"tool": "api__get_data"},
                                {"tool": "api__post_data"},
                                {"tool": "github__create_issue"},
                                {"tool": "github__get_repo"},
                            ]
                        },
                    }
                ],
                "filesystem": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "config": {
                            "tools": [{"tool": "read_file"}, {"tool": "list_directory"}]
                        },
                    }
                ],
                "github": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "config": {
                            "tools": [{"tool": "create_issue"}, {"tool": "get_repo"}]
                        },
                    }
                ],
                "api": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "config": {
                            "tools": [{"tool": "get_data"}, {"tool": "post_data"}]
                        },
                    }
                ],
            },
            "auditing": {"_global": []},
        }

    def create_aggregated_tools_response(self):
        """Create a mock aggregated tools response from multiple servers."""
        return MCPResponse(
            jsonrpc="2.0",
            id="aggregated-1",
            result={
                "tools": [
                    # Filesystem tools (namespaced)
                    {"name": "filesystem__read_file", "description": "Read a file"},
                    {"name": "filesystem__write_file", "description": "Write a file"},
                    {
                        "name": "filesystem__list_directory",
                        "description": "List directory contents",
                    },
                    {"name": "filesystem__delete_file", "description": "Delete a file"},
                    # GitHub tools (namespaced)
                    {"name": "github__create_issue", "description": "Create an issue"},
                    {"name": "github__close_issue", "description": "Close an issue"},
                    {"name": "github__get_repo", "description": "Get repository info"},
                    {"name": "github__delete_repo", "description": "Delete repository"},
                    # API tools (namespaced)
                    {"name": "api__get_data", "description": "Get data from API"},
                    {"name": "api__post_data", "description": "Post data to API"},
                    {
                        "name": "api__delete_all",
                        "description": "Delete all data (dangerous)",
                    },
                ]
            },
        )

    @pytest.mark.asyncio
    async def test_aggregated_tools_list_control_flow(self):
        """Test that _process_aggregated_tools_list_response is called for server_name=None."""

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)

        # Mock the _process_aggregated_tools_list_response method to track if it's called
        with patch.object(
            plugin_manager,
            "_process_aggregated_tools_list_response",
            new_callable=AsyncMock,
        ) as mock_aggregated_process:

            # Configure the mock to return a ProcessingPipeline
            from gatekit.plugins.interfaces import (
                ProcessingPipeline,
            )

            mock_pipeline = ProcessingPipeline(
                original_content=None,
                stages=[],
                final_content=None,
                total_time_ms=0.0,
                pipeline_outcome=PipelineOutcome.ALLOWED,
                blocked_at_stage=None,
                completed_by=None,
                had_security_plugin=True,
                capture_content=True,
            )
            mock_aggregated_process.return_value = mock_pipeline

            # Create test request and response
            request = MCPRequest(
                jsonrpc="2.0", method="tools/list", id="test-1", params={}
            )
            response = self.create_aggregated_tools_response()

            # Load plugins
            await plugin_manager.load_plugins()

            # Process response with server_name=None (the critical aggregated case)
            pipeline = await plugin_manager.process_response(
                request, response, server_name=None
            )

            # Verify aggregated processing was called
            mock_aggregated_process.assert_called_once_with(request, response)

            # Verify result indicates success
            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Check the last stage's reason since pipeline doesn't have a reason
            if pipeline.stages:
                assert (
                    "Aggregated processing completed"
                    in pipeline.stages[-1].result.reason
                )

    @pytest.mark.asyncio
    async def test_aggregated_processing_uses_single_server_path(self):
        """Test that aggregated processing correctly uses single server processing for each server."""

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)

        # Load plugins
        await plugin_manager.load_plugins()

        # Mock the single server processing to track calls
        with patch.object(
            plugin_manager,
            "_process_single_server_response",
            new_callable=AsyncMock,
            wraps=plugin_manager._process_single_server_response,
        ) as mock_single_process:

            request = MCPRequest(
                jsonrpc="2.0", method="tools/list", id="regression-test", params={}
            )
            response = self.create_aggregated_tools_response()

            # Process with server_name=None
            pipeline = await plugin_manager.process_response(
                request, response, server_name=None
            )

            # Now aggregated processing SHOULD call single server processing for each server
            # The test response has tools from 3 servers (filesystem, github, api)
            assert mock_single_process.call_count == 3

            # Result should be MODIFIED since aggregated processing modifies the response
            assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED

    @pytest.mark.asyncio
    async def test_denamespacing_and_plugin_application(self):
        """Test that tools get properly denamespaced and filtered per server."""

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)
        await plugin_manager.load_plugins()

        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="denamespace-test", params={}
        )
        response = self.create_aggregated_tools_response()

        # Process the aggregated response
        pipeline = await plugin_manager.process_response(
            request, response, server_name=None
        )

        # Should be modified (plugins filter individual tools, changing the response)
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED

        # Check that the response contains filtered results
        if pipeline.final_content and hasattr(pipeline.final_content, "result"):
            filtered_response = pipeline.final_content
            tool_names = [tool["name"] for tool in filtered_response.result["tools"]]

            # Filesystem tools should be filtered by allowlist (only read_file, list_directory)
            filesystem_tools = [
                name for name in tool_names if name.startswith("filesystem__")
            ]
            expected_filesystem = {
                "filesystem__read_file",
                "filesystem__list_directory",
            }
            assert set(filesystem_tools) == expected_filesystem

            # GitHub tools should be filtered by allowlist (only create_issue, get_repo)
            github_tools = [name for name in tool_names if name.startswith("github__")]
            expected_github = {"github__create_issue", "github__get_repo"}
            assert set(github_tools) == expected_github

            # API tools should be filtered by allowlist (delete_all omitted)
            api_tools = [name for name in tool_names if name.startswith("api__")]
            expected_api = {
                "api__get_data",
                "api__post_data",
            }  # delete_all should be blocked
            assert set(api_tools) == expected_api

    @pytest.mark.asyncio
    async def test_aggregated_response_with_server_failure(self):
        """Test aggregated processing when one server fails but others succeed."""

        # Create response with tools from only some servers (simulating partial failure)
        partial_response = MCPResponse(
            jsonrpc="2.0",
            id="partial-1",
            result={
                "tools": [
                    # Only filesystem and API tools (GitHub server "failed")
                    {"name": "filesystem__read_file", "description": "Read a file"},
                    {"name": "filesystem__write_file", "description": "Write a file"},
                    {"name": "api__get_data", "description": "Get data from API"},
                    {
                        "name": "api__delete_all",
                        "description": "Delete all data (dangerous)",
                    },
                ]
            },
        )

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)
        await plugin_manager.load_plugins()

        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="partial-test", params={}
        )

        # Process partial response
        pipeline = await plugin_manager.process_response(
            request, partial_response, server_name=None
        )

        # Should be modified (tools are filtered despite missing server)
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED

        # Verify available tools are still properly filtered
        if pipeline.final_content and hasattr(pipeline.final_content, "result"):
            filtered_response = pipeline.final_content
            tool_names = [tool["name"] for tool in filtered_response.result["tools"]]

            # Should have filesystem and API tools, but no GitHub tools
            filesystem_tools = [
                name for name in tool_names if name.startswith("filesystem__")
            ]
            api_tools = [name for name in tool_names if name.startswith("api__")]
            github_tools = [name for name in tool_names if name.startswith("github__")]

            assert (
                len(filesystem_tools) > 0
            )  # Should have some filtered filesystem tools
            assert len(api_tools) > 0  # Should have some filtered API tools
            assert (
                len(github_tools) == 0
            )  # Should have no GitHub tools (server "failed")

    @pytest.mark.asyncio
    async def test_aggregated_response_malformed_tools(self):
        """Test handling of malformed tools in aggregated response."""

        malformed_response = MCPResponse(
            jsonrpc="2.0",
            id="malformed-1",
            result={
                "tools": [
                    # Valid tool
                    {"name": "filesystem__read_file", "description": "Read a file"},
                    # Malformed tools (missing name, invalid name, etc.)
                    {"description": "Tool without name"},
                    {"name": "", "description": "Tool with empty name"},
                    {
                        "name": "invalid_name_no_namespace",
                        "description": "Tool without namespace",
                    },
                    # Valid tool after malformed ones
                    {"name": "api__get_data", "description": "Get data from API"},
                ]
            },
        )

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)
        await plugin_manager.load_plugins()

        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="malformed-test", params={}
        )

        # Process malformed response - should handle gracefully
        pipeline = await plugin_manager.process_response(
            request, malformed_response, server_name=None
        )

        # Should be modified (malformed tools filtered out by middleware)
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED

    @pytest.mark.asyncio
    async def test_aggregated_response_empty_tools(self):
        """Test handling of empty tools list in aggregated response."""

        empty_response = MCPResponse(jsonrpc="2.0", id="empty-1", result={"tools": []})

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)
        await plugin_manager.load_plugins()

        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="empty-test", params={}
        )

        # Process empty response
        pipeline = await plugin_manager.process_response(
            request, empty_response, server_name=None
        )

        # Should be NO_SECURITY_EVALUATION because no security plugins ran for this scope
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        # Empty tools list means no servers to process, so no stages created
        assert len(pipeline.stages) == 0, "Empty tools list should not create stages"

    @pytest.mark.asyncio
    async def test_aggregated_response_missing_tools_field(self):
        """Test handling of response missing tools field entirely."""

        missing_tools_response = MCPResponse(
            jsonrpc="2.0",
            id="missing-1",
            result={"other_field": "value"},  # Missing 'tools' field
        )

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)
        await plugin_manager.load_plugins()

        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="missing-test", params={}
        )

        # Process response missing tools field
        pipeline = await plugin_manager.process_response(
            request, missing_tools_response, server_name=None
        )

        # Should be allowed with appropriate reason (None because no security plugins ran)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # No security plugins for server_name=None
        if pipeline.stages:
            assert (
                "No tools" in pipeline.stages[-1].result.reason
            )  # Accept either "No tools in response to filter" or "No tools filtered"

    @pytest.mark.asyncio
    async def test_mixed_security_policies_aggregated(self):
        """Test aggregated processing with different allowlists per server."""

        # Response with tools that will be filtered differently by each server's policy
        mixed_response = MCPResponse(
            jsonrpc="2.0",
            id="mixed-1",
            result={
                "tools": [
                    # Filesystem tools - allowlist policy (only read_file, list_directory allowed)
                    {
                        "name": "filesystem__read_file",
                        "description": "Read a file",
                    },  # ALLOWED
                    {
                        "name": "filesystem__write_file",
                        "description": "Write a file",
                    },  # BLOCKED
                    {
                        "name": "filesystem__list_directory",
                        "description": "List directory",
                    },  # ALLOWED
                    # GitHub tools - allowlist policy (only create_issue, get_repo allowed)
                    {
                        "name": "github__create_issue",
                        "description": "Create an issue",
                    },  # ALLOWED
                    {
                        "name": "github__delete_repo",
                        "description": "Delete repository",
                    },  # BLOCKED
                    {
                        "name": "github__get_repo",
                        "description": "Get repository info",
                    },  # ALLOWED
                    # API tools - allowlist omits delete_all
                    {
                        "name": "api__get_data",
                        "description": "Get data from API",
                    },  # ALLOWED
                    {
                        "name": "api__post_data",
                        "description": "Post data to API",
                    },  # ALLOWED
                    {
                        "name": "api__delete_all",
                        "description": "Delete all data",
                    },  # BLOCKED
                ]
            },
        )

        plugin_config = self.create_plugin_config()
        plugin_manager = PluginManager(plugin_config)
        await plugin_manager.load_plugins()

        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="mixed-policies-test", params={}
        )

        # Process mixed policy response
        pipeline = await plugin_manager.process_response(
            request, mixed_response, server_name=None
        )

        # Should be modified (tools are filtered by mixed policies)
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED

        # Verify that different policies were applied correctly
        if pipeline.final_content and hasattr(pipeline.final_content, "result"):
            filtered_response = pipeline.final_content
            tool_names = [tool["name"] for tool in filtered_response.result["tools"]]

            # Expected allowed tools based on each server's policy
            expected_allowed = {
                "filesystem__read_file",  # Filesystem allowlist
                "filesystem__list_directory",  # Filesystem allowlist
                "github__create_issue",  # GitHub allowlist
                "github__get_repo",  # GitHub allowlist
                "api__get_data",  # API allowlist
                "api__post_data",  # API allowlist
            }

            # Expected blocked tools
            expected_blocked = {
                "filesystem__write_file",  # Not in filesystem allowlist
                "github__delete_repo",  # Not in github allowlist
                "api__delete_all",  # Not in API allowlist
            }

            # Verify correct filtering
            assert set(tool_names) == expected_allowed
            for blocked_tool in expected_blocked:
                assert blocked_tool not in tool_names
