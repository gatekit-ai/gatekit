"""Tests for human-readable auditing formatters.

This test suite covers the LineAuditingPlugin and DebugAuditingPlugin formatters:
- Line format output for operational monitoring
- Debug format output with detailed key-value pairs
- Proper formatting of requests, responses, and notifications
- Tool call handling and parameter display
- Error handling and status reporting
"""

import tempfile

import pytest
from gatekit.plugins.auditing.human_readable import LineAuditingPlugin

# Import shared logging cleanup helpers (Windows compatibility)
from conftest import close_all_logging_handlers as _close_all_logging_handlers

from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.plugins.interfaces import (
    PluginResult,
    ProcessingPipeline,
    PipelineStage,
    StageOutcome,
    PipelineOutcome,
)


class TestLineAuditingFormatter:
    """Test LineAuditingPlugin formatting functionality using public pipeline logging API."""

    def _pipeline(
        self,
        content,
        allowed=True,
        reason="",
        plugin_name="policy",
        tool_name=None,
        blocked=False,
        duration_ms=None,
        metadata=None,
    ):
        pipeline = ProcessingPipeline(original_content=content)
        pr_meta = metadata.copy() if metadata else {}
        if plugin_name:
            pr_meta.setdefault("plugin", plugin_name)
        result = PluginResult(allowed=allowed, reason=reason, metadata=pr_meta)
        stage = PipelineStage(
            plugin_name=plugin_name,
            plugin_type="security",
            input_content=content,
            output_content=content,
            content_hash="hash",
            result=result,
            processing_time_ms=1.0,
            outcome=StageOutcome.BLOCKED if blocked else StageOutcome.ALLOWED,
            security_evaluated=True,
        )
        pipeline.add_stage(stage)
        pipeline.had_security_plugin = True
        pipeline.pipeline_outcome = (
            PipelineOutcome.BLOCKED if blocked else PipelineOutcome.ALLOWED
        )
        if duration_ms is not None:
            # mimic duration by attaching metadata to stage result
            result.metadata["duration_ms"] = duration_ms
            # Also set on pipeline total time
            pipeline.total_time_ms = duration_ms
        return pipeline

    @pytest.mark.asyncio
    async def test_basic_request_formatting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin = LineAuditingPlugin({"output_file": f"{temp_dir}/test.log"})
            request = MCPRequest(
                jsonrpc="2.0", id="123", method="tools/list", params={}
            )
            pipeline = self._pipeline(request, allowed=True)
            await plugin.log_request(request, pipeline, server_name="test_server")
            # Last emitted line is written via logger; fetch by re-formatting using internal formatter
            # Simpler: regenerate entry using extracted data (indirect). Here we rely on plugin logger flush: ensure _ensure_logging_setup.
            # Instead of intercepting logger, validate via direct formatter call on extracted data for determinism.
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            formatted = plugin._format_request_entry(data)
            assert "REQUEST: tools/list" in formatted
            assert "ALLOWED" in formatted
            assert "test_server" in formatted
            assert "UTC" in formatted
            # Cleanup before temp directory is removed (required for Windows)
            plugin.cleanup()
            _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_tool_call_formatting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin = LineAuditingPlugin({"output_file": f"{temp_dir}/test.log"})
            request = MCPRequest(
                jsonrpc="2.0",
                id="123",
                method="tools/call",
                params={"name": "file_read", "arguments": {"path": "/test"}},
            )
            pipeline = self._pipeline(request, allowed=True)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            formatted = plugin._format_request_entry(data)
            # New format: timestamp - REQUEST: method - tool - server - OUTCOME
            assert "REQUEST: tools/call - file_read - test_server" in formatted
            assert "- ALLOWED" in formatted or "- NO_SECURITY" in formatted
            # Cleanup before temp directory is removed (required for Windows)
            plugin.cleanup()
            _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_security_block_formatting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin = LineAuditingPlugin({"output_file": f"{temp_dir}/test.log"})
            request = MCPRequest(
                jsonrpc="2.0",
                id="123",
                method="tools/call",
                params={"name": "dangerous_tool"},
            )
            pipeline = self._pipeline(
                request,
                allowed=False,
                reason="Tool blocked by security policy",
                plugin_name="security_plugin",
                blocked=True,
            )
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            formatted = plugin._format_request_entry(data)
            # New format: timestamp - REQUEST: method - tool - server - BLOCKED [plugin]
            assert (
                "REQUEST: tools/call - dangerous_tool - test_server - BLOCKED"
                in formatted
            )
            assert "[security_plugin]" in formatted
            # Cleanup before temp directory is removed (required for Windows)
            plugin.cleanup()
            _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_response_formatting_with_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin = LineAuditingPlugin({"output_file": f"{temp_dir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", id="123", method="tools/call")
            response = MCPResponse(jsonrpc="2.0", id="123", result={"status": "ok"})
            pipeline = self._pipeline(
                request, allowed=True, metadata={"duration_ms": 1500}
            )
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            formatted = plugin._format_response_entry(data)
            # New format: timestamp - RESPONSE - server - success (duration)
            assert "RESPONSE - test_server - success" in formatted
            assert "(1.500s)" in formatted
            # Cleanup before temp directory is removed (required for Windows)
            plugin.cleanup()
            _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_notification_formatting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin = LineAuditingPlugin({"output_file": f"{temp_dir}/test.log"})
            notification = MCPNotification(
                jsonrpc="2.0", method="notifications/message", params={"text": "Hello"}
            )
            pipeline = self._pipeline(
                notification,
                allowed=True,
                reason="Message approved",
                plugin_name="message_filter",
            )
            data = plugin._extract_common_notification_data(
                notification, pipeline, "test_server"
            )
            formatted = plugin._format_notification_entry(data)
            # New format: timestamp - NOTIFICATION: method - server - OUTCOME
            assert "NOTIFICATION: notifications/message - test_server" in formatted
            assert "- ALLOWED" in formatted or "- NO_SECURITY" in formatted
            # Cleanup before temp directory is removed (required for Windows)
            plugin.cleanup()
            _close_all_logging_handlers()


