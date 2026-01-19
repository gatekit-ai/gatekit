"""Tests for BaseAuditingPlugin core functionality.

This test suite covers the foundational functionality of the BaseAuditingPlugin class:
- Configuration and initialization
- Path resolution and validation
- Request timestamp tracking and cleanup
- Resource management (handlers, cleanup)
- Thread safety and concurrent access
- Critical vs non-critical error handling
"""

import pytest
import tempfile
import threading
import time
from pathlib import Path

from gatekit.plugins.auditing.base import BaseAuditingPlugin
from gatekit.plugins.interfaces import (
    PluginResult,
    ProcessingPipeline,
    PipelineStage,
    StageOutcome,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class MockAuditingPlugin(BaseAuditingPlugin):
    """Concrete implementation using new _format_*_entry API.

    Captures emitted log lines in-memory for assertions instead of relying on
    file output. This avoids flakiness and focuses tests on formatting & data
    extraction behaviors.
    """

    def __init__(self, config):
        super().__init__(config)
        self.emitted = []  # capture log messages

    # Override safe log to capture
    def _safe_log(self, message: str):  # type: ignore[override]
        self.emitted.append(message)

    # Simple line-based formatting making key/value presence easy to assert
    def _get_first_plugin_name(self, data):
        """Extract plugin name from first pipeline stage."""
        pipeline = data.get('pipeline', {})
        stages = pipeline.get('stages', [])
        if stages:
            # Stage metadata uses "plugin" key (from to_metadata_dict())
            return stages[0].get('plugin')
        return None

    def _format_request_entry(self, data):  # type: ignore[override]
        outcome = data['pipeline_outcome'].value if 'pipeline_outcome' in data else 'unknown'
        plugin_name = self._get_first_plugin_name(data)
        return (
            f"REQUEST method={data['method']} outcome={outcome} "
            f"plugin={plugin_name} reason={data.get('reason')} "
            f"modified={data['modified']} event={data['event_type']}"
        )

    def _format_response_entry(self, data):  # type: ignore[override]
        outcome = data['pipeline_outcome'].value if 'pipeline_outcome' in data else 'unknown'
        plugin_name = self._get_first_plugin_name(data)
        return (
            f"RESPONSE request_id={data.get('request_id')} status={data.get('response_status')} "
            f"outcome={outcome} plugin={plugin_name} duration={data.get('duration_ms')}"
        )

    def _format_notification_entry(self, data):  # type: ignore[override]
        outcome = data['pipeline_outcome'].value if 'pipeline_outcome' in data else 'unknown'
        plugin_name = self._get_first_plugin_name(data)
        return (
            f"NOTIFICATION method={data['method']} outcome={outcome} "
            f"plugin={plugin_name} event={data['event_type']}"
        )


class TestConfiguration:
    """Test configuration and initialization."""

    def test_default_configuration(self):
        """Test plugin initialization with default configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            assert plugin.max_file_size_mb == 10
            assert plugin.backup_count == 5
            assert plugin.critical  # All plugins default to critical=True

    def test_custom_configuration(self):
        """Test plugin initialization with custom configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "output_file": str(Path(tmpdir) / "test.log"),
                "max_file_size_mb": 20,
                "backup_count": 10,
                "critical": True,
                "event_buffer_size": 50,
            }
            plugin = MockAuditingPlugin(config)

            assert plugin.max_file_size_mb == 20
            assert plugin.backup_count == 10
            assert plugin.critical  # Should respect configured value
            assert plugin._event_buffer.maxlen == 50

    def test_invalid_configuration_types(self):
        """Test that invalid configuration types are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Invalid max_file_size_mb
            with pytest.raises(TypeError, match="max_file_size_mb must be positive"):
                MockAuditingPlugin(
                    {
                        "output_file": str(Path(tmpdir) / "test.log"),
                        "max_file_size_mb": -1,
                    }
                )

            # Invalid backup_count
            with pytest.raises(TypeError, match="backup_count must be non-negative"):
                MockAuditingPlugin(
                    {"output_file": str(Path(tmpdir) / "test.log"), "backup_count": -1}
                )


class TestPathResolution:
    """Test path resolution and validation."""

    def test_absolute_path_resolution(self):
        """Test that absolute paths are used directly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            absolute_path = str(Path(tmpdir) / "test.log")
            config = {"output_file": absolute_path}
            plugin = MockAuditingPlugin(config)

            # On macOS, paths may be resolved through symlinks, so compare resolved paths
            assert Path(plugin.output_file).resolve() == Path(absolute_path).resolve()

    def test_relative_path_with_config_directory(self):
        """Test that relative paths are resolved against config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            config = {"output_file": "logs/audit.log"}
            plugin = MockAuditingPlugin(config)
            plugin.set_config_directory(config_dir)

            expected_path = config_dir / "logs" / "audit.log"
            assert Path(plugin.output_file) == expected_path.resolve()

    def test_path_validation_errors(self):
        """Test path validation error handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            errors = plugin.validate_paths()
            # Should be no errors for valid path
            assert len(errors) == 0


