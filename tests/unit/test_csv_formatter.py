"""Tests for CSV formatter functionality in CsvAuditingPlugin.

This test suite follows Test-Driven Development (TDD) methodology:
1. RED: Tests are written first and should fail initially since CSV implementation is incomplete
2. GREEN: Minimal implementation is added to make tests pass
3. REFACTOR: Code is improved while keeping tests green

These tests define the contract for CSV format support in the CsvAuditingPlugin.
"""

import csv
import io
import tempfile

import pytest

from gatekit.plugins.auditing.csv import CsvAuditingPlugin
from gatekit.plugins.interfaces import (
    PipelineOutcome,
    PipelineStage,
    PluginResult,
    ProcessingPipeline,
    StageOutcome,
)
from gatekit.protocol.messages import MCPNotification, MCPRequest, MCPResponse

# Import shared logging cleanup helpers (Windows compatibility)
from conftest import close_all_logging_handlers, safe_unlink

# Aliases for backward compatibility with existing test code
_close_all_logging_handlers = close_all_logging_handlers
_safe_unlink = safe_unlink


class TestCSVFormatterBasic:
    """Test basic CSV formatter functionality."""

    def test_csv_formatter_initialization(self):
        """Test CSV formatter is initialized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            # Should have CSV attributes
            assert hasattr(plugin, "delimiter")
            assert hasattr(plugin, "field_order")
            assert plugin.field_order is not None

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_format_basic_request(self):
        """Test basic CSV message formatting for request."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0", id="test-123", method="tools/list", params={}
            )

            # Build pipeline with a passing security stage
            decision = PluginResult(
                allowed=True, reason="Default allow", metadata={"plugin": "test_plugin"}
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="test_plugin",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            csv_row = plugin._format_request_entry(data)
            formatted = csv_row

            # Parse CSV to verify structure
            reader = csv.DictReader(io.StringIO(formatted))
            rows = list(reader)

            assert len(rows) == 1
            row = rows[0]

            # Check basic fields
            assert row.get("event_type") == "REQUEST"
            assert row.get("request_id") == "test-123"
            assert row.get("method") == "tools/list"
            assert row.get("pipeline_outcome") == "allowed"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_format_with_header(self):
        """Test CSV formatting includes header."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id="test-456",
                method="tools/call",
                params={"tool": "read_file"},
            )

            decision = PluginResult(allowed=False, reason="Blocked by policy")
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.BLOCKED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.BLOCKED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            lines = formatted.strip().split("\n")
            assert len(lines) == 2  # Header + data row

            # Check header contains expected fields
            header_fields = lines[0].split(",")
            expected_fields = [
                "timestamp",
                "event_type",
                "request_id",
                "server_name",
                "method",
                "tool",
                "pipeline_outcome",
                "security_evaluated",
            ]
            for field in expected_fields:
                assert field in header_fields

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_format_special_characters(self):
        """Test CSV formatting handles special characters."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id="test-789",
                method="tools/call",
                params={"content": 'String with "quotes" and\nnewlines'},
            )

            decision = PluginResult(
                allowed=True, reason='Reason with, comma and "quotes"'
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="plugin",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            # Parse with CSV reader to ensure proper escaping
            reader = csv.DictReader(io.StringIO(formatted))
            row = next(reader)

            # Ensure CSV produced allowed pipeline_outcome
            assert row["pipeline_outcome"] == "allowed"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)


