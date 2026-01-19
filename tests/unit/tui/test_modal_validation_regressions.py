"""Regression tests for modal validation fixes.

These tests exercise PRODUCTION CODE to ensure:
1. Real auditing plugin schemas have minLength: 1 on output_file
2. Modal _validate_input_field correctly handles 0 values for numeric fields
3. Modal _validate_input_field correctly rejects empty strings for required fields
4. Modal _handle_save_action refuses to dismiss when error_labels is non-empty
"""

from unittest.mock import Mock, patch, PropertyMock

from gatekit.tui.screens.plugin_config import PluginConfigModal
from gatekit.tui.utils.field_registry import FieldInfo
from gatekit.plugins.interfaces import SecurityPlugin


# =============================================================================
# Tests for REAL auditing plugin schemas
# =============================================================================


class TestRealAuditingPluginSchemas:
    """Test that real auditing plugin schemas have minLength: 1 on output_file.

    Regression test: If someone removes minLength from the schemas, these tests fail.
    """

    def test_jsonl_plugin_output_file_has_minlength(self):
        """JsonAuditingPlugin schema must have minLength: 1 on output_file."""
        from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin

        schema = JsonAuditingPlugin.get_json_schema()
        output_file_schema = schema["properties"]["output_file"]

        assert output_file_schema.get("minLength") == 1, (
            "JsonAuditingPlugin.output_file must have minLength: 1 to prevent empty strings"
        )

    def test_csv_plugin_output_file_has_minlength(self):
        """CsvAuditingPlugin schema must have minLength: 1 on output_file."""
        from gatekit.plugins.auditing.csv import CsvAuditingPlugin

        schema = CsvAuditingPlugin.get_json_schema()
        output_file_schema = schema["properties"]["output_file"]

        assert output_file_schema.get("minLength") == 1, (
            "CsvAuditingPlugin.output_file must have minLength: 1 to prevent empty strings"
        )

    def test_human_readable_plugin_output_file_has_minlength(self):
        """LineAuditingPlugin schema must have minLength: 1 on output_file."""
        from gatekit.plugins.auditing.human_readable import LineAuditingPlugin

        schema = LineAuditingPlugin.get_json_schema()
        output_file_schema = schema["properties"]["output_file"]

        assert output_file_schema.get("minLength") == 1, (
            "LineAuditingPlugin.output_file must have minLength: 1 to prevent empty strings"
        )

    def test_output_file_is_required_in_all_auditing_plugins(self):
        """All auditing plugins must have output_file in required list."""
        from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin
        from gatekit.plugins.auditing.csv import CsvAuditingPlugin
        from gatekit.plugins.auditing.human_readable import LineAuditingPlugin

        for plugin_class in [JsonAuditingPlugin, CsvAuditingPlugin, LineAuditingPlugin]:
            schema = plugin_class.get_json_schema()
            required = schema.get("required", [])

            assert "output_file" in required, (
                f"{plugin_class.__name__} must have output_file in required list"
            )


# =============================================================================
# Tests for _validate_input_field production method
# =============================================================================


class MockPluginWithNumericField(SecurityPlugin):
    """Mock plugin with a required integer field for testing."""

    DISPLAY_NAME = "Test Plugin"
    DISPLAY_SCOPE = "global"

    @classmethod
    def get_json_schema(cls):
        return {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "integer",
                    "description": "Threshold (0 = unlimited)",
                    "default": 10,
                    "minimum": 0,
                },
            },
            "required": ["threshold"],
        }


class MockPluginWithStringField(SecurityPlugin):
    """Mock plugin with a required string field for testing."""

    DISPLAY_NAME = "Test Plugin"
    DISPLAY_SCOPE = "global"

    @classmethod
    def get_json_schema(cls):
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name field",
                    "default": "default",
                    "minLength": 1,
                },
            },
            "required": ["name"],
        }


