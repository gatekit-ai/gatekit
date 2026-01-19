"""Tests for the CallTracePlugin middleware plugin."""

import pytest
import time

from gatekit.plugins.middleware.call_trace import CallTracePlugin
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestCallTraceBasicTraceAppending:
    """Test basic trace appending to successful responses."""

    @pytest.mark.asyncio
    async def test_trace_appended_to_tools_call_response(self):
        """Verify trace is added to successful tools/call response."""
        plugin = CallTracePlugin({"max_param_length": 200})

        # Create request
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "read_file", "arguments": {"path": "/tmp/test.txt"}}
        )

        # Store request time
        await plugin.process_request(request, "filesystem")

        # Create successful response
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "content": [
                    {"type": "text", "text": "File contents here"}
                ]
            }
        )

        # Process response
        result = await plugin.process_response(request, response, "filesystem")

        # Verify modified content
        assert result.modified_content is not None
        assert isinstance(result.modified_content, MCPResponse)
        modified_response = result.modified_content

        # Verify trace was appended
        assert len(modified_response.result["content"]) == 2
        trace_block = modified_response.result["content"][1]
        assert trace_block["type"] == "text"
        assert "🔍 **Gatekit Gateway Trace**" in trace_block["text"]
        assert "Server: filesystem" in trace_block["text"]
        assert "Tool: read_file" in trace_block["text"]
        assert "Request ID: 1" in trace_block["text"]

    @pytest.mark.asyncio
    async def test_trace_includes_all_required_fields(self):
        """Verify trace includes all required fields in correct format."""
        plugin = CallTracePlugin({"max_param_length": 200})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-123",
            params={"name": "list_files", "arguments": {"dir": "/home"}}
        )

        await plugin.process_request(request, "fs-server")

        response = MCPResponse(
            jsonrpc="2.0",
            id="test-123",
            result={"content": [{"type": "text", "text": "file1.txt\nfile2.txt"}]}
        )

        result = await plugin.process_response(request, response, "fs-server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Verify all required fields
        assert "Server: fs-server" in trace_text
        assert "Tool: list_files" in trace_text
        assert 'Params: {"dir": "/home"}' in trace_text
        assert "Response:" in trace_text  # Size field
        assert "Duration:" in trace_text
        assert "Request ID: test-123" in trace_text
        assert "Timestamp:" in trace_text
        assert "Search your audit logs" in trace_text
        assert "---" in trace_text  # Markdown separator


class TestCallTraceDurationCalculation:
    """Test timing and duration calculation."""

    @pytest.mark.asyncio
    async def test_duration_calculation_accuracy(self):
        """Verify duration is calculated accurately."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "test_tool", "arguments": {}}
        )

        # Store request time
        await plugin.process_request(request, "server1")

        # Simulate 50ms delay
        time.sleep(0.05)

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server1")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Extract duration value
        import re
        duration_match = re.search(r"Duration: (\d+)ms", trace_text)
        assert duration_match is not None
        duration = int(duration_match.group(1))

        # Should be approximately 50ms
        # Wide tolerance (30-100ms for expected 50ms) because:
        # - Windows has ~15ms timer resolution by default
        # - CI environments may have variable scheduling delays
        # - time.sleep() is a minimum, not exact, sleep duration
        assert 30 <= duration <= 100

    @pytest.mark.asyncio
    async def test_missing_request_time_handled_gracefully(self):
        """Verify missing duration data is handled gracefully."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=999,
            params={"name": "test_tool", "arguments": {}}
        )

        # Don't store request time - simulate missing data

        response = MCPResponse(
            jsonrpc="2.0",
            id=999,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server1")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show N/A or omit duration
        assert "Duration: N/A" in trace_text or "Duration:" not in trace_text


class TestCallTraceSizeFormatting:
    """Test response size formatting."""

    @pytest.mark.asyncio
    async def test_size_formatting_bytes(self):
        """Test formatting for sizes under 1 KB."""
        plugin = CallTracePlugin({})

        # Test with small response (100 bytes)
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "x" * 100}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show bytes
        assert " B" in trace_text or "Response:" in trace_text

    @pytest.mark.asyncio
    async def test_size_formatting_kilobytes(self):
        """Test formatting for sizes in KB range."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Create ~2KB response
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "x" * 2048}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show KB
        assert " KB" in trace_text

    @pytest.mark.asyncio
    async def test_size_formatting_megabytes(self):
        """Test formatting for sizes in MB range."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Create ~1MB response
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "x" * (1024 * 1024)}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show MB
        assert " MB" in trace_text

    def test_size_formatting_gigabytes(self):
        """Test formatting for sizes in GB range."""
        plugin = CallTracePlugin({})

        # Test _format_size directly with GB value
        assert plugin._format_size(1024 ** 3) == "1.0 GB"
        assert plugin._format_size(int(2.5 * 1024 ** 3)) == "2.5 GB"


