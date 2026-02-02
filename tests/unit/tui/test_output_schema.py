"""Tests for output schema discovery and data reading utilities."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gatekit.tui.utils.output_schema import (
    humanize_number,
    ServerColumnDefinition,
    OutputSchemaDiscovery,
    ServerColumnReader,
    VALUE_FORMATTERS,
)
from gatekit.plugins.interfaces import PluginInterface


class TestHumanizeNumber:
    """Test humanize_number formatter."""

    def test_small_numbers(self):
        """Numbers under 1000 should be displayed as-is."""
        assert humanize_number(0) == "0"
        assert humanize_number(1) == "1"
        assert humanize_number(999) == "999"

    def test_thousands(self):
        """Numbers in thousands should use K suffix."""
        assert humanize_number(1000) == "1K"
        assert humanize_number(1500) == "1.5K"
        assert humanize_number(10000) == "10K"
        assert humanize_number(999999) == "1000K"  # Still K, not yet M

    def test_millions(self):
        """Numbers in millions should use M suffix."""
        assert humanize_number(1_000_000) == "1M"
        assert humanize_number(1_500_000) == "1.5M"
        assert humanize_number(10_000_000) == "10M"

    def test_billions(self):
        """Numbers in billions should use G suffix."""
        assert humanize_number(1_000_000_000) == "1G"
        assert humanize_number(1_500_000_000) == "1.5G"

    def test_negative_numbers(self):
        """Negative numbers should have minus prefix."""
        assert humanize_number(-100) == "-100"
        assert humanize_number(-1500) == "-1.5K"

    def test_trailing_zeros_stripped(self):
        """Trailing zeros after decimal should be stripped."""
        assert humanize_number(2000) == "2K"  # Not "2.0K"
        assert humanize_number(2_000_000) == "2M"  # Not "2.0M"


class TestServerColumnDefinition:
    """Test ServerColumnDefinition class."""

    def test_basic_initialization(self):
        """Test basic column definition creation."""
        column = ServerColumnDefinition(
            handler_name="test_plugin",
            plugin_class=PluginInterface,
            key="output",
            column_id="test_plugin__output",
            value_format="humanized_number",
        )
        assert column.handler_name == "test_plugin"
        assert column.key == "output"
        assert column.column_id == "test_plugin__output"
        assert column.value_format == "humanized_number"
        assert column.state_file_key == "state_file"
        assert column.label == ""
        assert column.tooltip is None
        assert column.width == 7
        assert column.context_menu == []

    def test_custom_state_file_key(self):
        """Test custom state file key."""
        column = ServerColumnDefinition(
            handler_name="test_plugin",
            plugin_class=PluginInterface,
            key="count",
            column_id="test_plugin__count",
            state_file_key="custom_state",
        )
        assert column.state_file_key == "custom_state"

    def test_format_value_humanized(self):
        """Test single-value formatting with humanized numbers."""
        column = ServerColumnDefinition(
            handler_name="test_plugin",
            plugin_class=PluginInterface,
            key="output",
            column_id="test_plugin__output",
            value_format="humanized_number",
        )
        assert column.format_value(3400) == "3.4K"
        assert column.format_value(0) == "0"
        assert column.format_value(999) == "999"

    def test_format_value_raw(self):
        """Test single-value formatting with raw numbers."""
        column = ServerColumnDefinition(
            handler_name="test_plugin",
            plugin_class=PluginInterface,
            key="count",
            column_id="test_plugin__count",
            value_format="raw",
        )
        assert column.format_value(200) == "200"
        assert column.format_value(0) == "0"

    def test_full_initialization_with_all_fields(self):
        """Test column definition with all optional fields."""
        menu = [{"label": "Reset", "method": "reset_counters"}]
        column = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=PluginInterface,
            key="input",
            column_id="token_usage__input",
            value_format="humanized_number",
            label="↓",
            tooltip="Tokens out of LLM",
            width=8,
            context_menu=menu,
            state_file_key="state_file",
        )
        assert column.label == "↓"
        assert column.tooltip == "Tokens out of LLM"
        assert column.width == 8
        assert column.context_menu == menu

    def test_column_id_format(self):
        """Test column_id uses double underscore separator."""
        column = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=PluginInterface,
            key="input",
            column_id="token_usage__input",
        )
        assert column.column_id == "token_usage__input"
        assert "__" in column.column_id


class TestOutputSchemaDiscovery:
    """Test OutputSchemaDiscovery class."""

    def test_discover_finds_token_usage_columns(self):
        """Token usage plugin should have two server columns."""
        columns = OutputSchemaDiscovery.discover_server_columns()
        assert isinstance(columns, list)
        # Should find two columns from token_usage plugin
        token_columns = [c for c in columns if c.handler_name == "token_usage"]
        assert len(token_columns) == 2

    def test_discovered_columns_have_correct_ids(self):
        """Token usage columns should have correct column_id values."""
        columns = OutputSchemaDiscovery.discover_server_columns()
        column_ids = [c.column_id for c in columns if c.handler_name == "token_usage"]
        assert "token_usage__output" in column_ids
        assert "token_usage__input" in column_ids

    def test_discovered_token_usage_has_correct_config(self):
        """Token usage columns should have correct configuration."""
        columns = OutputSchemaDiscovery.discover_server_columns()
        token_columns = {c.key: c for c in columns if c.handler_name == "token_usage"}

        input_col = token_columns["input"]
        assert input_col.label == "↑"
        assert input_col.value_format == "humanized_number"
        assert input_col.tooltip == "Input tokens (server responses into LLM)"
        assert input_col.width == 8

        output_col = token_columns["output"]
        assert output_col.label == "↓"
        assert output_col.value_format == "humanized_number"
        assert output_col.tooltip == "Output tokens (tool call requests from LLM)"
        assert output_col.width == 8

    def test_discovered_columns_share_context_menu(self):
        """Both token usage columns should share the same context menu."""
        columns = OutputSchemaDiscovery.discover_server_columns()
        token_columns = [c for c in columns if c.handler_name == "token_usage"]
        assert len(token_columns) == 2
        assert token_columns[0].context_menu == token_columns[1].context_menu
        assert len(token_columns[0].context_menu) == 2

    def test_discovered_context_menu_has_explicit_scope(self):
        """Token usage context menu entries should have explicit scope fields."""
        columns = OutputSchemaDiscovery.discover_server_columns()
        token_columns = [c for c in columns if c.handler_name == "token_usage"]
        assert len(token_columns) >= 1
        menu = token_columns[0].context_menu
        # First entry: per-server reset
        assert menu[0]["scope"] == "server"
        # Second entry: all-servers reset
        assert menu[1]["scope"] == "all_servers"


class TestServerColumnReader:
    """Test ServerColumnReader class."""

    @pytest.fixture
    def columns(self):
        """Create test column definitions with a mock plugin class."""
        mock_plugin = MagicMock()
        mock_plugin.get_config_schema.return_value = {
            "properties": {
                "state_file": {"default": "logs/token_usage_state.json"}
            }
        }

        def parse_server_values(state_data, server_name):
            total_input = 0
            total_output = 0
            found = False
            instances = state_data.get("instances", {})
            for instance_data in instances.values():
                servers = instance_data.get("servers", {})
                server_data = servers.get(server_name, {})
                if server_data is not None:
                    tools = server_data.get("tools", {})
                    if tools or server_name in servers:
                        found = True
                    total_input += sum(t.get("input", 0) for t in tools.values())
                    total_output += sum(t.get("output", 0) for t in tools.values())
            if not found:
                return {}
            return {"input": total_input, "output": total_output}

        mock_plugin.parse_server_values = parse_server_values

        output_col = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=mock_plugin,
            key="output",
            column_id="token_usage__output",
            value_format="humanized_number",
            label="↑",
        )
        input_col = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=mock_plugin,
            key="input",
            column_id="token_usage__input",
            value_format="humanized_number",
            label="↓",
        )
        return [output_col, input_col]

    @pytest.fixture
    def state_data(self):
        """Sample state file data using PID-keyed instances format."""
        return {
            "reset_id": 1,
            "reset_timestamp": "2024-01-26T10:00:00Z",
            "instances": {
                "12345": {
                    "started_at": "2024-01-26T10:00:00Z",
                    "last_update": "2024-01-26T10:05:00Z",
                    "servers": {
                        "my-server": {
                            "tools": {
                                "read_file": {"input": 150, "output": 320},
                                "write_file": {"input": 80, "output": 200},
                                "_other": {"input": 20, "output": 150},
                            }
                        },
                        "other-server": {
                            "tools": {
                                "search": {"input": 100, "output": 200}
                            }
                        }
                    }
                }
            }
        }

    @pytest.fixture
    def mock_config(self):
        """Create a mock config with upstreams."""
        config = MagicMock()
        upstream1 = MagicMock()
        upstream1.name = "my-server"
        upstream2 = MagicMock()
        upstream2.name = "other-server"
        config.upstreams = [upstream1, upstream2]
        config.plugins = None
        return config

    def test_read_column_values(self, columns, state_data, mock_config):
        """Test reading column values for all servers."""
        # Set up plugin config so _get_plugin_config can find the handler
        plugin = MagicMock()
        plugin.handler = "token_usage"
        plugin.enabled = True
        plugin.config = {}
        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {"_global": [plugin]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "logs" / "token_usage_state.json"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state_data))

            reader = ServerColumnReader(
                columns=columns,
                config=mock_config,
                config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("token_usage")

            # my-server: 150+80+20=250 input, 320+200+150=670 output
            assert "my-server" in values
            assert values["my-server"]["input"] == 250
            assert values["my-server"]["output"] == 670

            # other-server: 100 input, 200 output
            assert "other-server" in values
            assert values["other-server"]["input"] == 100
            assert values["other-server"]["output"] == 200

    def test_read_column_values_file_not_found(self, columns, mock_config):
        """Test reading column values when state file doesn't exist."""
        plugin = MagicMock()
        plugin.handler = "token_usage"
        plugin.enabled = True
        plugin.config = {}
        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {"_global": [plugin]}

        with tempfile.TemporaryDirectory() as tmpdir:
            reader = ServerColumnReader(
                columns=columns,
                config=mock_config,
                config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("token_usage")
            # Each server should get None when file not found (not configured/available)
            assert values == {"my-server": None, "other-server": None}

    def test_read_column_values_invalid_json(self, columns, mock_config):
        """Test reading column values with invalid JSON file."""
        plugin = MagicMock()
        plugin.handler = "token_usage"
        plugin.enabled = True
        plugin.config = {}
        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {"_global": [plugin]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "logs" / "token_usage_state.json"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text("not valid json")

            reader = ServerColumnReader(
                columns=columns,
                config=mock_config,
                config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("token_usage")
            # Each server should get None on parse error (state unavailable)
            assert values == {"my-server": None, "other-server": None}

    def test_column_id_property(self, columns, mock_config):
        """Test column_id property returns first column's column_id."""
        reader = ServerColumnReader(
            columns=columns,
            config=mock_config,
            config_directory=Path("/tmp"),
        )
        assert reader.column_id == "token_usage__output"

    def test_columns_by_handler_grouping(self, columns, mock_config):
        """Test columns are grouped by handler name."""
        reader = ServerColumnReader(
            columns=columns,
            config=mock_config,
            config_directory=Path("/tmp"),
        )
        assert "token_usage" in reader._columns_by_handler
        assert len(reader._columns_by_handler["token_usage"]) == 2

    def test_columns_by_id_lookup(self, columns, mock_config):
        """Test columns can be looked up by column_id."""
        reader = ServerColumnReader(
            columns=columns,
            config=mock_config,
            config_directory=Path("/tmp"),
        )
        assert "token_usage__output" in reader._columns_by_id
        assert "token_usage__input" in reader._columns_by_id

    def test_parse_server_values_unknown_server(self, columns, state_data, mock_config):
        """Test parse_server_values returns empty dict for unknown server."""
        plugin = MagicMock()
        plugin.handler = "token_usage"
        plugin.enabled = True
        plugin.config = {}
        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {"_global": [plugin]}

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "logs" / "token_usage_state.json"
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(json.dumps(state_data))

            reader = ServerColumnReader(
                columns=columns,
                config=mock_config,
                config_directory=Path(tmpdir),
            )

            # Add unknown server to config
            unknown = MagicMock()
            unknown.name = "unknown-server"
            mock_config.upstreams.append(unknown)

            values = reader.read_column_values("token_usage")
            # unknown-server should return empty dict (no data)
            assert values.get("unknown-server", {}) == {}

    def test_get_plugin_config_searches_all_categories(self, columns, mock_config):
        """Test _get_plugin_config searches security, middleware, and auditing."""
        plugin = MagicMock()
        plugin.handler = "token_usage"
        plugin.enabled = True
        plugin.config = {"enabled": True, "state_file": "custom.json"}

        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {
            "_global": [plugin]
        }

        reader = ServerColumnReader(
            columns=columns,
            config=mock_config,
            config_directory=Path("/tmp"),
        )
        config = reader._get_plugin_config("token_usage")
        assert config is not None
        assert config["state_file"] == "custom.json"


class TestDiscoveryValidation:
    """Test schema validation in OutputSchemaDiscovery.discover_server_columns."""

    def _make_plugin_with_schema(self, schema):
        """Create a mock plugin class with the given output schema."""
        mock_plugin = MagicMock()
        mock_plugin.get_output_schema.return_value = schema
        return mock_plugin

    def test_handler_name_with_separator_skipped(self):
        """Handler names containing __ should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "count", "value_format": "raw"}],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"bad__handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        bad = [c for c in columns if c.handler_name == "bad__handler"]
        assert len(bad) == 0

    def test_column_key_with_separator_skipped(self):
        """Column keys containing __ should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "bad__key", "value_format": "raw"}],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"good_handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        bad = [c for c in columns if c.key == "bad__key"]
        assert len(bad) == 0

    def test_duplicate_column_ids_filtered(self):
        """Duplicate column_id values should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [
                {"key": "count", "value_format": "raw"},
                {"key": "count", "value_format": "raw"},  # duplicate
            ],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1

    def test_width_clamped_below_minimum(self):
        """Width below 3 should be clamped to 3."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw", "width": 1}],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        assert matching[0].width == 3

    def test_width_clamped_above_maximum(self):
        """Width above 20 should be clamped to 20."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw", "width": 50}],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        assert matching[0].width == 20

    def test_non_integer_width_defaults(self):
        """Non-integer width should default to 7."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw", "width": "wide"}],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        assert matching[0].width == 7

    def test_invalid_value_format_falls_back_to_str(self):
        """Unrecognized value_format should fall back to str."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "nonexistent_format"}],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        assert matching[0].format_value(42) == "42"  # str fallback

    def test_context_menu_invalid_method_name_skipped(self):
        """Context menu entries with invalid method names should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw"}],
            "context_menu": [
                {"label": "Good", "method": "do_thing"},
                {"label": "Bad", "method": "123invalid"},
                {"label": "Private", "method": "_private_method"},
                {"label": "Spaces", "method": "not valid"},
            ],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        # Only the "Good" entry should survive validation
        assert len(matching[0].context_menu) == 1
        assert matching[0].context_menu[0]["method"] == "do_thing"

    def test_context_menu_missing_label_skipped(self):
        """Context menu entries without labels should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw"}],
            "context_menu": [
                {"label": "", "method": "do_thing"},
                {"label": "Valid", "method": "do_other"},
            ],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        assert len(matching[0].context_menu) == 1
        assert matching[0].context_menu[0]["label"] == "Valid"

    def test_context_menu_invalid_scope_skipped(self):
        """Context menu entries with invalid scope values should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw"}],
            "context_menu": [
                {"label": "Good Server", "method": "do_thing", "scope": "server"},
                {"label": "Good All", "method": "do_all", "scope": "all_servers"},
                {"label": "Bad Scope", "method": "do_bad", "scope": "invalid_scope"},
            ],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        # Only the two valid scope entries should survive
        assert len(matching[0].context_menu) == 2
        methods = [e["method"] for e in matching[0].context_menu]
        assert "do_thing" in methods
        assert "do_all" in methods
        assert "do_bad" not in methods

    def test_context_menu_scope_defaults_to_server(self):
        """Context menu entries without scope should default to 'server'."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [{"key": "x", "value_format": "raw"}],
            "context_menu": [
                {"label": "No Scope", "method": "do_thing"},
            ],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        # Entry without scope should pass validation (defaults to "server")
        assert len(matching[0].context_menu) == 1
        # The entry should not have scope injected - it's read at use time
        assert matching[0].context_menu[0]["method"] == "do_thing"

    def test_missing_required_fields_skipped(self):
        """Columns missing key or value_format should be skipped."""
        from gatekit.plugins.manager import PluginManager

        mock_plugin = self._make_plugin_with_schema({
            "server_columns": [
                {"key": "good", "value_format": "raw"},
                {"key": "no_format"},  # missing value_format
                {"value_format": "raw"},  # missing key
            ],
        })

        with patch.object(
            PluginManager, "_discover_handlers",
            return_value={"handler": mock_plugin},
        ):
            columns = OutputSchemaDiscovery.discover_server_columns()

        matching = [c for c in columns if c.handler_name == "handler"]
        assert len(matching) == 1
        assert matching[0].key == "good"


class TestReaderErrorHandling:
    """Test ServerColumnReader error handling for parse_server_values."""

    @pytest.fixture
    def mock_config(self):
        config = MagicMock()
        upstream = MagicMock()
        upstream.name = "server-a"
        config.upstreams = [upstream]
        config.plugins = None
        return config

    def _add_plugin_config(self, mock_config, handler_name):
        """Add a global PluginConfig entry so _get_plugin_config finds it."""
        p = MagicMock()
        p.handler = handler_name
        p.enabled = True
        p.config = {}
        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {"_global": [p]}

    def test_parse_server_values_returns_non_dict(self, mock_config):
        """Non-dict return from parse_server_values should be treated as empty."""
        mock_plugin = MagicMock()
        mock_plugin.get_config_schema.return_value = {
            "properties": {"state_file": {"default": "state.json"}}
        }
        mock_plugin.parse_server_values.return_value = "not a dict"

        col = ServerColumnDefinition(
            handler_name="broken",
            plugin_class=mock_plugin,
            key="x",
            column_id="broken__x",
        )

        self._add_plugin_config(mock_config, "broken")

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state_file.write_text(json.dumps({"instances": {}}))

            reader = ServerColumnReader(
                columns=[col], config=mock_config, config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("broken")

        assert values.get("server-a", {}) == {}

    def test_parse_server_values_raises_exception(self, mock_config):
        """Exception from parse_server_values should be handled gracefully."""
        mock_plugin = MagicMock()
        mock_plugin.get_config_schema.return_value = {
            "properties": {"state_file": {"default": "state.json"}}
        }
        mock_plugin.parse_server_values.side_effect = RuntimeError("boom")

        col = ServerColumnDefinition(
            handler_name="broken",
            plugin_class=mock_plugin,
            key="x",
            column_id="broken__x",
        )

        self._add_plugin_config(mock_config, "broken")

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            state_file.write_text(json.dumps({"instances": {}}))

            reader = ServerColumnReader(
                columns=[col], config=mock_config, config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("broken")

        # Should not raise; server-a should be present with empty dict
        # so that _update_column_values can default to 0 (prevents stale values)
        assert values.get("server-a") == {}

    def test_get_plugin_config_per_server_scope(self, mock_config):
        """_get_plugin_config should find config in per-server scopes."""
        mock_plugin_class = MagicMock()
        mock_plugin_class.get_config_schema.return_value = {"properties": {}}

        col = ServerColumnDefinition(
            handler_name="my_plugin",
            plugin_class=mock_plugin_class,
            key="x",
            column_id="my_plugin__x",
        )

        plugin = MagicMock()
        plugin.handler = "my_plugin"
        plugin.enabled = True
        plugin.config = {"enabled": True, "state_file": "per_server.json"}

        mock_config.plugins = MagicMock()
        mock_config.plugins.security = {}
        mock_config.plugins.middleware = {}
        mock_config.plugins.auditing = {
            "server-a": [plugin]
        }

        reader = ServerColumnReader(
            columns=[col], config=mock_config, config_directory=Path("/tmp"),
        )
        config = reader._get_plugin_config("my_plugin", server_name="server-a")
        assert config is not None
        assert config["state_file"] == "per_server.json"


class TestGetPluginConfigResolution:
    """Test _get_plugin_config with PluginConfig list structures and per-server resolution."""

    @staticmethod
    def _make_plugin(handler, config=None, enabled=True):
        """Create a mock PluginConfig object."""
        p = MagicMock()
        p.handler = handler
        p.enabled = enabled
        p.config = config if config is not None else {}
        return p

    @pytest.fixture
    def reader_with(self):
        """Return a factory that creates a ServerColumnReader with given plugins config."""
        mock_plugin_class = MagicMock()
        mock_plugin_class.get_config_schema.return_value = {"properties": {}}

        col = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=mock_plugin_class,
            key="x",
            column_id="token_usage__x",
        )

        def _factory(plugins_dict):
            config = MagicMock()
            config.upstreams = []
            config.plugins = MagicMock()
            config.plugins.security = plugins_dict.get("security", {})
            config.plugins.middleware = plugins_dict.get("middleware", {})
            config.plugins.auditing = plugins_dict.get("auditing", {})
            return ServerColumnReader(
                columns=[col], config=config, config_directory=Path("/tmp"),
            )
        return _factory

    def test_global_list_format(self, reader_with):
        """PluginConfig list in _global, finds by handler name."""
        p = self._make_plugin("token_usage", {"state_file": "global.json"})
        reader = reader_with({"auditing": {"_global": [p]}})
        result = reader._get_plugin_config("token_usage")
        assert result == {"state_file": "global.json"}

    def test_per_server_overrides_global(self, reader_with):
        """Per-server config returned instead of global when server_name provided."""
        g = self._make_plugin("token_usage", {"state_file": "global.json"})
        s = self._make_plugin("token_usage", {"state_file": "server.json"})
        reader = reader_with({"auditing": {"_global": [g], "srv1": [s]}})

        result = reader._get_plugin_config("token_usage", server_name="srv1")
        assert result == {"state_file": "server.json"}

    def test_per_server_disabled_no_fallback(self, reader_with):
        """Disabled per-server plugin returns None (does NOT fall back to global)."""
        g = self._make_plugin("token_usage", {"state_file": "global.json"})
        s = self._make_plugin("token_usage", enabled=False)
        reader = reader_with({"auditing": {"_global": [g], "srv1": [s]}})

        result = reader._get_plugin_config("token_usage", server_name="srv1")
        assert result is None

    def test_per_server_missing_handler_falls_to_global(self, reader_with):
        """Handler only in _global, server scope exists but doesn't mention it."""
        g = self._make_plugin("token_usage", {"state_file": "global.json"})
        other = self._make_plugin("other_plugin", {})
        reader = reader_with({"auditing": {"_global": [g], "srv1": [other]}})

        result = reader._get_plugin_config("token_usage", server_name="srv1")
        assert result == {"state_file": "global.json"}

    def test_global_disabled(self, reader_with):
        """Disabled global plugin returns None."""
        g = self._make_plugin("token_usage", {"state_file": "global.json"}, enabled=False)
        reader = reader_with({"auditing": {"_global": [g]}})

        result = reader._get_plugin_config("token_usage")
        assert result is None

    def test_server_name_none_resolves_global(self, reader_with):
        """server_name=None resolves _global even when per-server entries exist."""
        g = self._make_plugin("token_usage", {"state_file": "global.json"})
        s = self._make_plugin("token_usage", {"state_file": "server.json"})
        reader = reader_with({"auditing": {"_global": [g], "srv1": [s]}})

        result = reader._get_plugin_config("token_usage", server_name=None)
        assert result == {"state_file": "global.json"}


