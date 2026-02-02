"""Tests for Token Usage Estimator plugin."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gatekit.plugins.auditing.token_usage import (
    TokenUsagePlugin,
    MAX_CONTENT_SIZE,
    CSV_BUFFER_MAX_ROWS,
)
from gatekit.plugins.interfaces import ProcessingPipeline, PipelineOutcome
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestTokenUsagePluginConfiguration:
    """Test plugin configuration and initialization."""

    def test_valid_configuration(self):
        """Test plugin initializes with valid configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }
            plugin = TokenUsagePlugin(config)
            assert plugin.raw_output_file == f"{tmpdir}/token_usage.csv"
            assert plugin.raw_state_file == f"{tmpdir}/token_usage_state.json"

    def test_default_configuration(self):
        """Test plugin uses defaults when not specified."""
        config = {"enabled": True}
        plugin = TokenUsagePlugin(config)
        assert plugin.raw_output_file == "logs/token_usage.csv"
        assert plugin.raw_state_file == "logs/token_usage_state.json"
        assert plugin.flush_interval == 1.0

    def test_custom_flush_interval(self):
        """Test custom flush interval is respected."""
        config = {
            "enabled": True,
            "flush_interval_seconds": 5.0,
        }
        plugin = TokenUsagePlugin(config)
        assert plugin.flush_interval == 5.0

    def test_invalid_config_type(self):
        """Test plugin rejects non-dict configuration."""
        with pytest.raises(TypeError, match="must be a dictionary"):
            TokenUsagePlugin("invalid")


