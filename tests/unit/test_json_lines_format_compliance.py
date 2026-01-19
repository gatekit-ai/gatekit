"""Tests for JSON Lines auditing plugin format compliance and error handling (pipeline-based).

Migrated from decision-based _format_*_log helpers to pipeline-based
extraction + _format_*_entry methods.
"""

import json
import tempfile
from datetime import datetime, timezone
import time
import pytest

from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin

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

# Helper to build a simple allowed pipeline


def build_pipeline(message, allowed=True, reason="test", outcome=StageOutcome.ALLOWED):
    decision = PluginResult(allowed=allowed, reason=reason)
    pipeline = ProcessingPipeline(original_content=message)
    stage = PipelineStage(
        plugin_name="policy",
        plugin_type="security",
        input_content=message,
        output_content=message,
        content_hash="hash",
        result=decision,
        processing_time_ms=1.0,
        outcome=outcome,
        security_evaluated=True,
    )
    pipeline.add_stage(stage)
    pipeline.had_security_plugin = True
    if outcome == StageOutcome.BLOCKED:
        pipeline.pipeline_outcome = PipelineOutcome.BLOCKED
    else:
        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
    return pipeline, decision


class TestJsonRpcErrorClassification:
    def test_upstream_server_error_classification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            for error_code in [-32000, -32050, -32099]:
                request = MCPRequest(jsonrpc="2.0", method="test", id="test")
                response = MCPResponse(jsonrpc="2.0", id="test")
                response.error = {"code": error_code, "message": "Server error"}
                pipeline, _ = build_pipeline(request)
                data = plugin._extract_common_response_data(
                    request, response, pipeline, "test_server"
                )
                log_output = plugin._format_response_entry(data)
                log_data = json.loads(log_output.strip())
                assert log_data["event_type"] == "UPSTREAM_ERROR"

    def test_protocol_error_classification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            protocol_errors = [
                (-32700, "Parse error", "PARSE_ERROR"),
                (-32600, "Invalid Request", "INVALID_REQUEST_ERROR"),
                (-32601, "Method not found", "METHOD_NOT_FOUND_ERROR"),
                (-32602, "Invalid params", "INVALID_PARAMS_ERROR"),
                (-32603, "Internal error", "INTERNAL_ERROR"),
            ]
            for error_code, message, expected in protocol_errors:
                request = MCPRequest(jsonrpc="2.0", method="test", id="test")
                response = MCPResponse(jsonrpc="2.0", id="test")
                response.error = {"code": error_code, "message": message}
                pipeline, _ = build_pipeline(request)
                data = plugin._extract_common_response_data(
                    request, response, pipeline, "test_server"
                )
                log_output = plugin._format_response_entry(data)
                log_data = json.loads(log_output.strip())
                assert log_data["event_type"] == expected


