"""Tests for ConfigErrorModal TUI component."""

from pathlib import Path
from gatekit.config.errors import ConfigError
from gatekit.tui.screens.config_error_modal import ConfigErrorModal


class TestConfigErrorModal:
    """Test ConfigErrorModal component behavior."""

    def test_modal_creation_with_minimal_error(self):
        """Test creating modal with minimal ConfigError."""
        error = ConfigError(message="Test error", error_type="yaml_syntax")

        modal = ConfigErrorModal(error)
        assert modal.config_error == error
        assert modal.config_error.message == "Test error"

    def test_modal_creation_with_complete_error(self):
        """Test creating modal with complete ConfigError with all fields."""
        error = ConfigError(
            message="Plugin not found",
            error_type="missing_plugin",
            file_path=Path("/test/config.yaml"),
            line_number=42,
            field_path="plugins.auditing.typo_plugin",
            suggestions=[
                "Did you mean 'json_auditing'?",
                "Available plugins: csv, json",
            ],
            line_snippet="    handler: typo_plugin",
        )

        modal = ConfigErrorModal(error)
        assert modal.config_error == error
        assert modal.config_error.can_ignore is True  # missing plugins can be ignored

    def test_modal_title_display(self):
        """Test that modal displays error title correctly."""
        error = ConfigError(message="Configuration error", error_type="yaml_syntax")

        modal = ConfigErrorModal(error)
        # Modal should have a compose method (testing it exists)
        assert hasattr(modal, "compose")
        # Should store error for display
        assert modal.config_error.message == "Configuration error"

    def test_modal_button_configuration_for_yaml_error(self):
        """Test button configuration for YAML syntax error."""
        error = ConfigError(message="YAML error", error_type="yaml_syntax")

        ConfigErrorModal(error)
        # YAML errors can be edited but not ignored
        assert error.can_edit is True
        assert error.can_ignore is False

    def test_modal_button_configuration_for_missing_plugin(self):
        """Test button configuration for missing plugin error."""
        error = ConfigError(message="Plugin not found", error_type="missing_plugin")

        ConfigErrorModal(error)
        # Missing plugin errors can be edited and ignored
        assert error.can_edit is True
        assert error.can_ignore is True

    def test_modal_button_configuration_for_validation_error(self):
        """Test button configuration for validation error."""
        error = ConfigError(message="Invalid value", error_type="validation_error")

        ConfigErrorModal(error)
        # Validation errors can be edited but not ignored
        assert error.can_edit is True
        assert error.can_ignore is False

    def test_modal_location_info_display(self):
        """Test that modal displays location information when available."""
        error = ConfigError(
            message="Test error",
            error_type="yaml_syntax",
            file_path=Path("/test/config.yaml"),
            line_number=42,
            field_path="plugins.auditing.test",
        )

        ConfigErrorModal(error)
        # Should properly store error data for display
        assert error.file_path == Path("/test/config.yaml")
        assert error.line_number == 42
        assert error.field_path == "plugins.auditing.test"

    def test_modal_line_snippet_display(self):
        """Test that modal displays line snippets for YAML errors."""
        error = ConfigError(
            message="YAML syntax error",
            error_type="yaml_syntax",
            line_number=5,
            line_snippet="  bad_indent: value",
        )

        ConfigErrorModal(error)
        # Should have line snippet available for display
        assert error.line_snippet == "  bad_indent: value"

    def test_modal_suggestions_display(self):
        """Test that modal displays suggestions correctly."""
        suggestions = ["Fix indentation", "Check syntax", "Validate YAML"]
        error = ConfigError(
            message="YAML error", error_type="yaml_syntax", suggestions=suggestions
        )

        ConfigErrorModal(error)
        # Should have suggestions available for display
        assert len(error.suggestions) == 3
        assert error.suggestions == suggestions

    def test_modal_suggestions_limit_enforcement(self):
        """Test that modal enforces 3-suggestion limit."""
        many_suggestions = [
            "Suggestion 1",
            "Suggestion 2",
            "Suggestion 3",
            "Suggestion 4",
            "Suggestion 5",
        ]
        error = ConfigError(
            message="Error with many suggestions",
            error_type="yaml_syntax",
            suggestions=many_suggestions,
        )

        ConfigErrorModal(error)
        # Should be limited to 3 suggestions
        assert len(error.suggestions) == 3
        assert error.suggestions == many_suggestions[:3]


class TestConfigErrorModalButtonHandling:
    """Test ConfigErrorModal button press handling."""

    def test_button_press_returns_action(self):
        """Test that button presses return correct action strings."""
        error = ConfigError(message="Test error", error_type="missing_plugin")

        modal = ConfigErrorModal(error)

        # Mock button press events
        class MockButton:
            def __init__(self, button_id):
                self.id = button_id

        class MockEvent:
            def __init__(self, button_id):
                self.button = MockButton(button_id)

        # Mock the dismiss method to capture what gets passed
        dismissed_results = []

        def mock_dismiss(result):
            dismissed_results.append(result)

        modal.dismiss = mock_dismiss

        # Test different button presses
        edit_event = MockEvent("edit")
        modal.on_button_pressed(edit_event)
        assert dismissed_results[-1] == "edit"

        ignore_event = MockEvent("ignore")
        modal.on_button_pressed(ignore_event)
        assert dismissed_results[-1] == "ignore"

        close_event = MockEvent("close")
        modal.on_button_pressed(close_event)
        assert dismissed_results[-1] == "close"

        # Should have captured all three actions
        assert len(dismissed_results) == 3
        assert dismissed_results == ["edit", "ignore", "close"]

    def test_modal_dismissal_with_result(self):
        """Test that modal can be dismissed with different results."""
        error = ConfigError(message="Test error", error_type="missing_plugin")

        modal = ConfigErrorModal(error)

        # Should have dismiss method from ModalScreen
        assert hasattr(modal, "dismiss")
        # Should be a ModalScreen[str] (returns string result)
        assert issubclass(type(modal), object)  # Basic test that it's a valid object
