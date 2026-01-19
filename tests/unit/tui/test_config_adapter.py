"""Pure serialization tests for the TUI config adapter."""

from __future__ import annotations

import pytest

from gatekit.plugins.manager import PluginManager
from gatekit.tui.config_adapter import (
    build_form_state,
    merge_with_passthrough,
    serialize_form_data,
)
from tests.utils.golden import iter_golden_configs


def _all_golden_scenarios():
    scenarios = list(iter_golden_configs())
    if not scenarios:
        pytest.skip("No golden configs defined")
    return scenarios


@pytest.fixture(scope="module")
def handler_index() -> dict[str, dict[str, type]]:
    manager = PluginManager({})
    return {
        "security": manager.get_available_handlers("security"),
        "middleware": manager.get_available_handlers("middleware"),
        "auditing": manager.get_available_handlers("auditing"),
    }


def _config_values_preserved(original: dict, result: dict) -> bool:
    """Check that all original config values are preserved in the result.

    The result may contain additional keys (defaults populated per ADR-024),
    but all original values must be preserved.
    """
    for key, value in original.items():
        if key not in result:
            return False
        if isinstance(value, dict) and isinstance(result[key], dict):
            if not _config_values_preserved(value, result[key]):
                return False
        elif result[key] != value:
            return False
    return True


@pytest.mark.parametrize(
    "scenario",
    _all_golden_scenarios(),
    ids=lambda scn: f"adapter-{scn.handler}:{scn.scenario}",
)
def test_adapter_round_trip_preserves_config(scenario, handler_index):
    """config -> form -> config preserves original values (may add defaults).

    Per ADR-024, the adapter populates schema defaults for nested objects.
    This means the result may include additional keys beyond the original config,
    but all original values must be preserved.
    """
    plugin_class = handler_index[scenario.category][scenario.handler]

    state = build_form_state(plugin_class, scenario.config)
    serialized = serialize_form_data(state, state.initial_data)
    merged = merge_with_passthrough(state, serialized)

    # All original config values must be preserved
    assert _config_values_preserved(scenario.config, merged), (
        f"Original config values not preserved.\n"
        f"Original: {scenario.config}\n"
        f"Result: {merged}"
    )


def test_passthrough_fields_retained(handler_index):
    """Fields not represented in the schema should not be dropped."""
    plugin_class = handler_index["security"]["basic_pii_filter"]
    config = {
        "enabled": True,
        "priority": 30,
        "critical": True,
        "action": "redact",
        "passthrough_flag": "keep-me",
    }

    state = build_form_state(plugin_class, config)
    serialized = serialize_form_data(state, state.initial_data)
    merged = merge_with_passthrough(state, serialized)

    assert merged["passthrough_flag"] == "keep-me"


class TestSchemaDefaultsPopulation:
    """Tests for schema defaults being populated into form state.

    Regression tests for: TUI crash when enabling auditing plugins without
    output_file. Schema defaults must be populated into initial_data when
    the config is missing keys.
    """

    def test_build_form_state_populates_schema_defaults_for_missing_keys(self, handler_index):
        """build_form_state should populate schema defaults when config is missing keys.

        This is critical for auditing plugins which have required fields like output_file
        that have schema defaults. Without this, enabling a plugin in the TUI would crash.
        """
        plugin_class = handler_index["auditing"]["audit_csv"]

        # Minimal config missing output_file (simulates TUI toggle enabling plugin)
        config = {"enabled": True, "critical": True}

        state = build_form_state(plugin_class, config)

        # output_file should be populated from schema default
        assert "output_file" in state.initial_data, \
            "Schema default for output_file should be populated"
        assert state.initial_data["output_file"] == "logs/gatekit_audit.csv", \
            "output_file should match schema default"

    def test_build_form_state_populates_all_auditing_plugin_defaults(self, handler_index):
        """All auditing plugins should get their schema defaults populated."""
        for handler_name in ["audit_csv", "audit_jsonl", "audit_human_readable"]:
            plugin_class = handler_index["auditing"][handler_name]

            # Empty config (only framework fields)
            config = {"enabled": True, "critical": True}

            state = build_form_state(plugin_class, config)

            assert "output_file" in state.initial_data, \
                f"{handler_name}: output_file should be in initial_data"
            assert state.initial_data["output_file"], \
                f"{handler_name}: output_file should have a non-empty default"

    def test_build_form_state_preserves_explicit_config_over_schema_defaults(self, handler_index):
        """Explicit config values should take precedence over schema defaults."""
        plugin_class = handler_index["auditing"]["audit_csv"]

        # Config with explicit output_file
        config = {
            "enabled": True,
            "critical": True,
            "output_file": "/custom/path/audit.csv"
        }

        state = build_form_state(plugin_class, config)

        # Should use explicit value, not schema default
        assert state.initial_data["output_file"] == "/custom/path/audit.csv"

    def test_build_form_state_populates_nested_object_defaults(self, handler_index):
        """Schema defaults for nested objects (like csv_config) should be populated."""
        plugin_class = handler_index["auditing"]["audit_csv"]

        # Minimal config
        config = {"enabled": True, "critical": True}

        state = build_form_state(plugin_class, config)

        # csv_config has a default of {} in the schema
        assert "csv_config" in state.initial_data, \
            "csv_config should be populated from schema default"