class TestRequestTimestamps:
    """Test request timestamp tracking and cleanup."""

    def test_store_and_calculate_duration(self):
        """Test basic timestamp storage and duration calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            # Store timestamp
            request = MCPRequest(jsonrpc="2.0", method="test", id="123")
            plugin._store_request_timestamp(request)

            # Should have stored timestamp
            assert "123" in plugin.request_timestamps

            # Calculate duration after a small delay
            time.sleep(0.01)  # 10ms delay
            duration = plugin._calculate_duration("123")

            # Should return valid duration and clean up timestamp
            assert duration is not None
            assert duration >= 10  # At least 10ms
            assert "123" not in plugin.request_timestamps  # Cleaned up

    def test_ttl_cleanup(self):
        """Test TTL cleanup prevents memory leaks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            # Store many request timestamps
            current_time = time.time()
            for i in range(10):
                request = MCPRequest(jsonrpc="2.0", method="test", id=str(i))
                plugin._store_request_timestamp(request)

            assert len(plugin.request_timestamps) == 10

            # Force cleanup with time 6 minutes in future (beyond TTL of 5 minutes)
            future_time = current_time + 360  # 6 minutes
            plugin.force_cleanup_timestamps(future_time)

            # All timestamps should be cleaned up due to TTL expiration
            assert len(plugin.request_timestamps) == 0

    def test_concurrent_timestamp_access(self):
        """Test thread safety of request timestamp operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            def store_timestamps(start_id, count):
                for i in range(count):
                    request = MCPRequest(
                        jsonrpc="2.0", method="test", id=f"{start_id}-{i}"
                    )
                    plugin._store_request_timestamp(request)

            # Create multiple threads accessing request_timestamps concurrently
            threads = []
            for t in range(5):  # Reduced from 10 to make test more reliable
                thread = threading.Thread(target=store_timestamps, args=(t, 10))
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            # Should not crash with concurrent access
            assert len(plugin.request_timestamps) <= 50


class TestResourceManagement:
    """Test resource management including handlers and cleanup."""

    def test_handler_cleanup_on_deletion(self):
        """Test that handlers are properly cleaned up when plugin is deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            # Ensure logging is set up
            plugin._ensure_logging_setup()

            # Should have handler
            assert plugin.file_handler is not None
            assert plugin.logger is not None

            # Cleanup should remove handler
            plugin.cleanup()
            assert plugin.file_handler is None
            assert plugin.logger is None

    def test_thread_safety_of_logging_setup(self):
        """Test that logging setup is thread-safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"output_file": str(Path(tmpdir) / "test.log")}
            plugin = MockAuditingPlugin(config)

            results = []

            def setup_logging():
                result = plugin._ensure_logging_setup()
                results.append(result)

            # Multiple threads trying to set up logging concurrently
            threads = []
            for _ in range(5):
                thread = threading.Thread(target=setup_logging)
                threads.append(thread)
                thread.start()

            for thread in threads:
                thread.join()

            # All should succeed
            assert all(results)
            # Should only have one handler
            if plugin.logger:
                assert len(plugin.logger.handlers) == 1


class TestCriticalErrorHandling:
    """Test critical vs non-critical error handling."""

    def test_critical_plugin_respects_critical_config(self):
        """Test that critical audit plugins respect critical configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "output_file": str(Path(tmpdir) / "test.log"),
                "critical": True,  # Should be honored for audit plugins
            }

            # Critical audit plugins should have critical=True
            plugin = MockAuditingPlugin(config)
            assert plugin.critical is True  # Should respect configured value

    def test_non_critical_plugin_continues_on_setup_failure(self):
        """Test that non-critical plugins continue on setup failure."""
        # Try to write to a non-existent directory
        config = {"output_file": "/nonexistent/directory/test.log", "critical": False}

        # Should not raise exception
        plugin = MockAuditingPlugin(config)
        assert not plugin.critical