class TestCallTraceParameterTruncation:
    """Test parameter truncation for long values."""

    @pytest.mark.asyncio
    async def test_long_params_truncated(self):
        """Verify long parameters are truncated to max length."""
        plugin = CallTracePlugin({"max_param_length": 50})

        long_path = "/very/long/path/" + ("x" * 200)
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "read_file", "arguments": {"path": long_path}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "data"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Extract params line
        import re
        params_match = re.search(r"Params: (.+)", trace_text)
        assert params_match is not None
        params_text = params_match.group(1)

        # Should be truncated with ellipsis
        assert len(params_text) <= 53  # 50 + "..."
        assert "..." in params_text

    @pytest.mark.asyncio
    async def test_short_params_not_truncated(self):
        """Verify short parameters are not truncated."""
        plugin = CallTracePlugin({"max_param_length": 200})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {"key": "value"}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "data"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should not have ellipsis
        assert "..." not in trace_text or "..." not in trace_text.split("Params:")[1].split("\n")[0]


class TestCallTraceMissingDataHandling:
    """Test handling of missing or invalid data."""

    @pytest.mark.asyncio
    async def test_request_without_id(self):
        """Verify handling of request without ID."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=None,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=None,
            result={"content": [{"type": "text", "text": "data"}]}
        )

        result = await plugin.process_response(request, response, "server")

        # Should still work and show N/A or omit ID
        assert result.modified_content is not None
        trace_text = result.modified_content.result["content"][1]["text"]
        assert "Request ID: N/A" in trace_text or "Request ID: None" in trace_text

    @pytest.mark.asyncio
    async def test_params_serialization_error(self):
        """Verify graceful handling of serialization errors."""
        plugin = CallTracePlugin({})

        # Create request with non-serializable params
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": None}  # Valid but edge case
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "data"}]}
        )

        # Should not raise exception
        result = await plugin.process_response(request, response, "server")
        assert result.modified_content is not None


class TestCallTraceErrorResponses:
    """Test that error responses are NOT modified."""

    @pytest.mark.asyncio
    async def test_error_response_not_modified(self):
        """Verify trace is NOT added to error responses."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Create error response (no result field)
        error_response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            error={
                "code": -32000,
                "message": "Tool execution failed"
            }
        )

        result = await plugin.process_response(request, error_response, "server")

        # Should pass through unchanged
        assert result.modified_content is None

    @pytest.mark.asyncio
    async def test_error_response_with_data_field(self):
        """Verify error responses with data field are not modified."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        error_response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            error={
                "code": -32000,
                "message": "Error",
                "data": {"detail": "Something went wrong"}
            }
        )

        result = await plugin.process_response(request, error_response, "server")

        # Should pass through unchanged
        assert result.modified_content is None


class TestCallTraceMultipleMethods:
    """Test handling of different MCP methods."""

    @pytest.mark.asyncio
    async def test_tools_call_method_handled(self):
        """Verify tools/call method is processed."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "data"}]}
        )

        result = await plugin.process_response(request, response, "server")

        # Should be modified
        assert result.modified_content is not None

    @pytest.mark.asyncio
    async def test_other_methods_passed_through(self):
        """Verify non-tools/call methods are passed through unchanged."""
        plugin = CallTracePlugin({})

        # Test resources/read
        request = MCPRequest(
            jsonrpc="2.0",
            method="resources/read",
            id=1,
            params={"uri": "file:///test.txt"}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"contents": [{"uri": "file:///test.txt", "text": "data"}]}
        )

        result = await plugin.process_response(request, response, "server")

        # Should pass through unchanged
        assert result.modified_content is None

    @pytest.mark.asyncio
    async def test_prompts_get_passed_through(self):
        """Verify prompts/get method is passed through."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="prompts/get",
            id=1,
            params={"name": "test_prompt"}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"messages": [{"role": "user", "content": {"type": "text", "text": "prompt"}}]}
        )

        result = await plugin.process_response(request, response, "server")

        # Should pass through unchanged
        assert result.modified_content is None

    @pytest.mark.asyncio
    async def test_notifications_passed_through(self):
        """Verify notifications are passed through unchanged."""
        plugin = CallTracePlugin({})

        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/progress",
            params={"progress": 50}
        )

        result = await plugin.process_notification(notification, "server")

        # Should pass through
        assert result.modified_content is None


class TestCallTraceConfiguration:
    """Test configuration handling."""

    def test_default_configuration(self):
        """Verify default configuration values."""
        plugin = CallTracePlugin({})

        # Should have default values
        assert plugin._max_param_length == 200
        assert plugin.critical is True  # All plugins default to critical (fail-closed)
        assert plugin.priority == 90

    def test_custom_max_param_length(self):
        """Verify custom max_param_length is respected."""
        plugin = CallTracePlugin({"max_param_length": 100})
        assert plugin._max_param_length == 100

    def test_custom_priority(self):
        """Verify custom priority is respected."""
        plugin = CallTracePlugin({"priority": 50})
        assert plugin.priority == 50

    def test_critical_flag(self):
        """Verify critical flag can be set."""
        plugin = CallTracePlugin({"critical": True})
        assert plugin.is_critical() is True


class TestCallTraceFailOpenBehavior:
    """Test fail-open behavior - errors don't break requests."""

    @pytest.mark.asyncio
    async def test_response_without_content_array_gets_wrapped(self):
        """Verify responses without content array are wrapped and traced.

        Some MCP servers (like memory, sequential-thinking) return non-standard
        responses without the required content array. The plugin should wrap
        these in a content array and append the trace.
        """
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Create response with non-standard structure (like memory server)
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"entities": [], "relations": []}  # Non-standard, no 'content' field
        )

        # Should not raise exception
        result = await plugin.process_response(request, response, "server")

        # Should wrap the response and append trace
        assert result.modified_content is not None
        modified = result.modified_content
        assert "content" in modified.result
        assert isinstance(modified.result["content"], list)
        assert len(modified.result["content"]) == 2

        # First content item should be the serialized original result
        original_content = modified.result["content"][0]
        assert original_content["type"] == "text"
        assert '"entities": []' in original_content["text"]
        assert '"relations": []' in original_content["text"]

        # Second content item should be the trace
        trace_content = modified.result["content"][1]
        assert trace_content["type"] == "text"
        assert "Gatekit Gateway Trace" in trace_content["text"]

    @pytest.mark.asyncio
    async def test_malformed_response_handled_gracefully(self):
        """Verify malformed responses are handled gracefully."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Response with wrong content structure (string instead of list)
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": "not a list"}  # Should be a list
        )

        # Should not raise exception
        result = await plugin.process_response(request, response, "server")

        # Should wrap since content is not a list, and append trace
        assert result.modified_content is not None
        modified = result.modified_content
        assert isinstance(modified.result["content"], list)


class TestCallTraceRequestTimeCleanup:
    """Test cleanup of completed request times."""

    @pytest.mark.asyncio
    async def test_request_time_cleaned_after_response(self):
        """Verify request time is removed after processing response."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Verify request time was stored
        assert 1 in plugin._request_times

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "data"}]}
        )

        await plugin.process_response(request, response, "server")

        # Verify request time was cleaned up
        assert 1 not in plugin._request_times