class TestReadColumnValuesPerServer:
    """Test read_column_values with per-server state file resolution."""

    @staticmethod
    def _make_plugin_mock(handler, config=None, enabled=True):
        p = MagicMock()
        p.handler = handler
        p.enabled = enabled
        p.config = config if config is not None else {}
        return p

    @pytest.fixture
    def mock_plugin_class(self):
        """Mock plugin class with parse_server_values and config schema."""
        mock = MagicMock()
        mock.get_config_schema.return_value = {
            "properties": {"state_file": {"default": "default_state.json"}}
        }

        def parse_server_values(state_data, server_name):
            total_count = 0
            for instance_data in state_data.get("instances", {}).values():
                servers = instance_data.get("servers", {})
                server_data = servers.get(server_name, {})
                total_count += server_data.get("count", 0)
            return {"count": total_count}

        mock.parse_server_values = parse_server_values
        return mock

    def test_per_server_state_files(self, mock_plugin_class):
        """Two servers with different state file paths, each read once."""
        col = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=mock_plugin_class,
            key="count",
            column_id="token_usage__count",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two separate state files
            file_a = Path(tmpdir) / "state_a.json"
            file_a.write_text(json.dumps({"instances": {"1": {"servers": {"srv-a": {"count": 10}}}}}))
            file_b = Path(tmpdir) / "state_b.json"
            file_b.write_text(json.dumps({"instances": {"1": {"servers": {"srv-b": {"count": 20}}}}}))

            pa = self._make_plugin_mock("token_usage", {"state_file": "state_a.json"})
            pb = self._make_plugin_mock("token_usage", {"state_file": "state_b.json"})

            config = MagicMock()
            ua = MagicMock(); ua.name = "srv-a"
            ub = MagicMock(); ub.name = "srv-b"
            config.upstreams = [ua, ub]
            config.plugins = MagicMock()
            config.plugins.security = {}
            config.plugins.middleware = {}
            config.plugins.auditing = {"srv-a": [pa], "srv-b": [pb]}

            reader = ServerColumnReader(
                columns=[col], config=config, config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("token_usage")

        assert values["srv-a"]["count"] == 10
        assert values["srv-b"]["count"] == 20

    def test_disabled_server_plugin_gets_empty(self, mock_plugin_class):
        """Server with disabled plugin gets empty values."""
        col = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=mock_plugin_class,
            key="count",
            column_id="token_usage__count",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = Path(tmpdir) / "default_state.json"
            file_a.write_text(json.dumps({"instances": {"1": {"servers": {"srv-a": {"count": 10}}}}}))

            g = self._make_plugin_mock("token_usage", {"state_file": "default_state.json"})
            disabled = self._make_plugin_mock("token_usage", enabled=False)

            config = MagicMock()
            ua = MagicMock(); ua.name = "srv-a"
            ub = MagicMock(); ub.name = "srv-b"
            config.upstreams = [ua, ub]
            config.plugins = MagicMock()
            config.plugins.security = {}
            config.plugins.middleware = {}
            config.plugins.auditing = {"_global": [g], "srv-b": [disabled]}

            reader = ServerColumnReader(
                columns=[col], config=config, config_directory=Path(tmpdir),
            )
            values = reader.read_column_values("token_usage")

        assert values["srv-a"]["count"] == 10
        assert values["srv-b"] is None  # Disabled plugin → not configured

    def test_path_is_none_gives_empty(self, mock_plugin_class):
        """_resolve_state_file_path returns None -> server gets empty values."""
        mock_plugin_class.get_config_schema.return_value = {"properties": {}}

        col = ServerColumnDefinition(
            handler_name="token_usage",
            plugin_class=mock_plugin_class,
            key="count",
            column_id="token_usage__count",
        )

        p = self._make_plugin_mock("token_usage", {})  # no state_file key

        config = MagicMock()
        ua = MagicMock(); ua.name = "srv-a"
        config.upstreams = [ua]
        config.plugins = MagicMock()
        config.plugins.security = {}
        config.plugins.middleware = {}
        config.plugins.auditing = {"_global": [p]}

        reader = ServerColumnReader(
            columns=[col], config=config, config_directory=Path("/tmp"),
        )
        values = reader.read_column_values("token_usage")

        assert values["srv-a"] is None  # No state file path → not available


class TestColumnActionRequestedScope:
    """Test ColumnActionRequested message scope field."""

    def test_default_scope_is_server(self):
        """ColumnActionRequested should default scope to 'server'."""
        from gatekit.tui.widgets.server_list import ColumnActionRequested

        msg = ColumnActionRequested(
            column_id="test__col",
            handler_name="test",
            method_name="do_thing",
            server_name="my-server",
        )
        assert msg.scope == "server"
        assert msg.server_name == "my-server"

    def test_scope_all_servers(self):
        """ColumnActionRequested with scope='all_servers' should store it."""
        from gatekit.tui.widgets.server_list import ColumnActionRequested

        msg = ColumnActionRequested(
            column_id="test__col",
            handler_name="test",
            method_name="do_thing",
            server_name="my-server",
            scope="all_servers",
        )
        assert msg.scope == "all_servers"
        # server_name is always provided (the row that was right-clicked)
        assert msg.server_name == "my-server"

    def test_scope_server_explicit(self):
        """ColumnActionRequested with explicit scope='server'."""
        from gatekit.tui.widgets.server_list import ColumnActionRequested

        msg = ColumnActionRequested(
            column_id="test__col",
            handler_name="test",
            method_name="do_thing",
            server_name="my-server",
            scope="server",
        )
        assert msg.scope == "server"


class TestValueFormatters:
    """Test the VALUE_FORMATTERS registry."""

    def test_humanized_number_registered(self):
        """humanized_number formatter should be registered."""
        assert "humanized_number" in VALUE_FORMATTERS
        assert VALUE_FORMATTERS["humanized_number"](1500) == "1.5K"

    def test_raw_registered(self):
        """raw formatter should be registered."""
        assert "raw" in VALUE_FORMATTERS
        assert VALUE_FORMATTERS["raw"](1500) == "1500"