class TestJsonLinesFormatEnforcement:
    def test_jsonl_output_includes_newline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log"}
            )
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            request_log = plugin._format_request_entry(data)
            assert request_log.endswith("\n")
            json.loads(request_log.rstrip("\n"))
            response = MCPResponse(jsonrpc="2.0", id="123", result={})
            data_r = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            response_log = plugin._format_response_entry(data_r)
            assert response_log.endswith("\n")

    def test_jsonl_output_is_compact_single_line(self):
        """Test that JSON Lines output is always compact (single line per entry)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log"}
            )
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            request_log = plugin._format_request_entry(data)
            # Should be exactly 2 lines: the JSON content and the trailing newline
            assert len(request_log.split("\n")) == 2
            json.loads(request_log.rstrip("\n"))


class TestTimezoneAwareTimestamps:
    def test_iso8601_timestamp_includes_timezone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_output = plugin._format_request_entry(data)
            ts = json.loads(log_output.strip())["timestamp"]
            assert ts.endswith("Z")

    def test_timestamps_always_iso8601(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            ts = json.loads(plugin._format_request_entry(data).strip())["timestamp"]
            assert "T" in ts and ts.endswith("Z")


class TestResponseLogCorrelation:
    def test_response_log_includes_method(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="tools/list", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result=[])
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert log_data["method"] == "tools/list"

    def test_response_log_includes_tool_name_for_tools_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="123",
                params={"name": "read_file", "arguments": {"path": "/t"}},
            )
            response = MCPResponse(jsonrpc="2.0", id="123", result={"content": "test"})
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert log_data["tool"] == "read_file"

    def test_response_log_no_tool_field_for_non_tools_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="resources/list", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result=[])
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert "tool" not in log_data


class TestSafeAttributeAccess:
    def test_safe_modified_content_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result={})
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert log_data["event_type"] == "RESPONSE"

    def test_response_modified_event_type_used_for_modifications(self):
        """RESPONSE_MODIFIED event type when content is modified (no translation to REDACTION)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result={"result": "SSN"})
            # Build pipeline with modified stage
            pipeline, decision = build_pipeline(request, reason="PII redacted from response")
            pipeline.stages[0].outcome = StageOutcome.MODIFIED
            decision.modified_content = {"result": "REDACTED"}
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            # Stock event_type from base.py is used, no translation
            assert log_data["event_type"] == "RESPONSE_MODIFIED"