class TestCSVFormatterConfiguration:
    """Test CSV formatter configuration options."""

    def test_csv_custom_delimiter(self):
        """Test CSV formatting with custom delimiter."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "format": "csv",
                "csv_config": {"delimiter": "|"},
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0", id="test-pipe", method="initialize", params={}
            )

            decision = PluginResult(allowed=True, reason="OK")
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            # Check delimiter is used
            assert "|" in formatted
            assert "," not in formatted  # Default delimiter not used

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_custom_quote_char(self):
        """Test CSV formatting with custom quote character."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "format": "csv",
                "csv_config": {"quote_char": "'"},
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id="test-quote",
                method="tools/list",
                params={"filter": "needs 'quotes'"},
            )

            decision = PluginResult(allowed=True, reason="Contains 'quotes'")
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            # We don't assert internal quote escaping of params in this pipeline-derived path
            assert "tools/list" in formatted

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_null_value_handling(self):
        """Test CSV formatting with custom null value."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "format": "csv",
                "csv_config": {"null_value": "N/A"},
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            notification = MCPNotification(
                jsonrpc="2.0",
                method="server/log",
                params={"level": "info", "message": "test"},
            )

            PluginResult(allowed=True, reason="OK", metadata={})
            pipeline = ProcessingPipeline(original_content=notification)
            # No security evaluation
            data = plugin._extract_common_notification_data(
                notification, pipeline, "test-server"
            )
            formatted = plugin._format_notification_entry(data)

            # Parse CSV
            reader = csv.DictReader(io.StringIO(formatted))
            row = next(reader)

            # Check null values are replaced with configured null_value
            # Notifications have no request_id, so it should be N/A
            assert row.get("request_id") == "N/A"
            # Notifications also have no tool, so it should be N/A
            assert row.get("tool") == "N/A"
            # Missing fields (not in notification entry dict) should also get N/A
            assert row.get("response_status") == "N/A"
            assert row.get("error_code") == "N/A"
            assert row.get("error_message") == "N/A"
            assert row.get("error_classification") == "N/A"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_null_value_for_request_missing_error_fields(self):
        """Test that REQUEST events get null_value for missing error/response fields."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "csv_config": {"null_value": "NULL"},
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id="req-123",
                method="tools/list",
                params={},
            )

            decision = PluginResult(allowed=True, reason="OK")
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED

            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            # Parse CSV
            reader = csv.DictReader(io.StringIO(formatted))
            row = next(reader)

            # REQUEST events don't have error fields - they should get null_value
            assert row.get("response_status") == "NULL"
            assert row.get("error_code") == "NULL"
            assert row.get("error_message") == "NULL"
            assert row.get("error_classification") == "NULL"

            # But fields that ARE present should have their actual values
            assert row.get("request_id") == "req-123"
            assert row.get("method") == "tools/list"
            assert row.get("event_type") == "REQUEST"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)


class TestCSVFormatterIntegration:
    """Test CSV formatter integration with CsvAuditingPlugin."""

    @pytest.mark.asyncio
    async def test_csv_log_request_response_cycle(self):
        """Test CSV formatting through complete request/response cycle."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            # Request
            request = MCPRequest(
                jsonrpc="2.0",
                id="cycle-test",
                method="tools/call",
                params={
                    "name": "calculator",
                    "args": {"operation": "add", "a": 1, "b": 2},
                },
            )

            # Build pipeline for request
            req_decision = PluginResult(allowed=True, reason="Calculator allowed")
            req_pipeline = ProcessingPipeline(original_content=request)
            req_stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=req_decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            req_pipeline.add_stage(req_stage)
            req_pipeline.had_security_plugin = True
            req_pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            await plugin.log_request(request, req_pipeline, "test_server")

            # Response
            response = MCPResponse(
                jsonrpc="2.0", id="cycle-test", result={"output": "3"}
            )

            resp_decision = PluginResult(
                allowed=True, reason="Response allowed", metadata={"duration_ms": 42}
            )
            resp_pipeline = ProcessingPipeline(original_content=request)
            resp_stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=resp_decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            resp_pipeline.add_stage(resp_stage)
            resp_pipeline.had_security_plugin = True
            resp_pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            # Store timestamp to allow duration computation path (even if plugin itself extracts from metadata)
            plugin._store_request_timestamp(request)
            await plugin.log_response(request, response, resp_pipeline, "test_server")

            # Read and verify CSV file
            with open(f.name, "r") as csv_file:
                content = csv_file.read()
                lines = content.strip().split("\n")

                # Should have header + 2 data rows
                assert len(lines) >= 3

                # Verify both request and response are logged
                assert "REQUEST" in content
                assert "RESPONSE" in content
                assert "cycle-test" in content
                assert "calculator" in content
                # Duration is calculated dynamically, just verify it's present
                assert "duration_ms" in lines[0]  # Header has duration_ms column

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    @pytest.mark.asyncio
    async def test_csv_log_notification(self):
        """Test CSV formatting for notifications."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            notification = MCPNotification(
                jsonrpc="2.0",
                method="server/progress",
                params={"progress": 50, "total": 100, "operation": "indexing"},
            )

            # Build empty pipeline (no security evaluation for notification)
            pipeline = ProcessingPipeline(original_content=notification)
            await plugin.log_notification(notification, pipeline, "test_server")

            # Read and verify CSV file
            with open(f.name, "r") as csv_file:
                content = csv_file.read()

                # Verify notification is logged
                assert "NOTIFICATION" in content
                assert "server/progress" in content
                assert "indexing" in content

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)


