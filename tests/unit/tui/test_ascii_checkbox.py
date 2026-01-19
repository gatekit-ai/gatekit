"""Tests for ASCIICheckbox widget."""

from gatekit.tui.widgets.ascii_checkbox import ASCIICheckbox


class TestASCIICheckboxRendering:
    """Test ASCIICheckbox rendering functionality."""

    def test_ascii_checkbox_constants(self):
        """Test that ASCIICheckbox uses ASCII-safe characters."""
        checkbox = ASCIICheckbox("Test")

        assert checkbox.BUTTON_LEFT == "["
        assert checkbox.BUTTON_RIGHT == "]"
        assert checkbox.BUTTON_INNER == "X"

    def test_ascii_checkbox_creation(self):
        """Test creating ASCIICheckbox with different states."""
        # Test unchecked
        checkbox_unchecked = ASCIICheckbox("Test", value=False)
        assert checkbox_unchecked.value is False
        assert checkbox_unchecked.label == "Test"

        # Test checked
        checkbox_checked = ASCIICheckbox("Test", value=True)
        assert checkbox_checked.value is True
        assert checkbox_checked.label == "Test"

    def test_ascii_checkbox_empty_label(self):
        """Test ASCIICheckbox with empty label (used in plugin widgets)."""
        checkbox = ASCIICheckbox("", value=True)
        assert checkbox.label == ""
        assert checkbox.value is True

    def test_ascii_checkbox_button_constants_override(self):
        """Test that ASCII constants override the Unicode ones."""
        checkbox = ASCIICheckbox("Test", value=False)

        # Verify that our ASCII characters are used instead of Unicode
        assert checkbox.BUTTON_LEFT != "▐"  # Unicode left half block
        assert checkbox.BUTTON_RIGHT != "▌"  # Unicode right half block
        assert checkbox.BUTTON_LEFT == "["
        assert checkbox.BUTTON_RIGHT == "]"
        assert checkbox.BUTTON_INNER == "X"


class TestASCIICheckboxCSS:
    """Test ASCIICheckbox CSS and styling."""

    def test_ascii_checkbox_has_default_css(self):
        """Test that ASCIICheckbox has proper default CSS."""
        checkbox = ASCIICheckbox("Test")

        # Check that DEFAULT_CSS is defined and contains expected styles
        assert hasattr(checkbox, "DEFAULT_CSS")
        assert "ASCIICheckbox" in checkbox.DEFAULT_CSS
        assert "toggle--button" in checkbox.DEFAULT_CSS
        assert "background: transparent" in checkbox.DEFAULT_CSS

    def test_ascii_checkbox_width_smaller_than_unicode(self):
        """Test that ASCIICheckbox has smaller width than Unicode version."""
        # This is more of a documentation test - ASCII checkboxes should use less space
        # The CSS in global_plugins.py should set width: 3 instead of width: 4
        checkbox = ASCIICheckbox("Test")

        # ASCII version should be more compact
        # This is verified by the CSS changes in global_plugins.py
        assert checkbox.BUTTON_LEFT == "["  # Single character
        assert checkbox.BUTTON_RIGHT == "]"  # Single character
        # Total width should be 3 characters: [X] or [ ]


class TestASCIICheckboxIntegration:
    """Test ASCIICheckbox integration with other widgets."""

    def test_ascii_checkbox_id_assignment(self):
        """Test that ASCIICheckbox accepts and maintains ID."""
        checkbox = ASCIICheckbox("Test", id="test_id")
        assert checkbox.id == "test_id"

    def test_ascii_checkbox_toggles_state(self):
        """Test that ASCIICheckbox state can be toggled."""
        checkbox = ASCIICheckbox("Test", value=False)
        assert checkbox.value is False

        # Toggle the checkbox
        checkbox.toggle()
        assert checkbox.value is True

        # Toggle again
        checkbox.toggle()
        assert checkbox.value is False