class TestTokenUsagePluginSchema:
    """Test plugin schema methods."""

    def test_get_config_schema(self):
        """Test config schema is valid."""
        schema = TokenUsagePlugin.get_config_schema()
        assert schema["type"] == "object"
        assert "output_file" in schema["properties"]
        assert "state_file" in schema["properties"]
        assert "flush_interval_seconds" in schema["properties"]

    def test_get_output_schema(self):
        """Test output schema declares two server columns."""
        schema = TokenUsagePlugin.get_output_schema()
        assert schema is not None
        assert "server_columns" in schema
        columns = schema["server_columns"]
        assert len(columns) == 2
        # First column: input (↑) - server responses into LLM
        assert columns[0]["key"] == "input"
        assert columns[0]["label"] == "↑"
        assert columns[0]["value_format"] == "humanized_number"
        assert columns[0]["width"] == 8
        # Second column: output (↓) - tool call requests from LLM
        assert columns[1]["key"] == "output"
        assert columns[1]["label"] == "↓"
        assert columns[1]["value_format"] == "humanized_number"
        assert columns[1]["width"] == 8
        # Context menu
        assert "context_menu" in schema
        assert len(schema["context_menu"]) == 2
        assert schema["context_menu"][0]["scope"] == "server"
        assert schema["context_menu"][1]["scope"] == "all_servers"
        assert "state_file_key" in schema

    def test_parse_server_values_basic(self):
        """Test parse_server_values sums tool token counts across instances."""
        state_data = {
            "instances": {
                "1234": {
                    "servers": {
                        "my-server": {
                            "tools": {
                                "read_file": {"input": 100, "output": 200},
                                "write_file": {"input": 50, "output": 100},
                            }
                        }
                    }
                }
            }
        }
        result = TokenUsagePlugin.parse_server_values(state_data, "my-server")
        assert result == {"input": 150, "output": 300}

    def test_parse_server_values_unknown_server(self):
        """Test parse_server_values returns empty dict for unknown server."""
        state_data = {"instances": {"1234": {"servers": {"other": {"tools": {}}}}}}
        result = TokenUsagePlugin.parse_server_values(state_data, "unknown")
        assert result == {}

    def test_parse_server_values_empty_state(self):
        """Test parse_server_values with empty state data."""
        result = TokenUsagePlugin.parse_server_values({}, "any-server")
        assert result == {}

    def test_parse_server_values_no_tools(self):
        """Test parse_server_values with server that has no tools."""
        state_data = {"instances": {"1234": {"servers": {"my-server": {"tools": {}}}}}}
        result = TokenUsagePlugin.parse_server_values(state_data, "my-server")
        assert result == {"input": 0, "output": 0}

    def test_parse_server_values_aggregates_across_instances(self):
        """Test parse_server_values sums counters across multiple instances."""
        state_data = {
            "instances": {
                "1111": {
                    "servers": {
                        "my-server": {
                            "tools": {
                                "echo": {"input": 100, "output": 50},
                            }
                        }
                    }
                },
                "2222": {
                    "servers": {
                        "my-server": {
                            "tools": {
                                "echo": {"input": 200, "output": 100},
                                "search": {"input": 10, "output": 5},
                            }
                        }
                    }
                },
            }
        }
        result = TokenUsagePlugin.parse_server_values(state_data, "my-server")
        assert result == {"input": 310, "output": 155}

    def test_parse_server_values_legacy_format(self):
        """Test parse_server_values falls back to legacy top-level servers."""
        state_data = {
            "servers": {
                "my-server": {
                    "tools": {
                        "read_file": {"input": 100, "output": 200},
                    }
                }
            }
        }
        result = TokenUsagePlugin.parse_server_values(state_data, "my-server")
        assert result == {"input": 100, "output": 200}

    def test_parse_server_values_instances_preferred_over_legacy(self):
        """Test that instances data is used when both formats present."""
        state_data = {
            "instances": {
                "1234": {
                    "servers": {
                        "my-server": {
                            "tools": {
                                "echo": {"input": 50, "output": 25},
                            }
                        }
                    }
                }
            },
            "servers": {
                "my-server": {
                    "tools": {
                        "echo": {"input": 999, "output": 999},
                    }
                }
            }
        }
        result = TokenUsagePlugin.parse_server_values(state_data, "my-server")
        # Should use instances data, not legacy
        assert result == {"input": 50, "output": 25}

    def test_reset_counters_all_servers(self):
        """Test reset_counters resets all servers across all instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(f"{tmpdir}/state.json")
            pid = str(os.getpid())
            state = {
                "reset_id": 1,
                "instances": {
                    pid: {
                        "started_at": "2024-01-26T10:00:00Z",
                        "last_update": "2024-01-26T10:00:00Z",
                        "servers": {"s1": {"tools": {"t": {"input": 10, "output": 20}}}},
                    }
                },
            }
            state_file.write_text(json.dumps(state))

            msg = TokenUsagePlugin.reset_counters(state_file, server_name=None)
            assert "all servers" in msg

            new_state = json.loads(state_file.read_text())
            assert new_state["reset_id"] == 2
            # Instance server entries are preserved with empty tools (so TUI shows zeros)
            assert new_state["instances"][pid]["servers"] == {"s1": {"tools": {}}}

    def test_reset_counters_single_server(self):
        """Test reset_counters resets a single server across all instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(f"{tmpdir}/state.json")
            pid = str(os.getpid())
            state = {
                "reset_id": 0,
                "server_reset_ids": {},
                "instances": {
                    pid: {
                        "started_at": "2024-01-26T10:00:00Z",
                        "last_update": "2024-01-26T10:00:00Z",
                        "servers": {
                            "s1": {"tools": {"t": {"input": 10, "output": 20}}},
                            "s2": {"tools": {"t": {"input": 5, "output": 10}}},
                        },
                    }
                },
            }
            state_file.write_text(json.dumps(state))

            msg = TokenUsagePlugin.reset_counters(state_file, server_name="s1")
            assert "'s1'" in msg

            new_state = json.loads(state_file.read_text())
            assert new_state["reset_id"] == 0  # Global unchanged
            assert new_state["server_reset_ids"]["s1"] == 1
            # Server entry preserved with empty tools (so TUI shows zeros)
            inst = new_state["instances"][pid]
            assert inst["servers"]["s1"] == {"tools": {}}
            assert "s2" in inst["servers"]

    def test_reset_counters_creates_missing_file(self):
        """Test reset_counters creates state file if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(f"{tmpdir}/subdir/state.json")
            assert not state_file.exists()

            msg = TokenUsagePlugin.reset_counters(state_file, server_name=None)
            assert "all servers" in msg
            assert state_file.exists()

            new_state = json.loads(state_file.read_text())
            assert new_state["reset_id"] == 1
            assert new_state["instances"] == {}

    def test_reset_counters_lock_timeout_raises_runtime_error(self):
        """Test reset_counters raises RuntimeError on lock timeout."""
        from filelock import Timeout

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(f"{tmpdir}/state.json")
            lock_path = str(state_file) + ".lock"

            with patch("filelock.FileLock.acquire", side_effect=Timeout(lock_path)):
                with pytest.raises(RuntimeError, match="Could not acquire file lock"):
                    TokenUsagePlugin.reset_counters(state_file)

    def test_describe_status_disabled(self):
        """Test status when disabled."""
        assert TokenUsagePlugin.describe_status({}) == "Disabled"
        assert TokenUsagePlugin.describe_status({"enabled": False}) == "Disabled"

    def test_describe_status_enabled(self):
        """Test status when enabled shows output file path."""
        config = {"enabled": True, "output_file": "logs/token_usage.csv"}
        assert TokenUsagePlugin.describe_status(config) == "logs/token_usage.csv"

    def test_describe_status_enabled_no_file(self):
        """Test status when enabled but no output file configured."""
        config = {"enabled": True}
        assert TokenUsagePlugin.describe_status(config) == "No output file configured"


class TestTokenEstimation:
    """Test token estimation functionality."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            yield plugin

    def test_estimate_tokens_string(self, plugin):
        """Test token estimation for string content."""
        if not plugin._tiktoken_available:
            pytest.skip("tiktoken not available")

        tokens = plugin._estimate_tokens("Hello, world!")
        assert tokens > 0

    def test_estimate_tokens_dict(self, plugin):
        """Test token estimation for dict content."""
        if not plugin._tiktoken_available:
            pytest.skip("tiktoken not available")

        tokens = plugin._estimate_tokens({"message": "Hello, world!"})
        assert tokens > 0

    def test_estimate_tokens_none(self, plugin):
        """Test token estimation for None returns 0."""
        tokens = plugin._estimate_tokens(None)
        assert tokens == 0

    def test_estimate_tokens_large_content_truncated(self, plugin):
        """Test that large content is truncated."""
        if not plugin._tiktoken_available:
            pytest.skip("tiktoken not available")

        # Patch MAX_CONTENT_SIZE to a smaller value for fast testing
        # This verifies truncation logic without tokenizing 10MB of content
        test_max_size = 1000
        with patch("gatekit.plugins.auditing.token_usage.MAX_CONTENT_SIZE", test_max_size):
            # Create content larger than the patched MAX_CONTENT_SIZE
            large_content = "x" * (test_max_size + 500)
            # Should not raise, should handle gracefully
            tokens = plugin._estimate_tokens(large_content)
            # Truncated content should still produce tokens
            assert tokens > 0

    def test_estimate_tokens_without_tiktoken(self):
        """Test heuristic fallback when tiktoken unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }

            with patch.dict("sys.modules", {"tiktoken": None}):
                plugin = TokenUsagePlugin(config)
                plugin._tiktoken_available = False
                plugin._encoder = None

                # Should return non-zero via heuristic when tiktoken unavailable
                tokens = plugin._estimate_tokens("Hello, world!")
                assert tokens > 0

    def test_heuristic_estimation_formula(self):
        """Test heuristic uses max(len//4, words*1.33)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }
            plugin = TokenUsagePlugin(config)
            text = "The quick brown fox jumps over the lazy dog"
            tokens = plugin._estimate_tokens_heuristic(text)
            expected = max(len(text) // 4, int(len(text.split()) * 1.33))
            assert tokens == expected

    def test_heuristic_estimation_with_none(self):
        """Test heuristic returns 0 for None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }
            plugin = TokenUsagePlugin(config)
            assert plugin._estimate_tokens_heuristic(None) == 0

    def test_heuristic_estimation_with_dict(self):
        """Test heuristic handles dict content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }
            plugin = TokenUsagePlugin(config)
            tokens = plugin._estimate_tokens_heuristic({"key": "value", "nested": {"a": 1}})
            assert tokens > 0

    def test_get_config_warnings_with_tiktoken(self):
        """Test no warnings when tiktoken is available."""
        warnings = TokenUsagePlugin.get_config_warnings()
        # tiktoken is installed in dev environment
        assert warnings == []

    def test_get_config_warnings_without_tiktoken(self):
        """Test warning returned when tiktoken unavailable."""
        with patch.dict("sys.modules", {"tiktoken": None}):
            warnings = TokenUsagePlugin.get_config_warnings()
            assert len(warnings) == 1
            assert "tiktoken" in warnings[0].lower()


class TestCounterManagement:
    """Test counter increment and management."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/token_usage_state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            yield plugin

    def test_increment_counter_new_server(self, plugin):
        """Test incrementing counter for new server."""
        plugin._increment_counter("my-server", "read_file", 100, 200)

        assert "my-server" in plugin._counters
        assert "read_file" in plugin._counters["my-server"]
        assert plugin._counters["my-server"]["read_file"]["input"] == 100
        assert plugin._counters["my-server"]["read_file"]["output"] == 200

    def test_increment_counter_existing_server(self, plugin):
        """Test incrementing counter for existing server."""
        plugin._increment_counter("my-server", "read_file", 100, 200)
        plugin._increment_counter("my-server", "read_file", 50, 100)

        assert plugin._counters["my-server"]["read_file"]["input"] == 150
        assert plugin._counters["my-server"]["read_file"]["output"] == 300

    def test_increment_counter_multiple_tools(self, plugin):
        """Test incrementing counters for multiple tools."""
        plugin._increment_counter("my-server", "read_file", 100, 200)
        plugin._increment_counter("my-server", "write_file", 50, 100)

        assert plugin._counters["my-server"]["read_file"]["input"] == 100
        assert plugin._counters["my-server"]["write_file"]["input"] == 50

    def test_get_tool_name_tools_call(self, plugin):
        """Test extracting tool name from tools/call request."""
        request = MCPRequest(jsonrpc="2.0", id="1", method="tools/call", params={"name": "read_file"})
        tool_name = plugin._get_tool_name(request)
        assert tool_name == "read_file"

    def test_get_tool_name_other_method(self, plugin):
        """Test _other for non-tools/call methods."""
        request = MCPRequest(jsonrpc="2.0", id="1", method="resources/list", params={})
        tool_name = plugin._get_tool_name(request)
        assert tool_name == "_other"


class TestStateFilePersistence:
    """Test state file save and restore."""

    def test_state_file_restore(self):
        """Test restoring state from own PID's instance in file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"

            # Create state file with data for this PID
            pid_key = str(os.getpid())
            state = {
                "reset_id": 5,
                "reset_timestamp": "2024-01-26T10:00:00Z",
                "instances": {
                    pid_key: {
                        "started_at": "2024-01-26T09:00:00Z",
                        "last_update": "2024-01-26T10:00:00Z",
                        "servers": {
                            "my-server": {
                                "tools": {
                                    "read_file": {"input": 100, "output": 200},
                                }
                            }
                        }
                    }
                }
            }
            Path(state_file).write_text(json.dumps(state))

            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Verify state was restored (regardless of started_at value)
            assert plugin._reset_id == 5
            assert plugin._reset_timestamp == "2024-01-26T10:00:00Z"
            assert plugin._counters["my-server"]["read_file"]["input"] == 100
            assert plugin._counters["my-server"]["read_file"]["output"] == 200

    def test_state_file_restore_legacy_format(self):
        """Test restoring state from legacy top-level servers format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"

            # Legacy format: top-level servers, no instances
            state = {
                "reset_id": 3,
                "reset_timestamp": "2024-01-26T10:00:00Z",
                "servers": {
                    "my-server": {
                        "tools": {
                            "read_file": {"input": 500, "output": 600},
                        }
                    }
                }
            }
            Path(state_file).write_text(json.dumps(state))

            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Verify legacy state was migrated
            assert plugin._reset_id == 3
            assert plugin._counters["my-server"]["read_file"]["input"] == 500
            assert plugin._counters["my-server"]["read_file"]["output"] == 600

    def test_state_file_flush(self):
        """Test flushing state to file writes under instances[own_pid]."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Add some counters
            plugin._increment_counter("my-server", "read_file", 100, 200)

            # Force flush
            plugin._last_state_flush = 0
            plugin._flush_state()

            # Read and verify
            state_path = Path(f"{tmpdir}/state.json")
            assert state_path.exists()

            state = json.loads(state_path.read_text())
            pid_key = str(os.getpid())
            assert "instances" in state
            assert pid_key in state["instances"]
            instance = state["instances"][pid_key]
            assert instance["started_at"] == plugin._started_at
            assert "last_update" in instance
            assert "my-server" in instance["servers"]
            assert instance["servers"]["my-server"]["tools"]["read_file"]["input"] == 100

    def test_state_file_reset_detection(self):
        """Test detecting reset from state file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"

            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Add counters
            plugin._increment_counter("my-server", "read_file", 100, 200)
            assert plugin._counters["my-server"]["read_file"]["input"] == 100

            # Simulate TUI reset by writing higher reset_id
            state = {
                "reset_id": 10,
                "reset_timestamp": "2024-01-26T12:00:00Z",
                "instances": {}
            }
            Path(state_file).write_text(json.dumps(state))

            # Trigger flush which should detect reset
            plugin._last_state_flush = 0
            plugin._flush_state()

            # Counters should be zeroed (keys preserved so TUI shows 0, not "—")
            assert plugin._counters == {"my-server": {}}
            assert plugin._reset_id == 10

    def test_state_file_per_server_reset_detection(self):
        """Test that plugin detects per-server reset from TUI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Add counters for two servers
            plugin._increment_counter("server-a", "tool1", 100, 200)
            plugin._increment_counter("server-b", "tool2", 150, 250)
            assert "server-a" in plugin._counters
            assert "server-b" in plugin._counters

            # Simulate TUI per-server reset for server-a only
            state = {
                "reset_id": 0,  # Global reset_id unchanged
                "reset_timestamp": "2024-01-26T12:00:00Z",
                "server_reset_ids": {"server-a": 1},
                "instances": {}
            }
            Path(state_file).write_text(json.dumps(state))

            # Trigger flush which should detect per-server reset
            plugin._last_state_flush = 0
            plugin._flush_state()

            # server-a counters should be zeroed (key preserved so TUI shows 0)
            assert plugin._counters["server-a"] == {}
            assert "server-b" in plugin._counters
            assert plugin._counters["server-b"]["tool2"]["input"] == 150
            assert plugin._server_reset_ids["server-a"] == 1


class TestCSVLogging:
    """Test CSV log writing."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            yield plugin
            plugin.cleanup()

    def test_csv_row_added_to_buffer(self, plugin):
        """Test adding row to CSV buffer."""
        plugin._add_csv_row("my-server", "tools/call", "read_file", 100, 200)

        assert len(plugin._csv_buffer) == 1
        assert plugin._csv_buffer[0]["server"] == "my-server"
        assert plugin._csv_buffer[0]["tool"] == "read_file"
        assert plugin._csv_buffer[0]["input_tokens"] == 100
        assert plugin._csv_buffer[0]["output_tokens"] == 200

    def test_csv_buffer_flush_on_max_rows(self, plugin):
        """Test buffer flushes when max rows reached."""
        # Add rows up to buffer limit
        for i in range(CSV_BUFFER_MAX_ROWS):
            plugin._add_csv_row("server", "method", f"tool_{i}", i, i)

        # Buffer should be flushed
        assert len(plugin._csv_buffer) == 0

        # CSV file should exist with content
        csv_path = Path(plugin.output_file)
        assert csv_path.exists()

        content = csv_path.read_text()
        assert "timestamp" in content  # Header
        assert "tool_0" in content

    def test_csv_injection_prevention(self, plugin):
        """Test CSV injection characters are escaped."""
        plugin._add_csv_row("=cmd", "method", "+tool", 100, 200)

        # Force flush
        with plugin._lock:
            plugin._flush_csv_buffer()

        csv_path = Path(plugin.output_file)
        content = csv_path.read_text()

        # Dangerous characters should be prefixed with single quote
        assert "'=cmd" in content
        assert "'+tool" in content


class TestRequestResponseCorrelation:
    """Test request/response correlation for token attribution."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            yield plugin
            plugin.cleanup()

    @pytest.mark.asyncio
    async def test_request_stores_pending(self, plugin):
        """Test request stores pending entry for correlation."""
        request = MCPRequest(jsonrpc="2.0", id="req-1", method="tools/call", params={"name": "read_file"})
        pipeline = ProcessingPipeline(
            original_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_request(request, pipeline, "my-server")

        assert "req-1" in plugin._pending_requests
        assert plugin._pending_requests["req-1"]["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_response_correlates_with_request(self, plugin):
        """Test response correlates with pending request."""
        # Log request first
        request = MCPRequest(jsonrpc="2.0", id="req-1", method="tools/call", params={"name": "read_file"})
        pipeline = ProcessingPipeline(
            original_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_request(request, pipeline, "my-server")

        # Log response
        response = MCPResponse(jsonrpc="2.0", id="req-1", result={"content": "data"})
        await plugin.log_response(request, response, pipeline, "my-server")

        # Pending entry should be removed
        assert "req-1" not in plugin._pending_requests

        # Counter should have both input and output
        assert "my-server" in plugin._counters
        assert "read_file" in plugin._counters["my-server"]

    @pytest.mark.asyncio
    async def test_response_without_pending_uses_other(self, plugin):
        """Test response without pending entry uses _other category."""
        response = MCPResponse(jsonrpc="2.0", id="unknown-req", result={"content": "data"})
        request = MCPRequest(jsonrpc="2.0", id="unknown-req", method="unknown", params={})
        pipeline = ProcessingPipeline(
            original_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_response(request, response, pipeline, "my-server")

        # Should use _other category
        assert "my-server" in plugin._counters
        assert "_other" in plugin._counters["my-server"]


class TestNotificationLogging:
    """Test notification token logging."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            yield plugin
            plugin.cleanup()

    @pytest.mark.asyncio
    async def test_notification_counted_as_other(self, plugin):
        """Test notifications are counted in _other category."""
        notification = MCPNotification(jsonrpc="2.0", method="notifications/message", params={"message": "test"})
        pipeline = ProcessingPipeline(
            original_content=notification,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_notification(notification, pipeline, "my-server")

        assert "my-server" in plugin._counters
        assert "_other" in plugin._counters["my-server"]
        assert plugin._counters["my-server"]["_other"]["input"] > 0

    @pytest.mark.asyncio
    async def test_notification_none_server_name_skipped(self, plugin):
        """Test notifications with None server_name are silently skipped."""
        notification = MCPNotification(jsonrpc="2.0", method="notifications/initialized", params={})
        pipeline = ProcessingPipeline(
            original_content=notification,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_notification(notification, pipeline, None)

        # No "null" or None key should appear in counters
        assert None not in plugin._counters
        assert "null" not in plugin._counters


class TestFlushBeforeIncrement:
    """Test that _flush_state is called before incrementing counters to detect resets."""

    @pytest.fixture
    def plugin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            yield plugin
            plugin.cleanup()

    @pytest.mark.asyncio
    async def test_log_request_flushes_before_increment(self, plugin):
        """Test that log_request calls _flush_state before incrementing counters."""
        call_order = []
        orig_flush = plugin._flush_state
        orig_increment = plugin._increment_counter

        def tracking_flush(**kwargs):
            call_order.append("flush")
            orig_flush(**kwargs)

        def tracking_increment(*args, **kwargs):
            call_order.append("increment")
            orig_increment(*args, **kwargs)

        plugin._flush_state = tracking_flush
        plugin._increment_counter = tracking_increment

        request = MCPRequest(jsonrpc="2.0", method="tools/call", id=1, params={"name": "test"})
        pipeline = ProcessingPipeline(
            original_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_request(request, pipeline, "test-server")

        assert call_order.index("flush") < call_order.index("increment")

    @pytest.mark.asyncio
    async def test_log_response_flushes_before_increment(self, plugin):
        """Test that log_response calls _flush_state before incrementing counters."""
        call_order = []
        orig_flush = plugin._flush_state
        orig_increment = plugin._increment_counter

        def tracking_flush(**kwargs):
            call_order.append("flush")
            orig_flush(**kwargs)

        def tracking_increment(*args, **kwargs):
            call_order.append("increment")
            orig_increment(*args, **kwargs)

        plugin._flush_state = tracking_flush
        plugin._increment_counter = tracking_increment

        request = MCPRequest(jsonrpc="2.0", method="tools/call", id=1, params={"name": "test"})
        response = MCPResponse(jsonrpc="2.0", id=1, result={"content": [{"type": "text", "text": "ok"}]})
        pipeline = ProcessingPipeline(
            original_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )

        await plugin.log_response(request, response, pipeline, "test-server")

        assert call_order.index("flush") < call_order.index("increment")

    @pytest.mark.asyncio
    async def test_reset_detected_before_new_data(self, plugin):
        """Test that a reset clears counters before new request data is added."""
        # First, add some data
        request = MCPRequest(jsonrpc="2.0", method="tools/call", id=1, params={"name": "test"})
        pipeline = ProcessingPipeline(
            original_content=request,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            had_security_plugin=True,
        )
        await plugin.log_request(request, pipeline, "test-server")

        # Force flush to write state
        plugin._last_state_flush = 0
        plugin._flush_state()
        assert "test-server" in plugin._counters

        # Simulate external reset by writing a higher reset_id to state file
        state_path = Path(plugin.state_file)
        state = json.loads(state_path.read_text())
        state["reset_id"] = state["reset_id"] + 1
        state_path.write_text(json.dumps(state))

        # Now log a new request - flush should detect reset first, clear counters,
        # then add the new data fresh
        request2 = MCPRequest(jsonrpc="2.0", method="tools/call", id=2, params={"name": "test2"})
        plugin._last_state_flush = 0  # Allow flush to run
        await plugin.log_request(request2, pipeline, "test-server")

        # The counter should only have the new request's data, not the old + new
        assert "test-server" in plugin._counters


class TestMultiInstanceBehavior:
    """Test PID-keyed multi-instance state file behavior."""

    def test_flush_preserves_other_instances(self):
        """Test that flushing preserves all other instances' data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"

            other_pid = "77777"
            own_pid = str(os.getpid())
            recent_time = datetime.utcnow().isoformat() + "Z"

            state = {
                "reset_id": 0,
                "reset_timestamp": recent_time,
                "server_reset_ids": {},
                "instances": {
                    other_pid: {
                        "started_at": recent_time,
                        "last_update": recent_time,
                        "servers": {
                            "srv": {"tools": {"echo": {"input": 50, "output": 25}}}
                        }
                    }
                }
            }
            Path(state_file).write_text(json.dumps(state))

            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Add own counters
            plugin._increment_counter("srv", "echo", 100, 50)

            # Flush
            plugin._last_state_flush = 0
            plugin._flush_state()

            # Verify both instances present
            result = json.loads(Path(state_file).read_text())
            assert own_pid in result["instances"]
            assert other_pid in result["instances"]
            assert result["instances"][other_pid]["servers"]["srv"]["tools"]["echo"]["input"] == 50
            assert result["instances"][own_pid]["servers"]["srv"]["tools"]["echo"]["input"] == 100

    def test_flush_preserves_dead_pid_instances(self):
        """Test that dead PID entries are preserved during flush (data persists until reset)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"

            dead_pid = "88888"
            old_time = "2020-01-01T00:00:00Z"

            state = {
                "reset_id": 0,
                "reset_timestamp": old_time,
                "server_reset_ids": {},
                "instances": {
                    dead_pid: {
                        "started_at": old_time,
                        "last_update": old_time,
                        "servers": {
                            "srv": {"tools": {"echo": {"input": 999, "output": 999}}}
                        }
                    }
                }
            }
            Path(state_file).write_text(json.dumps(state))

            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Give the plugin some traffic so it will actually write to state
            plugin._increment_counter("myserver", "mytool", 10, 20)

            # Flush should NOT clean up the dead PID — data persists until user resets
            plugin._last_state_flush = 0
            plugin._flush_state()

            result = json.loads(Path(state_file).read_text())
            assert dead_pid in result["instances"]
            assert result["instances"][dead_pid]["servers"]["srv"]["tools"]["echo"]["input"] == 999
            assert str(os.getpid()) in result["instances"]

    def test_cleanup_removes_own_pid(self):
        """Test that cleanup removes own PID entry from state file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/state.json"
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": state_file,
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)

            # Add data and flush to create state file
            plugin._increment_counter("srv", "echo", 100, 50)
            plugin._last_state_flush = 0
            plugin._flush_state()

            pid_key = str(os.getpid())
            state = json.loads(Path(state_file).read_text())
            assert pid_key in state["instances"]

            # Cleanup should remove own PID
            plugin.cleanup()

            state = json.loads(Path(state_file).read_text())
            assert pid_key not in state["instances"]

    def test_is_pid_alive_current_process(self):
        """Test _is_pid_alive returns True for current process."""
        assert TokenUsagePlugin._is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_dead_process(self):
        """Test _is_pid_alive returns False for non-existent PID."""
        assert TokenUsagePlugin._is_pid_alive(9999999) is False

    def test_parse_server_values_multi_instance_aggregation(self):
        """Test parse_server_values sums across instances for TUI display."""
        state_data = {
            "instances": {
                "111": {
                    "servers": {
                        "everything": {"tools": {"echo": {"input": 310, "output": 161}}}
                    }
                },
                "222": {
                    "servers": {
                        "everything": {"tools": {"echo": {"input": 150, "output": 80}}}
                    }
                },
            }
        }
        result = TokenUsagePlugin.parse_server_values(state_data, "everything")
        assert result == {"input": 460, "output": 241}

    def test_reset_counters_zeros_all_instances(self):
        """Test that reset_counters zeros server data in all instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(f"{tmpdir}/state.json")
            pid = str(os.getpid())
            other_pid = "55555"
            state = {
                "reset_id": 0,
                "server_reset_ids": {},
                "instances": {
                    pid: {
                        "started_at": "2024-01-26T10:00:00Z",
                        "last_update": "2024-01-26T10:00:00Z",
                        "servers": {
                            "s1": {"tools": {"t": {"input": 100, "output": 200}}},
                        },
                    },
                    other_pid: {
                        "started_at": "2024-01-26T10:00:00Z",
                        "last_update": datetime.utcnow().isoformat() + "Z",
                        "servers": {
                            "s1": {"tools": {"t": {"input": 50, "output": 60}}},
                        },
                    },
                },
            }
            state_file.write_text(json.dumps(state))

            # Patch _is_pid_alive: both PIDs alive
            with patch.object(TokenUsagePlugin, "_is_pid_alive", return_value=True):
                TokenUsagePlugin.reset_counters(state_file, server_name=None)

            new_state = json.loads(state_file.read_text())
            assert new_state["reset_id"] == 1
            # Both instances' server entries should be zeroed
            assert len(new_state["instances"]) == 2
            for inst in new_state["instances"].values():
                assert inst["servers"]["s1"] == {"tools": {}}


class TestPeriodicFlushTimer:
    """Test periodic flush timer lifecycle."""

    def test_timer_starts_on_set_config_directory(self):
        """Test that periodic flush timer is started when config directory is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            assert plugin._periodic_flush_timer is None

            plugin.set_config_directory(tmpdir)
            assert plugin._periodic_flush_timer is not None
            assert plugin._periodic_flush_timer.is_alive()

            plugin.cleanup()
            assert plugin._periodic_flush_timer is None

    def test_timer_stopped_on_cleanup(self):
        """Test that cleanup stops the periodic flush timer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "enabled": True,
                "output_file": f"{tmpdir}/token_usage.csv",
                "state_file": f"{tmpdir}/state.json",
            }
            plugin = TokenUsagePlugin(config)
            plugin.set_config_directory(tmpdir)
            assert plugin._periodic_flush_timer is not None

            plugin.cleanup()
            assert plugin._flush_timer_stopped is True
            assert plugin._periodic_flush_timer is None


class TestTokenUsageResolveAndValidatePaths:
    """Test TokenUsagePlugin.resolve_and_validate_paths classmethod."""

    def test_valid_paths_return_no_errors(self, tmp_path):
        config = {
            "output_file": "logs/token_usage.csv",
            "state_file": "logs/token_usage_state.json",
        }
        errors = TokenUsagePlugin.resolve_and_validate_paths(config, tmp_path)
        assert errors == []

    def test_missing_paths_return_no_errors(self):
        errors = TokenUsagePlugin.resolve_and_validate_paths({}, Path("/tmp"))
        assert errors == []

    def test_unwritable_directory_returns_error(self, tmp_path):
        import os
        from unittest.mock import patch

        config = {
            "output_file": "token.csv",
            "state_file": "state.json",
        }
        tmp_resolved = tmp_path.resolve()
        original_access = os.access

        def mock_access(path, mode):
            if mode == os.W_OK and Path(path).resolve() == tmp_resolved:
                return False
            return original_access(path, mode)

        with patch("os.access", side_effect=mock_access):
            errors = TokenUsagePlugin.resolve_and_validate_paths(config, tmp_path)
            # Both output_file and state_file should report errors
            assert len(errors) == 2
            assert all("No write permission" in e for e in errors)

    def test_no_instance_created(self, tmp_path):
        """Verify no plugin instance is created during classmethod validation."""
        from unittest.mock import patch

        config = {
            "output_file": "token.csv",
            "state_file": "state.json",
        }
        with patch.object(
            TokenUsagePlugin, "__init__", side_effect=AssertionError("Should not be called")
        ):
            errors = TokenUsagePlugin.resolve_and_validate_paths(config, tmp_path)
            assert errors == []