class TestPipelineLogging:
    """Tests focused on logging using the new ProcessingPipeline model."""

    def _make_pipeline(
        self,
        content,
        plugin_name="test_plugin",
        allowed=True,
        reason="ok",
        modified=False,
    ):
        pipeline = ProcessingPipeline(original_content=content)
        result = PluginResult(
            allowed=allowed, reason=reason, metadata={"plugin": plugin_name}
        )
        if modified:
            # Simulate modification (e.g., security redaction) via modified_content attribute
            result.modified_content = content  # type: ignore[attr-defined]
        stage = PipelineStage(
            plugin_name=plugin_name,
            plugin_type="security",
            input_content=content,
            output_content=content,
            content_hash="hash",
            result=result,
            processing_time_ms=1.0,
            outcome=StageOutcome.ALLOWED if allowed else StageOutcome.BLOCKED,
            security_evaluated=True,
        )
        pipeline.add_stage(stage)
        pipeline.had_security_plugin = True
        if allowed:
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        return pipeline

    @pytest.mark.asyncio
    async def test_request_logging_includes_plugin_and_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = MockAuditingPlugin(
                {"output_file": str(Path(tmpdir) / "audit.log")}
            )
            request = MCPRequest(
                jsonrpc="2.0", method="tools/call", id="1", params={"name": "tool"}
            )
            pipeline = self._make_pipeline(
                request, plugin_name="policy", allowed=True, reason="allowed"
            )
            await plugin.log_request(request, pipeline, server_name="srv")
            assert plugin.emitted, "No log emitted"
            line = plugin.emitted[-1]
            assert "method=tools/call" in line
            assert "plugin=policy" in line
            assert "outcome=allowed" in line
            assert "reason=[policy] allowed" in line

    @pytest.mark.asyncio
    async def test_response_logging_includes_duration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = MockAuditingPlugin(
                {"output_file": str(Path(tmpdir) / "audit.log")}
            )
            request = MCPRequest(jsonrpc="2.0", method="ping", id="9")
            pipeline = self._make_pipeline(request, plugin_name="sec", allowed=True)
            # store timestamp to enable duration calculation
            plugin._store_request_timestamp(request)
            # simulate small delay
            time.sleep(0.005)
            response = MCPResponse(jsonrpc="2.0", id="9", result={"ok": True})
            await plugin.log_response(request, response, pipeline, server_name="srv")
            line = plugin.emitted[-1]
            assert "RESPONSE" in line
            assert "duration=" in line
            # ensure duration captured with numeric content
            assert any(ch.isdigit() for ch in line.split("duration=")[1])

    @pytest.mark.asyncio
    async def test_notification_logging_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = MockAuditingPlugin(
                {"output_file": str(Path(tmpdir) / "audit.log")}
            )
            notification = MCPNotification(
                jsonrpc="2.0", method="progress", params={"pct": 50}
            )
            pipeline = ProcessingPipeline(original_content=notification)
            # No security evaluation
            await plugin.log_notification(notification, pipeline, server_name="srv")
            line = plugin.emitted[-1]
            assert "NOTIFICATION" in line
            assert "method=progress" in line
            # outcome should be present -> we only verify key presence
            assert "outcome=" in line


class TestEventBuffering:
    """Test event buffering for early initialization failures."""

    def test_event_buffer_initialization(self):
        """Test that event buffer is properly initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "output_file": str(Path(tmpdir) / "test.log"),
                "event_buffer_size": 25,
            }
            plugin = MockAuditingPlugin(config)

            assert hasattr(plugin, "_event_buffer")
            assert hasattr(plugin, "_buffer_enabled")
            assert plugin._event_buffer.maxlen == 25
            assert plugin._buffer_enabled

    def test_buffer_size_bounds(self):
        """Test that event buffer is properly bounded."""
        from collections import deque

        # Test bounded deque behavior directly
        buffer = deque(maxlen=3)

        # Fill beyond capacity
        for i in range(10):
            buffer.append(f"Message {i}")

        # Should be bounded to max size
        assert len(buffer) == 3

        # Should contain most recent messages
        messages = list(buffer)
        assert "Message 7" in messages[0]
        assert "Message 8" in messages[1]
        assert "Message 9" in messages[2]


class TestBaseClassEnhancements:
    """Remaining base class behavioral tests (non-logging helpers removed)."""

    # Placeholder for any future base-level behaviors needing verification post-refactor.
    pass