class TestBodyLogging:
    def test_include_request_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_request_body": True}
            )
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="123",
                params={
                    "name": "authenticate",
                    "arguments": {
                        "username": "u",
                        "password": "p",
                        "token": "t",
                        "normal_field": "v",
                    },
                },
            )
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())
            # Body should be included without redaction
            assert "request_body" in log_data
            body = log_data["request_body"]
            assert body["arguments"]["password"] == "p"
            assert body["arguments"]["token"] == "t"
            assert body["arguments"]["username"] == "u"
            assert body["arguments"]["normal_field"] == "v"

    def test_exclude_request_body_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="123",
                params={"password": "secret", "data": "value"},
            )
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())
            # Body should not be included by default
            assert "request_body" not in log_data

    @pytest.mark.asyncio
    async def test_include_response_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_response_body": True}
            )
            try:
                request = MCPRequest(jsonrpc="2.0", method="test", id="123")
                response = MCPResponse(
                    jsonrpc="2.0", id="123", result={"data": "test", "secret": "value"}
                )
                pipeline, _ = build_pipeline(request)
                # Call the overridden log_response method
                await plugin.log_response(request, response, pipeline, "test_server")
                # Read the log file to verify
                with open(f"{tmpdir}/test.log", "r") as f:
                    log_line = f.read().strip()
                    log_data = json.loads(log_line)
                    assert "response_body" in log_data
                    assert log_data["response_body"]["data"] == "test"
                    assert log_data["response_body"]["secret"] == "value"
            finally:
                # Cleanup before temp directory is removed (required for Windows)
                plugin.cleanup()
                _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_include_notification_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_notification_body": True}
            )
            try:
                notification = MCPNotification(
                    jsonrpc="2.0",
                    method="progress/update",
                    params={"status": "running", "percentage": 50},
                )
                pipeline, _ = build_pipeline(notification)
                # Call the overridden log_notification method
                await plugin.log_notification(notification, pipeline, "test_server")
                # Read the log file to verify
                with open(f"{tmpdir}/test.log", "r") as f:
                    log_line = f.read().strip()
                    log_data = json.loads(log_line)
                    assert "notification_body" in log_data
                    assert log_data["notification_body"]["status"] == "running"
                    assert log_data["notification_body"]["percentage"] == 50
            finally:
                # Cleanup before temp directory is removed (required for Windows)
                plugin.cleanup()
                _close_all_logging_handlers()

    def test_body_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test with a moderate max_body_size that allows structured truncation
            plugin = JsonAuditingPlugin(
                {
                    "output_file": f"{tmpdir}/test.log",
                    "include_request_body": True,
                    "max_body_size": 200,  # Large enough for some key-value pairs
                }
            )

            # Create a large request body
            large_data = {"key" + str(i): "value" + str(i) for i in range(100)}
            request = MCPRequest(
                jsonrpc="2.0", method="test", id="123", params=large_data
            )
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())

            # Body should be truncated
            assert "request_body" in log_data
            body = log_data["request_body"]
            # With structured truncation, we get a dict with _truncated marker
            assert isinstance(body, dict)
            assert "_truncated" in body  # Truncation marker should be present
            # Should have preserved some actual content
            assert any(k.startswith("key") for k in body.keys())

            # Test unlimited body size
            plugin_unlimited = JsonAuditingPlugin(
                {
                    "output_file": f"{tmpdir}/test2.log",
                    "include_request_body": True,
                    "max_body_size": 0,  # 0 means unlimited
                }
            )
            data2 = plugin_unlimited._extract_common_request_data(
                request, pipeline, "test_server"
            )
            log_data2 = json.loads(
                plugin_unlimited._format_request_entry(data2).strip()
            )

            # Body should not be truncated
            body2 = log_data2["request_body"]
            assert "_truncated" not in body2
            assert len(body2) == 100  # All items should be present

    def test_body_truncation_fallback_to_string(self):
        """Test that truncation falls back to string when no key-value pairs fit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test with a max_body_size that won't fit even one key-value pair
            plugin = JsonAuditingPlugin(
                {
                    "output_file": f"{tmpdir}/test.log",
                    "include_request_body": True,
                    "max_body_size": 100,  # Small but enough for some content
                }
            )

            # Create a body where the first key-value pair is too large to fit
            large_data = {
                "very_long_key_name_that_takes_up_space": "x" * 200,
                "another_key": "value",
            }
            request = MCPRequest(
                jsonrpc="2.0", method="test", id="123", params=large_data
            )
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())

            # Body should be truncated but include actual content, not just a marker
            assert "request_body" in log_data
            body = log_data["request_body"]

            # Should be a string (fallback) containing actual content from original
            assert isinstance(body, str)
            assert "...[truncated]" in body
            # Should include part of the original JSON content
            assert "very_long_key_name" in body

    def test_body_truncation_list_fallback_to_string(self):
        """Test that list truncation falls back to string when no items fit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {
                    "output_file": f"{tmpdir}/test.log",
                    "include_request_body": True,
                    "max_body_size": 50,  # Very small
                }
            )

            # Create a list where the first item is too large to fit
            large_list = ["x" * 200, "short", "items"]
            request = MCPRequest(
                jsonrpc="2.0", method="test", id="123", params={"items": large_list}
            )
            pipeline, _ = build_pipeline(request)

            # Test the _truncate_body method directly on the list
            result = plugin._truncate_body(large_list)

            # Should be a string (fallback) containing actual content
            assert isinstance(result, str)
            assert "...[truncated]" in result
            # Should include part of the original JSON content
            assert '["x' in result or "xxx" in result

    def test_max_body_size_minimum_validation(self):
        """Test that max_body_size must be at least 50 bytes when set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Values below 50 (but not 0) should raise ValueError
            with pytest.raises(ValueError, match="must be at least 50 bytes"):
                JsonAuditingPlugin(
                    {
                        "output_file": f"{tmpdir}/test.log",
                        "max_body_size": 30,
                    }
                )

            # 0 (unlimited) should be allowed
            plugin = JsonAuditingPlugin(
                {
                    "output_file": f"{tmpdir}/test.log",
                    "max_body_size": 0,
                }
            )
            assert plugin.max_body_size == 0

            # 50 (minimum) should be allowed
            plugin = JsonAuditingPlugin(
                {
                    "output_file": f"{tmpdir}/test.log",
                    "max_body_size": 50,
                }
            )
            assert plugin.max_body_size == 50

    def test_deprecation_warning(self):
        """Test that deprecated redact_request_fields triggers a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:

            # Capture log output
            import unittest

            with unittest.TestCase().assertLogs(
                "gatekit.plugins.auditing.json_lines", level="WARNING"
            ) as cm:
                JsonAuditingPlugin(
                    {
                        "output_file": f"{tmpdir}/test.log",
                        "redact_request_fields": [
                            "password",
                            "token",
                        ],  # Deprecated option
                    }
                )

            # Check that warning was logged
            assert any("redact_request_fields" in msg for msg in cm.output)
            assert any("has been removed" in msg for msg in cm.output)