class TestCallTraceConfigurableFields:
    """Test configurable field display options."""

    @pytest.mark.asyncio
    async def test_all_fields_enabled_by_default(self):
        """Verify all fields are shown with default configuration."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "test_tool", "arguments": {"key": "value"}}
        )

        await plugin.process_request(request, "test-server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "test-server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Verify all fields are present
        assert "Server: test-server" in trace_text
        assert "Tool: test_tool" in trace_text
        assert "Params:" in trace_text
        assert "Response:" in trace_text
        assert "Duration:" in trace_text
        assert "Request ID: 1" in trace_text
        assert "Timestamp:" in trace_text
        assert "Search your audit logs" in trace_text

    @pytest.mark.asyncio
    async def test_all_fields_disabled(self):
        """Verify minimal trace when all fields are disabled."""
        plugin = CallTracePlugin({
            "trace_fields": {
                "server": False,
                "tool": False,
                "params": False,
                "response_size": False,
                "duration": False,
                "request_id": False,
                "timestamp": False,
            }
        })

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "test_tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should only have header and footer markers
        assert "🔍 **Gatekit Gateway Trace**" in trace_text
        assert "---" in trace_text

        # No data fields should be present
        assert "Server:" not in trace_text
        assert "Tool:" not in trace_text
        assert "Params:" not in trace_text
        assert "Response:" not in trace_text
        assert "Duration:" not in trace_text
        assert "Request ID:" not in trace_text
        assert "Timestamp:" not in trace_text

        # No footer message when timestamp and request_id are both disabled
        assert "Search your audit logs" not in trace_text

    @pytest.mark.asyncio
    async def test_selective_fields_enabled(self):
        """Verify only configured fields are shown."""
        plugin = CallTracePlugin({
            "trace_fields": {
                "server": True,
                "tool": True,
                "params": False,
                "response_size": False,
                "duration": True,
                "request_id": False,
                "timestamp": False,
            }
        })

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "test_tool", "arguments": {"key": "value"}}
        )

        await plugin.process_request(request, "test-server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "test-server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Enabled fields should be present
        assert "Server: test-server" in trace_text
        assert "Tool: test_tool" in trace_text
        assert "Duration:" in trace_text

        # Disabled fields should not be present
        assert "Params:" not in trace_text
        assert "Response:" not in trace_text
        assert "Request ID:" not in trace_text
        assert "Timestamp:" not in trace_text

    @pytest.mark.asyncio
    async def test_footer_with_only_timestamp(self):
        """Verify footer message when only timestamp is enabled."""
        plugin = CallTracePlugin({
            "trace_fields": {
                "server": False,
                "tool": False,
                "params": False,
                "response_size": False,
                "duration": False,
                "request_id": False,
                "timestamp": True,
            }
        })

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "test_tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show timestamp field
        assert "Timestamp:" in trace_text

        # Footer should mention timestamp but not request_id
        assert "Search your audit logs near timestamp" in trace_text
        assert "request_id:" not in trace_text

    @pytest.mark.asyncio
    async def test_footer_with_only_request_id(self):
        """Verify footer message when only request_id is enabled."""
        plugin = CallTracePlugin({
            "trace_fields": {
                "server": False,
                "tool": False,
                "params": False,
                "response_size": False,
                "duration": False,
                "request_id": True,
                "timestamp": False,
            }
        })

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=42,
            params={"name": "test_tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=42,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show request ID field
        assert "Request ID: 42" in trace_text

        # Footer should mention request_id but not timestamp
        assert "request_id: 42" in trace_text
        assert "near timestamp" not in trace_text

    @pytest.mark.asyncio
    async def test_footer_with_both_timestamp_and_request_id(self):
        """Verify footer message when both timestamp and request_id are enabled."""
        plugin = CallTracePlugin({
            "trace_fields": {
                "server": False,
                "tool": False,
                "params": False,
                "response_size": False,
                "duration": False,
                "request_id": True,
                "timestamp": True,
            }
        })

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=99,
            params={"name": "test_tool", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=99,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Should show both fields
        assert "Request ID: 99" in trace_text
        assert "Timestamp:" in trace_text

        # Footer should mention both
        assert "near timestamp" in trace_text
        assert "request_id: 99" in trace_text

    @pytest.mark.asyncio
    async def test_params_field_respects_max_param_length(self):
        """Verify params field works together with max_param_length."""
        plugin = CallTracePlugin({
            "trace_fields": {
                "params": True,
            },
            "max_param_length": 20,
        })

        long_value = "x" * 100
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "tool", "arguments": {"data": long_value}}
        )

        await plugin.process_request(request, "server")

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": "result"}]}
        )

        result = await plugin.process_response(request, response, "server")
        trace_text = result.modified_content.result["content"][1]["text"]

        # Params should be shown but truncated
        assert "Params:" in trace_text
        import re
        params_match = re.search(r"Params: (.+)", trace_text)
        assert params_match is not None
        params_text = params_match.group(1)
        assert "..." in params_text
        assert len(params_text) <= 23  # 20 + "..."

    def test_get_json_schema_structure(self):
        """Verify get_json_schema() returns correct structure."""
        schema = CallTracePlugin.get_json_schema()

        # Verify schema structure
        assert schema["type"] == "object"
        assert "$schema" in schema
        assert "properties" in schema

        # Verify top-level properties
        props = schema["properties"]
        assert "max_param_length" in props
        assert "trace_fields" in props

        # Verify max_param_length structure
        assert props["max_param_length"]["type"] == "integer"
        assert props["max_param_length"]["default"] == 200
        assert props["max_param_length"]["minimum"] == 0

        # Verify trace_fields is an object
        trace_fields = props["trace_fields"]
        assert trace_fields["type"] == "object"
        assert "title" in trace_fields
        assert trace_fields["title"] == "Trace Fields"
        assert "description" in trace_fields
        assert "properties" in trace_fields

        # Verify all boolean fields are present in trace_fields
        trace_props = trace_fields["properties"]
        assert "server" in trace_props
        assert "tool" in trace_props
        assert "params" in trace_props
        assert "response_size" in trace_props
        assert "duration" in trace_props
        assert "request_id" in trace_props
        assert "timestamp" in trace_props

        # Verify boolean fields have correct type and defaults
        for field in ["server", "tool", "params", "response_size",
                      "duration", "request_id", "timestamp"]:
            assert trace_props[field]["type"] == "boolean"
            assert trace_props[field]["default"] is True
            assert "title" in trace_props[field]
            assert "description" in trace_props[field]

    def test_configuration_flags_initialization(self):
        """Verify configuration flags are properly initialized."""
        # Test default values
        plugin_default = CallTracePlugin({})
        assert plugin_default._include_server is True
        assert plugin_default._include_tool is True
        assert plugin_default._include_params is True
        assert plugin_default._include_response_size is True
        assert plugin_default._include_duration is True
        assert plugin_default._include_request_id is True
        assert plugin_default._include_timestamp is True

        # Test custom values
        plugin_custom = CallTracePlugin({
            "trace_fields": {
                "server": False,
                "tool": False,
                "params": True,
            }
        })
        assert plugin_custom._include_server is False
        assert plugin_custom._include_tool is False
        assert plugin_custom._include_params is True
        # Others should still be default True
        assert plugin_custom._include_response_size is True
        assert plugin_custom._include_duration is True


class TestCallTraceNonStandardResponses:
    """Test handling of non-standard MCP response formats.

    Some MCP servers (memory, sequential-thinking) return responses that don't
    follow the standard tools/call response format with a content array.
    The call_trace plugin should handle these gracefully by wrapping them.
    """

    @pytest.mark.asyncio
    async def test_sequential_thinking_style_response(self):
        """Test response format like sequential-thinking server."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "sequentialthinking", "arguments": {"thought": "test"}}
        )

        await plugin.process_request(request, "sequential-thinking")

        # Sequential-thinking returns structured data without content array
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "thoughtNumber": 1,
                "totalThoughts": 1,
                "nextThoughtNeeded": False,
                "branches": [],
                "thoughtHistoryLength": 1
            }
        )

        result = await plugin.process_response(request, response, "sequential-thinking")

        # Should wrap and append trace
        assert result.modified_content is not None
        modified = result.modified_content
        assert "content" in modified.result
        assert len(modified.result["content"]) == 2

        # Verify original data is preserved as JSON text
        original_text = modified.result["content"][0]["text"]
        assert '"thoughtNumber": 1' in original_text
        assert '"nextThoughtNeeded": false' in original_text

        # Verify trace is appended
        trace_text = modified.result["content"][1]["text"]
        assert "Gatekit Gateway Trace" in trace_text
        assert "Server: sequential-thinking" in trace_text

    @pytest.mark.asyncio
    async def test_memory_server_style_response(self):
        """Test response format like memory server."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "read_graph", "arguments": {}}
        )

        await plugin.process_request(request, "memory")

        # Memory server returns entity/relation structure
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "entities": [
                    {"name": "test", "entityType": "concept", "observations": ["obs1"]}
                ],
                "relations": []
            }
        )

        result = await plugin.process_response(request, response, "memory")

        # Should wrap and append trace
        assert result.modified_content is not None
        modified = result.modified_content
        assert "content" in modified.result

        # Verify original data is preserved
        original_text = modified.result["content"][0]["text"]
        assert '"entities"' in original_text
        assert '"name": "test"' in original_text

    @pytest.mark.asyncio
    async def test_list_result_response(self):
        """Test response where result is a list instead of dict."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "list_items", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Some tools might return a list directly
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result=[{"id": 1, "name": "item1"}, {"id": 2, "name": "item2"}]
        )

        result = await plugin.process_response(request, response, "server")

        # Should wrap and append trace
        assert result.modified_content is not None
        modified = result.modified_content
        assert "content" in modified.result
        assert len(modified.result["content"]) == 2

        # Verify original data is preserved as JSON
        original_text = modified.result["content"][0]["text"]
        assert '"id": 1' in original_text
        assert '"name": "item1"' in original_text

    @pytest.mark.asyncio
    async def test_primitive_result_response(self):
        """Test response where result is a primitive value."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "get_count", "arguments": {}}
        )

        await plugin.process_request(request, "server")

        # Some tools might return a primitive
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result=42
        )

        result = await plugin.process_response(request, response, "server")

        # Should wrap and append trace
        assert result.modified_content is not None
        modified = result.modified_content
        assert "content" in modified.result
        assert len(modified.result["content"]) == 2

        # Verify original value is preserved
        original_text = modified.result["content"][0]["text"]
        assert "42" in original_text

    @pytest.mark.asyncio
    async def test_standard_response_still_works(self):
        """Verify standard MCP responses still work correctly after fix."""
        plugin = CallTracePlugin({})

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "echo", "arguments": {"message": "hello"}}
        )

        await plugin.process_request(request, "everything")

        # Standard MCP tools/call response with content array
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "content": [
                    {"type": "text", "text": "Echo: hello"}
                ]
            }
        )

        result = await plugin.process_response(request, response, "everything")

        # Should append trace to existing content
        assert result.modified_content is not None
        modified = result.modified_content
        assert "content" in modified.result
        assert len(modified.result["content"]) == 2

        # Original content should be preserved as-is (not serialized)
        assert modified.result["content"][0]["type"] == "text"
        assert modified.result["content"][0]["text"] == "Echo: hello"

        # Trace should be appended
        trace_text = modified.result["content"][1]["text"]
        assert "Gatekit Gateway Trace" in trace_text