class TestValidateInputFieldProduction:
    """Test the actual _validate_input_field method in PluginConfigModal.

    These tests call the real production code to verify validation behavior.
    """

    def _create_mock_input(self, value: str, widget_id: str = "field_test") -> Mock:
        """Create a mock Input widget with the given value."""
        mock_input = Mock()
        mock_input.value = value
        mock_input.id = widget_id
        return mock_input

    def _create_field_info(
        self, schema: dict, required: bool = True, widget_id: str = "field_test"
    ) -> FieldInfo:
        """Create a FieldInfo for testing."""
        return FieldInfo(
            json_pointer="/properties/test",
            widget_id=widget_id,
            widget=None,
            schema=schema,
            required=required,
        )

    def test_integer_zero_does_not_trigger_required_error(self):
        """Integer value 0 should NOT trigger a required field error.

        Regression test: Previously `not field_value` treated 0 as falsy.
        """
        modal = PluginConfigModal(MockPluginWithNumericField, "test", {})

        mock_input = self._create_mock_input("0", "field_threshold")
        field_info = self._create_field_info(
            schema={"type": "integer", "minimum": 0},
            required=True,
            widget_id="field_threshold",
        )

        # Mock _show_field_error and _clear_field_error to track calls
        modal._show_field_error = Mock()
        modal._clear_field_error = Mock()

        # Call the REAL production method
        modal._validate_input_field(mock_input, field_info)

        # Should NOT have called _show_field_error with required message
        for call in modal._show_field_error.call_args_list:
            args = call[0]
            assert "required" not in args[1].lower(), (
                f"Integer 0 incorrectly triggered required error: {args[1]}"
            )

        # Should have called _clear_field_error (validation passed)
        modal._clear_field_error.assert_called()

    def test_integer_empty_string_triggers_required_error(self):
        """Empty string for required integer field should trigger error."""
        modal = PluginConfigModal(MockPluginWithNumericField, "test", {})

        mock_input = self._create_mock_input("", "field_threshold")
        field_info = self._create_field_info(
            schema={"type": "integer", "minimum": 0},
            required=True,
            widget_id="field_threshold",
        )

        modal._show_field_error = Mock()
        modal._clear_field_error = Mock()

        modal._validate_input_field(mock_input, field_info)

        # Should have called _show_field_error with required message
        modal._show_field_error.assert_called()
        args = modal._show_field_error.call_args[0]
        assert "required" in args[1].lower(), (
            f"Empty integer field should trigger required error, got: {args[1]}"
        )

    def test_string_empty_triggers_required_error(self):
        """Empty string for required string field should trigger error."""
        modal = PluginConfigModal(MockPluginWithStringField, "test", {})

        mock_input = self._create_mock_input("", "field_name")
        field_info = self._create_field_info(
            schema={"type": "string", "minLength": 1},
            required=True,
            widget_id="field_name",
        )

        modal._show_field_error = Mock()
        modal._clear_field_error = Mock()

        modal._validate_input_field(mock_input, field_info)

        # Should have called _show_field_error
        modal._show_field_error.assert_called()
        args = modal._show_field_error.call_args[0]
        assert "required" in args[1].lower(), (
            f"Empty string field should trigger required error, got: {args[1]}"
        )

    def test_string_with_content_passes_validation(self):
        """Non-empty string for required string field should pass."""
        modal = PluginConfigModal(MockPluginWithStringField, "test", {})

        mock_input = self._create_mock_input("valid_value", "field_name")
        field_info = self._create_field_info(
            schema={"type": "string", "minLength": 1},
            required=True,
            widget_id="field_name",
        )

        modal._show_field_error = Mock()
        modal._clear_field_error = Mock()

        modal._validate_input_field(mock_input, field_info)

        # Should have called _clear_field_error (validation passed)
        modal._clear_field_error.assert_called()


# =============================================================================
# Tests for _handle_save_action error_labels guard
# =============================================================================


class TestHandleSaveActionErrorGuard:
    """Test that _handle_save_action refuses to dismiss when error_labels is non-empty.

    This exercises the production guard that was added to prevent saving
    when inline validation errors are showing.
    """

    def test_save_blocked_when_error_labels_present(self):
        """Modal should not dismiss when error_labels has entries."""
        modal = PluginConfigModal(MockPluginWithStringField, "test", {"name": "valid"})

        # Simulate an inline validation error
        modal.error_labels = {"field_name": "This field is required"}

        # Mock dismiss and app.notify to verify behavior
        modal.dismiss = Mock()
        mock_app = Mock()

        # Patch app property at class level
        with patch.object(
            PluginConfigModal, "app", new_callable=PropertyMock, return_value=mock_app
        ):
            # Call the REAL production method
            modal._handle_save_action()

        # Should NOT have called dismiss
        modal.dismiss.assert_not_called()

        # Should have notified user about validation errors
        mock_app.notify.assert_called()
        call_args = mock_app.notify.call_args
        assert "validation" in call_args[0][0].lower() or "error" in call_args[0][0].lower()

    def test_save_proceeds_when_error_labels_empty(self):
        """Modal should proceed with save when error_labels is empty."""
        modal = PluginConfigModal(MockPluginWithStringField, "test", {"name": "valid"})

        # No inline validation errors
        modal.error_labels = {}

        # Mock the form adapter and validation
        modal.form_adapter = Mock()
        modal.form_adapter.get_form_data = Mock(return_value={"name": "valid"})

        # Mock dismiss to verify it gets called
        modal.dismiss = Mock()
        mock_app = Mock()

        # Mock the validator to return no errors
        modal.validator = Mock()
        modal.validator.validate = Mock(return_value=[])

        # Mock serialize_form_data and app property at class level
        with patch(
            "gatekit.tui.screens.plugin_config.modal.serialize_form_data"
        ) as mock_serialize:
            mock_serialize.return_value = {"name": "valid"}

            with patch.object(
                PluginConfigModal, "app", new_callable=PropertyMock, return_value=mock_app
            ):
                # Call the REAL production method
                modal._handle_save_action()

        # Should have called dismiss with the config
        modal.dismiss.assert_called_once()