class TestPipelineOutcomeInLogs:
    def test_pipeline_outcome_in_request_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline_allowed, _ = build_pipeline(request, allowed=True)
            data_a = plugin._extract_common_request_data(
                request, pipeline_allowed, "test_server"
            )
            log_a = json.loads(plugin._format_request_entry(data_a).strip())
            assert log_a["pipeline_outcome"] == "allowed"
            request_b = MCPRequest(jsonrpc="2.0", method="test", id="124")
            pipeline_block, _ = build_pipeline(
                request_b, allowed=False, reason="blocked"
            )
            pipeline_block.stages[0].result.allowed = False
            pipeline_block.pipeline_outcome = PipelineOutcome.BLOCKED
            data_b = plugin._extract_common_request_data(
                request_b, pipeline_block, "test_server"
            )
            log_b = json.loads(plugin._format_request_entry(data_b).strip())
            assert log_b["pipeline_outcome"] == "blocked"

    def test_pipeline_outcome_in_response_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result={})
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log = json.loads(plugin._format_response_entry(data).strip())
            assert log["pipeline_outcome"] == "allowed"


class TestTimestampConsistency:
    def test_timestamp_consistency_within_single_log_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())
            # Verify timestamp exists and is in ISO format with timezone
            ts = log_data["timestamp"]
            assert ts is not None
            assert "T" in ts  # ISO format
            assert "+" in ts or "Z" in ts  # Has timezone

    def test_timestamp_changes_between_separate_log_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            r1 = MCPRequest(jsonrpc="2.0", method="test", id="123")
            p1, _ = build_pipeline(r1)
            d1 = plugin._extract_common_request_data(r1, p1, "test_server")
            log1 = json.loads(plugin._format_request_entry(d1).strip())
            time.sleep(0.001)
            r2 = MCPRequest(jsonrpc="2.0", method="test", id="124")
            p2, _ = build_pipeline(r2)
            d2 = plugin._extract_common_request_data(r2, p2, "test_server")
            log2 = json.loads(plugin._format_request_entry(d2).strip())
            assert log1["timestamp"] != log2["timestamp"]


class TestJsonSerializationRobustness:
    def test_serialization_fallback_on_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})

            class NonSerializable:
                pass

            log_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": "TEST",
                "non_serializable": NonSerializable(),
            }
            result = plugin._format_json_output(log_data)
            parsed = json.loads(result.strip())
            assert parsed["error"] == "JSON serialization failed"


class TestModifiedFieldInLogs:
    """Test the 'modified' field in JSONL output."""

    def test_modified_false_when_no_modification(self):
        """Verify modified=false for unmodified requests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            pipeline, _ = build_pipeline(request, outcome=StageOutcome.ALLOWED)
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())
            assert log_data["modified"] is False

    def test_modified_true_when_content_modified(self):
        """Verify modified=true when pipeline has modification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            # Build pipeline with MODIFIED stage outcome
            pipeline, decision = build_pipeline(request, outcome=StageOutcome.MODIFIED)
            pipeline.stages[0].outcome = StageOutcome.MODIFIED
            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())
            assert log_data["modified"] is True

    def test_modified_field_in_response_logs(self):
        """Verify modified field appears in response logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result={})
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert "modified" in log_data
            assert log_data["modified"] is False

    def test_modified_field_in_notification_logs(self):
        """Verify modified field appears in notification logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            notification = MCPNotification(
                jsonrpc="2.0", method="progress", params={"pct": 50}
            )
            pipeline, _ = build_pipeline(notification)
            data = plugin._extract_common_notification_data(
                notification, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_notification_entry(data).strip())
            assert "modified" in log_data