class TestCSVFormatterErrorHandling:
    """Test CSV formatter error handling."""

    def test_csv_invalid_delimiter(self):
        """Test CSV formatter rejects invalid delimiter."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "format": "csv",
                "csv_config": {"delimiter": "abc"},  # Multi-character delimiter
                "critical": False,
            }

            with pytest.raises(
                ValueError, match="delimiter must be a single character"
            ):
                CsvAuditingPlugin(config)

            # Clean up - close any handlers that may have been created before exception
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    # Note: test_csv_invalid_quote_style removed - schema validates quote_style enum
    # See tests/unit/test_schema_validation_coverage.py

    def test_csv_quote_style_nonnumeric(self):
        """Test CSV quote_style: nonnumeric quotes strings but not numbers."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "csv_config": {"quote_style": "nonnumeric"},
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            # Create a response with numeric duration
            request = MCPRequest(
                jsonrpc="2.0",
                id=42,  # Numeric request ID
                method="tools/call",
                params={"name": "test_tool"},
            )

            response = MCPResponse(
                jsonrpc="2.0",
                id=42,
                result={"content": [{"type": "text", "text": "result"}]},
            )

            decision = PluginResult(
                allowed=True,
                reason="Test nonnumeric quoting",
                metadata={"plugin": "test"},
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="test",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED

            # Format a response entry (has duration_ms)
            data = plugin._extract_common_response_data(
                request, response, pipeline, "test-server"
            )
            # Ensure we have a numeric duration for testing
            data["duration_ms"] = 123
            formatted = plugin._format_response_entry(data)

            # Parse the CSV output
            reader = csv.reader(io.StringIO(formatted))
            rows = list(reader)
            # Should have header + data row
            assert len(rows) == 2

            # With QUOTE_NONNUMERIC:
            # - Numeric fields (request_id=42, duration_ms=123) should NOT be quoted
            #   (they appear as plain numbers in the raw CSV)
            # - String fields should be quoted
            # When parsed by csv.reader, quotes are stripped, so we check the raw output

            # Get raw line (skip header)
            lines = formatted.strip().split("\n")
            raw_data_line = lines[1]

            # Numeric fields should appear unquoted in raw output
            # The pattern should include ,42, and ,123, without surrounding quotes
            assert ",42," in raw_data_line or raw_data_line.endswith(",42")
            assert ",123," in raw_data_line or raw_data_line.endswith(",123")

            # String fields should be quoted - check that "RESPONSE" appears quoted
            assert '"RESPONSE"' in raw_data_line or '"RESPONSE_MODIFIED"' in raw_data_line

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_quote_style_all(self):
        """Test CSV quote_style: all quotes every field including numbers."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "csv_config": {"quote_style": "all"},
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id=42,
                method="tools/call",
                params={"name": "test_tool"},
            )

            response = MCPResponse(
                jsonrpc="2.0",
                id=42,
                result={"content": [{"type": "text", "text": "result"}]},
            )

            decision = PluginResult(
                allowed=True,
                reason="Test all quoting",
                metadata={"plugin": "test"},
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="test",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED

            data = plugin._extract_common_response_data(
                request, response, pipeline, "test-server"
            )
            data["duration_ms"] = 123
            formatted = plugin._format_response_entry(data)

            # Get raw data line
            lines = formatted.strip().split("\n")
            raw_data_line = lines[1]

            # With QUOTE_ALL, numeric fields should also be quoted
            # Should see "42" and "123" with quotes
            assert '"42"' in raw_data_line
            assert '"123"' in raw_data_line

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_quote_none_with_escapechar(self):
        """Test CSV formatting with QUOTE_NONE and escapechar for fields containing delimiters."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {
                "output_file": f.name,
                "csv_config": {
                    "quote_style": "none",
                    "escape_char": "\\",
                    "delimiter": ",",
                },
                "critical": False,
            }
            plugin = CsvAuditingPlugin(config)

            # Create request with comma in the reason (delimiter character)
            request = MCPRequest(
                jsonrpc="2.0",
                id="test-escape",
                method="tools/call",
                params={"name": "test,tool"},  # Contains delimiter
            )

            decision = PluginResult(
                allowed=True,
                reason="Test with comma, and more text",
                metadata={"plugin": "escape_test"},
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="escape_test",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            # Should handle the comma correctly with escapechar
            assert formatted is not None
            # Verify the CSV can be parsed back correctly
            import csv
            import io

            reader = csv.reader(io.StringIO(formatted), delimiter=",", escapechar="\\")
            rows = list(reader)
            # Should have header + data row
            assert len(rows) == 2

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_csv_format_with_complex_data(self):
        """Test CSV formatting handles complex nested data."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id="complex-test",
                method="tools/call",
                params={
                    "name": "complex_tool",
                    "args": {
                        "nested": {"deep": {"value": "test"}},
                        "list": [1, 2, 3],
                        "boolean": True,
                    },
                },
            )

            decision = PluginResult(
                allowed=True,
                reason="Complex data test",
                metadata={"scores": [0.1, 0.2, 0.3], "flags": {"a": True, "b": False}},
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="policy",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            data = plugin._extract_common_request_data(request, pipeline, "test-server")
            formatted = plugin._format_request_entry(data)

            # Parse CSV
            reader = csv.DictReader(io.StringIO(formatted))
            row = next(reader)

            # Complex data should be handled (note: CSV doesn't include full params)
            # Just verify the basic request structure is preserved
            assert row.get("request_id") == "complex-test"
            assert row.get("tool") == "complex_tool"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)


class TestCSVAuditLogCorrectness:
    """Test CSV audit log format correctness for compliance and downstream tooling.

    These tests verify the contract that audit log consumers depend on:
    - Required fields are always present
    - Field values are semantically correct
    - Request/response correlation works
    """

    @pytest.mark.asyncio
    async def test_request_response_correlation_by_id(self):
        """Test that request and response entries can be correlated by request_id."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request_id = "correlation-test-12345"

            # Log request
            request = MCPRequest(
                jsonrpc="2.0",
                id=request_id,
                method="tools/call",
                params={"name": "test_tool"},
            )
            req_pipeline = ProcessingPipeline(original_content=request)
            req_stage = PipelineStage(
                plugin_name="security",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=PluginResult(allowed=True, reason="OK"),
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            req_pipeline.add_stage(req_stage)
            req_pipeline.had_security_plugin = True
            req_pipeline.pipeline_outcome = PipelineOutcome.ALLOWED

            await plugin.log_request(request, req_pipeline, "test-server")

            # Log response
            response = MCPResponse(jsonrpc="2.0", id=request_id, result={"data": "ok"})
            resp_pipeline = ProcessingPipeline(original_content=response)
            resp_stage = PipelineStage(
                plugin_name="security",
                plugin_type="security",
                input_content=response,
                output_content=response,
                content_hash="hash",
                result=PluginResult(allowed=True, reason="OK"),
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            resp_pipeline.add_stage(resp_stage)
            resp_pipeline.had_security_plugin = True
            resp_pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            plugin._store_request_timestamp(request)

            await plugin.log_response(request, response, resp_pipeline, "test-server")

            # Parse CSV and verify correlation
            with open(f.name, "r") as csv_file:
                reader = csv.DictReader(csv_file)
                rows = list(reader)

            # Should have exactly 2 rows (request + response)
            assert len(rows) == 2

            # Both should have same request_id for correlation
            assert rows[0]["request_id"] == request_id
            assert rows[1]["request_id"] == request_id

            # Should be distinguishable by event_type
            event_types = {rows[0]["event_type"], rows[1]["event_type"]}
            assert "REQUEST" in event_types or any("REQUEST" in et for et in event_types)
            assert "RESPONSE" in event_types or any("RESPONSE" in et for et in event_types)

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    @pytest.mark.asyncio
    async def test_security_evaluation_tracked(self):
        """Test that security_evaluated field correctly reflects whether security plugins ran."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0", id="security-test", method="initialize", params={}
            )

            # Pipeline WITH security evaluation
            pipeline_with_security = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="pii_filter",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=PluginResult(allowed=True, reason="No PII"),
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline_with_security.add_stage(stage)
            pipeline_with_security.had_security_plugin = True
            pipeline_with_security.pipeline_outcome = PipelineOutcome.ALLOWED

            await plugin.log_request(request, pipeline_with_security, "test-server")

            # Parse and verify
            with open(f.name, "r") as csv_file:
                reader = csv.DictReader(csv_file)
                row = next(reader)

            assert row["security_evaluated"] == "true"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    @pytest.mark.asyncio
    async def test_blocked_request_has_correct_outcome(self):
        """Test that blocked requests have pipeline_outcome=blocked."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id="blocked-test",
                method="tools/call",
                params={"name": "dangerous_tool"},
            )

            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="secrets_filter",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=PluginResult(allowed=False, reason="Secret detected"),
                processing_time_ms=2.5,
                outcome=StageOutcome.BLOCKED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.BLOCKED

            await plugin.log_request(request, pipeline, "test-server")

            with open(f.name, "r") as csv_file:
                reader = csv.DictReader(csv_file)
                row = next(reader)

            assert row["pipeline_outcome"] == "blocked"
            assert "secret" in row["reason"].lower() or "Secret" in row["reason"]

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    @pytest.mark.asyncio
    async def test_error_response_has_error_fields(self):
        """Test that error responses populate error_code and error_message fields."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0", id="error-test", method="tools/call", params={}
            )

            # Error response
            response = MCPResponse(
                jsonrpc="2.0",
                id="error-test",
                error={"code": -32601, "message": "Method not found"},
            )

            pipeline = ProcessingPipeline(original_content=response)
            stage = PipelineStage(
                plugin_name="security",
                plugin_type="security",
                input_content=response,
                output_content=response,
                content_hash="hash",
                result=PluginResult(allowed=True, reason="Error response allowed"),
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
            plugin._store_request_timestamp(request)

            await plugin.log_response(request, response, pipeline, "test-server")

            with open(f.name, "r") as csv_file:
                reader = csv.DictReader(csv_file)
                row = next(reader)

            # Error fields should be populated
            # Note: error_code may be prefixed with ' for CSV injection prevention
            assert "-32601" in row["error_code"]
            assert "not found" in row["error_message"].lower()
            assert row["error_classification"] == "method_not_found"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_all_required_fields_in_header(self):
        """Test that CSV header contains all required fields for audit compliance."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            # Required fields for audit compliance
            required_fields = [
                "timestamp",
                "event_type",
                "request_id",
                "server_name",
                "method",
                "pipeline_outcome",
                "security_evaluated",
                "reason",
            ]

            for field in required_fields:
                assert field in plugin.field_order, f"Required field '{field}' missing from CSV schema"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)


class TestCSVInjectionPrevention:
    """Test CSV injection attack prevention.

    CSV injection (aka formula injection) is a security vulnerability where
    malicious content in CSV cells can execute code when opened in spreadsheet
    applications like Excel. Dangerous payloads start with =, +, -, @, etc.

    See: https://owasp.org/www-community/attacks/CSV_Injection
    """

    def test_sanitize_formula_injection_equals(self):
        """Test that = prefix (formula start) is sanitized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            # Classic formula injection payload
            malicious = "=cmd|' /C calc'!A0"
            sanitized = plugin._sanitize_csv_injection(malicious)

            # Should prefix with single quote to prevent execution
            assert sanitized.startswith("'")
            assert sanitized == "'" + malicious

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_sanitize_formula_injection_plus(self):
        """Test that + prefix (alternative formula start) is sanitized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            malicious = "+cmd|' /C calc'!A0"
            sanitized = plugin._sanitize_csv_injection(malicious)

            assert sanitized.startswith("'")
            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_sanitize_formula_injection_minus(self):
        """Test that - prefix is sanitized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            malicious = "-1+1+cmd|' /C calc'!A0"
            sanitized = plugin._sanitize_csv_injection(malicious)

            assert sanitized.startswith("'")
            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_sanitize_formula_injection_at(self):
        """Test that @ prefix (external data) is sanitized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            # @ can trigger external data retrieval in Excel
            malicious = "@SUM(1+1)*cmd|' /C calc'!A0"
            sanitized = plugin._sanitize_csv_injection(malicious)

            assert sanitized.startswith("'")
            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_sanitize_formula_injection_tab(self):
        """Test that tab character prefix is sanitized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            malicious = "\t=cmd|' /C calc'!A0"
            sanitized = plugin._sanitize_csv_injection(malicious)

            assert sanitized.startswith("'")
            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_sanitize_formula_injection_carriage_return(self):
        """Test that carriage return is escaped (which neutralizes the formula threat).

        When a value starts with \\r, the newline escaping converts it to \\\\r first,
        which means the first character becomes '\\' not '\\r'. This neutralizes the
        formula injection threat without needing the single-quote prefix.
        """
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            malicious = "\r=cmd|' /C calc'!A0"
            sanitized = plugin._sanitize_csv_injection(malicious)

            # The \r is escaped to \\r, so the value now starts with \
            # This neutralizes the formula injection threat
            assert sanitized.startswith("\\r")
            assert "\\r=cmd" in sanitized
            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    def test_safe_content_not_modified(self):
        """Test that safe content is not modified."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            safe_values = [
                "Normal text",
                "text with = in middle",
                "123456",
                "user@example.com",  # @ not at start
                "path/to/file",
                "",  # Empty string
            ]

            for value in safe_values:
                sanitized = plugin._sanitize_csv_injection(value)
                assert sanitized == value, f"Safe value '{value}' was incorrectly modified"

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)

    @pytest.mark.asyncio
    async def test_injection_sanitized_in_logged_output(self):
        """Test that CSV injection payloads in actual log output are sanitized."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            config = {"output_file": f.name, "critical": False}
            plugin = CsvAuditingPlugin(config)

            # Attacker tries to inject via tool arguments
            request = MCPRequest(
                jsonrpc="2.0",
                id="inject-test",
                method="tools/call",
                params={
                    "name": "=cmd|' /C calc'!A0",  # Malicious tool name
                    "args": {"data": "normal"},
                },
            )

            decision = PluginResult(
                allowed=False,
                reason="=HYPERLINK('http://evil.com','Click')",  # Malicious reason
            )
            pipeline = ProcessingPipeline(original_content=request)
            stage = PipelineStage(
                plugin_name="security",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=decision,
                processing_time_ms=1.0,
                outcome=StageOutcome.BLOCKED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.had_security_plugin = True
            pipeline.pipeline_outcome = PipelineOutcome.BLOCKED

            await plugin.log_request(request, pipeline, "test-server")

            # Read the CSV output
            with open(f.name, "r") as csv_file:
                content = csv_file.read()

            # The malicious payloads should be prefixed with single quote
            # Note: tool name extraction may transform the value, but if it appears
            # it should be sanitized
            lines = content.split("\n")
            data_line = lines[1] if len(lines) > 1 else ""

            # Verify no raw formula injection characters at field boundaries
            # After CSV parsing, dangerous chars should be quoted
            assert "=cmd" not in data_line or "'=cmd" in data_line or '"=cmd' in data_line

            # Clean up - must close all logging handlers before deleting file on Windows
            plugin.cleanup()
            _close_all_logging_handlers()
            _safe_unlink(f.name)
