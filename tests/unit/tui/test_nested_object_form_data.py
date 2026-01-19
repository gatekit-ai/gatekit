"""Test nested object form data collection for call_trace plugin.

This test verifies that trace_fields nested object values are properly
collected from the form and returned by get_form_data(), and survive
the full round-trip through merge_with_passthrough.
"""

from unittest.mock import MagicMock

from gatekit.plugins.middleware.call_trace import CallTracePlugin
from gatekit.tui.config_adapter import (
    build_form_state,
    serialize_form_data,
    merge_with_passthrough,
)
from gatekit.tui.utils.json_form_adapter import JSONFormAdapter
from gatekit.tui.utils.field_registry import FieldRegistry


class TestNestedObjectFormData:
    """Test nested object form data collection."""

    def test_call_trace_schema_has_trace_fields(self):
        """Verify call_trace schema includes trace_fields nested object."""
        state = build_form_state(CallTracePlugin, {})

        assert "trace_fields" in state.schema_keys
        assert "trace_fields" in state.schema.get("properties", {})

        trace_fields_schema = state.schema["properties"]["trace_fields"]
        assert trace_fields_schema.get("type") == "object"

        expected_fields = ["server", "tool", "params", "response_size", "duration", "request_id", "timestamp"]
        actual_fields = list(trace_fields_schema.get("properties", {}).keys())
        assert sorted(actual_fields) == sorted(expected_fields)

    def test_set_nested_value_builds_correct_structure(self):
        """Test that _set_nested_value builds the correct nested dict structure."""
        state = build_form_state(CallTracePlugin, {})
        registry = FieldRegistry()
        adapter = JSONFormAdapter(state.schema, state.initial_data, "", registry)

        data = {}

        # Simulate what get_form_data does for trace_fields properties
        test_cases = [
            ("/properties/trace_fields/properties/server", True),
            ("/properties/trace_fields/properties/tool", False),
            ("/properties/trace_fields/properties/params", True),
            ("/properties/trace_fields/properties/response_size", False),
        ]

        for pointer, value in test_cases:
            adapter._set_nested_value(data, pointer, value)

        # Verify nested structure was built correctly
        assert "trace_fields" in data
        assert isinstance(data["trace_fields"], dict)
        assert data["trace_fields"]["server"] is True
        assert data["trace_fields"]["tool"] is False
        assert data["trace_fields"]["params"] is True
        assert data["trace_fields"]["response_size"] is False

    def test_serialize_form_data_preserves_nested_objects(self):
        """Test that serialize_form_data preserves nested object structure."""
        state = build_form_state(CallTracePlugin, {})

        raw_form_data = {
            "enabled": True,
            "priority": 50,
            "max_param_length": 200,
            "trace_fields": {
                "server": True,
                "tool": False,
                "params": True,
                "response_size": True,
                "duration": False,
                "request_id": True,
                "timestamp": True,
            }
        }

        serialized = serialize_form_data(state, raw_form_data)

        assert "trace_fields" in serialized
        assert isinstance(serialized["trace_fields"], dict)
        assert serialized["trace_fields"]["server"] is True
        assert serialized["trace_fields"]["tool"] is False
        assert serialized["trace_fields"]["params"] is True
        assert serialized["trace_fields"]["response_size"] is True
        assert serialized["trace_fields"]["duration"] is False
        assert serialized["trace_fields"]["request_id"] is True
        assert serialized["trace_fields"]["timestamp"] is True

    def test_get_form_data_with_mocked_checkboxes(self):
        """Test get_form_data collects nested checkbox values correctly."""
        state = build_form_state(CallTracePlugin, {})
        registry = FieldRegistry()
        adapter = JSONFormAdapter(state.schema, state.initial_data, "", registry)

        # Mock checkboxes for trace_fields properties
        # Register them as would happen during form generation
        from textual.widgets import Checkbox

        trace_field_values = {
            "server": True,
            "tool": False,
            "params": True,
            "response_size": True,
            "duration": False,
            "request_id": True,
            "timestamp": True,
        }

        for field_name, value in trace_field_values.items():
            mock_checkbox = MagicMock(spec=Checkbox)
            mock_checkbox.value = value
            mock_checkbox.id = None  # Let registry assign ID

            pointer = f"/properties/trace_fields/properties/{field_name}"
            schema = {"type": "boolean"}
            registry.register(pointer, mock_checkbox, schema, False)

        # Also register top-level fields
        for field_name, value in [("enabled", True), ("priority", 50), ("max_param_length", 200)]:
            if field_name in ["enabled"]:
                mock_widget = MagicMock(spec=Checkbox)
                mock_widget.value = value
            else:
                from textual.widgets import Input
                mock_widget = MagicMock(spec=Input)
                mock_widget.value = str(value)
            mock_widget.id = None

            pointer = f"/properties/{field_name}"
            schema = {"type": "integer" if field_name in ["priority", "max_param_length"] else "boolean"}
            registry.register(pointer, mock_widget, schema, False)

        # Now call get_form_data
        form_data = adapter.get_form_data()

        # Verify trace_fields structure exists
        assert "trace_fields" in form_data, f"Expected 'trace_fields' in form_data, got: {form_data.keys()}"
        assert isinstance(form_data["trace_fields"], dict)

        # Verify all nested values
        for field_name, expected_value in trace_field_values.items():
            assert form_data["trace_fields"][field_name] == expected_value, \
                f"Expected trace_fields.{field_name}={expected_value}, got {form_data['trace_fields'].get(field_name)}"