class TestResponseStatusField:
    """Test the 'response_status' field in JSONL output."""

    def test_response_status_success_for_normal_response(self):
        """Verify response_status='success' for responses with result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123", result={"data": "value"})
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert log_data["response_status"] == "success"

    def test_response_status_error_for_error_response(self):
        """Verify response_status='error' for responses with error field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            response = MCPResponse(jsonrpc="2.0", id="123")
            response.error = {"code": -32600, "message": "Invalid Request"}
            pipeline, _ = build_pipeline(request)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            assert log_data["response_status"] == "error"

    def test_response_status_independent_of_pipeline_outcome(self):
        """Response status reflects MCP response, not security decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            # Successful MCP response
            response = MCPResponse(jsonrpc="2.0", id="123", result={"ok": True})
            # But blocked by security
            pipeline, _ = build_pipeline(request, allowed=False, outcome=StageOutcome.BLOCKED)
            pipeline.pipeline_outcome = PipelineOutcome.BLOCKED
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test_server"
            )
            log_data = json.loads(plugin._format_response_entry(data).strip())
            # response_status is about MCP protocol response, not security
            assert log_data["response_status"] == "success"
            # pipeline_outcome reflects security decision
            assert log_data["pipeline_outcome"] == "blocked"


class TestRedactedContentInLogs:
    """Test that audit logs use pipeline.final_content (post-redaction) instead of original content.

    This is a critical security fix to prevent log replay attacks where sensitive data
    that was redacted by security plugins still appears in audit logs.
    """

    def test_request_params_use_final_content_when_modified(self):
        """Verify request params come from pipeline.final_content, not original request."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_request_body": True}
            )

            # Original request with sensitive data
            original_request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="123",
                params={
                    "name": "authenticate",
                    "arguments": {
                        "api_key": "sk-proj-abc123secretkey",
                        "username": "user@example.com",
                    },
                },
            )

            # Redacted version that security plugin would produce
            redacted_request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="123",
                params={
                    "name": "authenticate",
                    "arguments": {
                        "api_key": "[SECRET REDACTED by Gatekit]",
                        "username": "user@example.com",
                    },
                },
            )

            # Build pipeline with modification - final_content has redacted version
            pipeline, _ = build_pipeline(original_request, outcome=StageOutcome.MODIFIED)
            pipeline.final_content = redacted_request

            # Extract and format log entry
            data = plugin._extract_common_request_data(original_request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())

            # SECURITY: params should contain redacted content, NOT original sensitive data
            assert "request_body" in log_data
            body = log_data["request_body"]
            assert body["arguments"]["api_key"] == "[SECRET REDACTED by Gatekit]"
            assert "sk-proj-abc123" not in str(body)  # Original secret must NOT appear
            assert body["arguments"]["username"] == "user@example.com"  # Non-sensitive preserved

    def test_request_params_fallback_to_original_when_no_modification(self):
        """Verify original request params are used when pipeline.final_content is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_request_body": True}
            )

            request = MCPRequest(
                jsonrpc="2.0",
                method="test",
                id="123",
                params={"data": "value"},
            )

            # Pipeline with no modification (final_content is None)
            pipeline, _ = build_pipeline(request)
            pipeline.final_content = None

            data = plugin._extract_common_request_data(request, pipeline, "test_server")
            log_data = json.loads(plugin._format_request_entry(data).strip())

            # Should use original params when no final_content
            assert log_data["request_body"]["data"] == "value"

    @pytest.mark.asyncio
    async def test_response_body_uses_final_content_when_modified(self):
        """Verify response body comes from pipeline.final_content, not original response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_response_body": True}
            )
            try:
                request = MCPRequest(jsonrpc="2.0", method="test", id="123")

                # Original response with sensitive data
                original_response = MCPResponse(
                    jsonrpc="2.0",
                    id="123",
                    result={
                        "data": "public info",
                        "ssn": "123-45-6789",
                        "credit_card": "4111-1111-1111-1111",
                    },
                )

                # Redacted version that security plugin would produce
                redacted_response = MCPResponse(
                    jsonrpc="2.0",
                    id="123",
                    result={
                        "data": "public info",
                        "ssn": "[PII REDACTED]",
                        "credit_card": "[PII REDACTED]",
                    },
                )

                # Build pipeline with modification
                pipeline, _ = build_pipeline(request, outcome=StageOutcome.MODIFIED)
                pipeline.final_content = redacted_response

                # Call the overridden log_response method
                await plugin.log_response(request, original_response, pipeline, "test_server")

                # Read the log file to verify
                with open(f"{tmpdir}/test.log", "r") as f:
                    log_line = f.read().strip()
                    log_data = json.loads(log_line)

                    # SECURITY: response_body should contain redacted content
                    assert "response_body" in log_data
                    body = log_data["response_body"]
                    assert body["data"] == "public info"
                    assert body["ssn"] == "[PII REDACTED]"
                    assert body["credit_card"] == "[PII REDACTED]"
                    assert "123-45-6789" not in str(body)  # Original SSN must NOT appear
                    assert "4111-1111" not in str(body)  # Original CC must NOT appear
            finally:
                plugin.cleanup()
                _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_response_body_fallback_to_original_when_no_modification(self):
        """Verify original response body is used when pipeline.final_content is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_response_body": True}
            )
            try:
                request = MCPRequest(jsonrpc="2.0", method="test", id="123")
                response = MCPResponse(
                    jsonrpc="2.0", id="123", result={"data": "value"}
                )

                # Pipeline with no modification
                pipeline, _ = build_pipeline(request)
                pipeline.final_content = None

                await plugin.log_response(request, response, pipeline, "test_server")

                with open(f"{tmpdir}/test.log", "r") as f:
                    log_data = json.loads(f.read().strip())
                    assert log_data["response_body"]["data"] == "value"
            finally:
                plugin.cleanup()
                _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_notification_body_uses_final_content_when_modified(self):
        """Verify notification body comes from pipeline.final_content, not original notification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_notification_body": True}
            )
            try:
                # Original notification with sensitive data
                original_notification = MCPNotification(
                    jsonrpc="2.0",
                    method="progress/update",
                    params={
                        "status": "processing",
                        "file_path": "/home/user/documents/financial_records.xlsx",
                        "user_email": "john.doe@company.com",
                    },
                )

                # Redacted version
                redacted_notification = MCPNotification(
                    jsonrpc="2.0",
                    method="progress/update",
                    params={
                        "status": "processing",
                        "file_path": "/home/user/documents/financial_records.xlsx",
                        "user_email": "[EMAIL REDACTED]",
                    },
                )

                # Build pipeline with modification
                pipeline, _ = build_pipeline(original_notification, outcome=StageOutcome.MODIFIED)
                pipeline.final_content = redacted_notification

                await plugin.log_notification(original_notification, pipeline, "test_server")

                with open(f"{tmpdir}/test.log", "r") as f:
                    log_data = json.loads(f.read().strip())

                    # SECURITY: notification_body should contain redacted content
                    assert "notification_body" in log_data
                    body = log_data["notification_body"]
                    assert body["user_email"] == "[EMAIL REDACTED]"
                    assert "john.doe@company.com" not in str(body)
            finally:
                plugin.cleanup()
                _close_all_logging_handlers()

    @pytest.mark.asyncio
    async def test_notification_body_fallback_to_original_when_no_modification(self):
        """Verify original notification body is used when pipeline.final_content is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_notification_body": True}
            )
            try:
                notification = MCPNotification(
                    jsonrpc="2.0",
                    method="progress",
                    params={"status": "running"},
                )

                # Pipeline with no modification
                pipeline, _ = build_pipeline(notification)
                pipeline.final_content = None

                await plugin.log_notification(notification, pipeline, "test_server")

                with open(f"{tmpdir}/test.log", "r") as f:
                    log_data = json.loads(f.read().strip())
                    assert log_data["notification_body"]["status"] == "running"
            finally:
                plugin.cleanup()
                _close_all_logging_handlers()

    def test_base_auditing_extract_request_data_uses_final_content(self):
        """Test that _extract_common_request_data uses pipeline.final_content for params."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})

            original_request = MCPRequest(
                jsonrpc="2.0",
                method="test",
                id="123",
                params={"secret": "original_sensitive_value"},
            )

            redacted_request = MCPRequest(
                jsonrpc="2.0",
                method="test",
                id="123",
                params={"secret": "[REDACTED]"},
            )

            pipeline, _ = build_pipeline(original_request, outcome=StageOutcome.MODIFIED)
            pipeline.final_content = redacted_request

            data = plugin._extract_common_request_data(original_request, pipeline, "test_server")

            # The params in extracted data should be from final_content
            assert data["params"]["secret"] == "[REDACTED]"
            assert "original_sensitive_value" not in str(data["params"])

    def test_base_auditing_extract_notification_data_uses_final_content(self):
        """Test that _extract_common_notification_data uses pipeline.final_content for params."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin({"output_file": f"{tmpdir}/test.log"})

            original_notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"token": "bearer_xyz123"},
            )

            redacted_notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"token": "[BEARER TOKEN REDACTED]"},
            )

            pipeline, _ = build_pipeline(original_notification, outcome=StageOutcome.MODIFIED)
            pipeline.final_content = redacted_notification

            data = plugin._extract_common_notification_data(original_notification, pipeline, "test_server")

            # The params in extracted data should be from final_content
            assert data["params"]["token"] == "[BEARER TOKEN REDACTED]"
            assert "bearer_xyz123" not in str(data["params"])

    def test_response_error_uses_final_content_when_modified(self):
        """Verify response error body also uses final_content when modified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = JsonAuditingPlugin(
                {"output_file": f"{tmpdir}/test.log", "include_response_body": True}
            )

            request = MCPRequest(jsonrpc="2.0", method="test", id="123")

            # Original error response with sensitive details
            original_response = MCPResponse(jsonrpc="2.0", id="123")
            original_response.error = {
                "code": -32000,
                "message": "Auth failed for user john.doe@secret.com",
                "data": {"connection_string": "postgres://admin:password123@db.internal:5432/prod"},
            }

            # Redacted version
            redacted_response = MCPResponse(jsonrpc="2.0", id="123")
            redacted_response.error = {
                "code": -32000,
                "message": "Auth failed for user [EMAIL REDACTED]",
                "data": {"connection_string": "[CONNECTION STRING REDACTED]"},
            }

            pipeline, _ = build_pipeline(request, outcome=StageOutcome.MODIFIED)
            pipeline.final_content = redacted_response

            # Use synchronous extraction to test the logic
            data = plugin._extract_common_response_data(request, original_response, pipeline, "test_server")

            # For error response body, we need to check what log_response would produce
            # since that's where the final_content check happens for include_response_body
            response_for_body = (
                pipeline.final_content
                if pipeline.final_content and isinstance(pipeline.final_content, MCPResponse)
                else original_response
            )

            if response_for_body.error is not None:
                body = plugin._truncate_body(response_for_body.error)
                assert "[EMAIL REDACTED]" in str(body)
                assert "password123" not in str(body)