class TestNestedObjectRoundTrip:
    """Test full round-trip of nested objects through the config save pipeline.

    These tests verify that nested fields like trace_fields survive the complete
    save flow: build_form_state -> serialize_form_data -> merge_with_passthrough.

    This is critical because the original bug was in merge_with_passthrough
    removing keys that weren't in the original config.
    """

    def test_trace_fields_survives_roundtrip_from_empty_config(self):
        """Verify trace_fields survives when original config lacks that key.

        This is the exact scenario that triggered the bug: config only had
        'enabled' and 'priority', but not 'trace_fields' or 'max_param_length'.
        """
        # Original config lacks trace_fields (like the real bug scenario)
        original_config = {"enabled": True, "priority": 50}
        state = build_form_state(CallTracePlugin, original_config)

        # Simulate form data with trace_fields set by user
        form_data = {
            "enabled": True,
            "priority": 50,
            "max_param_length": 200,
            "trace_fields": {
                "server": False,
                "tool": True,
                "params": True,
                "response_size": True,
                "duration": False,
                "request_id": True,
                "timestamp": True,
            }
        }

        # Run through the full save pipeline
        serialized = serialize_form_data(state, form_data)
        final_config = merge_with_passthrough(state, serialized)

        # trace_fields MUST survive - this was the bug
        assert "trace_fields" in final_config, \
            f"trace_fields was dropped! Final config keys: {list(final_config.keys())}"
        assert final_config["trace_fields"]["server"] is False
        assert final_config["trace_fields"]["tool"] is True

        # max_param_length should also survive
        assert "max_param_length" in final_config
        assert final_config["max_param_length"] == 200

    def test_all_schema_fields_preserved_from_minimal_config(self):
        """Verify all schema fields are preserved even from minimal starting config."""
        # Minimal config - only required fields
        minimal_config = {"enabled": False}
        state = build_form_state(CallTracePlugin, minimal_config)

        # User fills out all fields in the form
        form_data = {
            "enabled": True,
            "priority": 25,
            "max_param_length": 500,
            "trace_fields": {
                "server": True,
                "tool": True,
                "params": False,
                "response_size": False,
                "duration": True,
                "request_id": False,
                "timestamp": True,
            }
        }

        serialized = serialize_form_data(state, form_data)
        final_config = merge_with_passthrough(state, serialized)

        # All fields should be in final config
        assert final_config["enabled"] is True
        assert final_config["priority"] == 25
        assert final_config["max_param_length"] == 500
        assert "trace_fields" in final_config
        assert final_config["trace_fields"]["params"] is False
        assert final_config["trace_fields"]["duration"] is True

    def test_passthrough_keys_preserved_alongside_schema_fields(self):
        """Verify unknown config keys are preserved while adding new schema fields."""
        # Config with an unknown field (e.g., from older plugin version)
        original_config = {
            "enabled": True,
            "priority": 50,
            "unknown_legacy_field": "preserve_me",
        }
        state = build_form_state(CallTracePlugin, original_config)

        # Form data includes new trace_fields
        form_data = {
            "enabled": True,
            "priority": 50,
            "max_param_length": 200,
            "trace_fields": {
                "server": True,
                "tool": True,
                "params": True,
                "response_size": True,
                "duration": True,
                "request_id": True,
                "timestamp": True,
            }
        }

        serialized = serialize_form_data(state, form_data)
        final_config = merge_with_passthrough(state, serialized)

        # Both new schema fields AND legacy field should be preserved
        assert "trace_fields" in final_config
        assert "max_param_length" in final_config
        assert final_config["unknown_legacy_field"] == "preserve_me"

    def test_empty_config_gets_all_form_fields(self):
        """Verify completely empty config gets all fields from form."""
        state = build_form_state(CallTracePlugin, {})

        form_data = {
            "enabled": True,
            "priority": 50,
            "max_param_length": 100,
            "trace_fields": {
                "server": True,
                "tool": False,
                "params": True,
                "response_size": False,
                "duration": True,
                "request_id": False,
                "timestamp": True,
            }
        }

        serialized = serialize_form_data(state, form_data)
        final_config = merge_with_passthrough(state, serialized)

        assert len(final_config) == 4  # enabled, priority, max_param_length, trace_fields
        assert "trace_fields" in final_config
        assert len(final_config["trace_fields"]) == 7
