"""ASCII-safe checkbox widget for better Mac Terminal compatibility."""

from typing import TYPE_CHECKING

from textual.widgets._toggle_button import ToggleButton

if TYPE_CHECKING:
    from textual.content import Content


class ASCIICheckbox(ToggleButton):
    """Checkbox widget using ASCII-safe characters for Mac Terminal compatibility."""

    # Override the Unicode half-block characters with ASCII brackets
    BUTTON_LEFT: str = "["
    BUTTON_INNER: str = "X"  # Keep X for checked, space for unchecked
    BUTTON_RIGHT: str = "]"

    # Custom CSS to ensure proper spacing and prevent Unicode fallback
    DEFAULT_CSS = """
    ASCIICheckbox {
        width: auto;
        min-width: 3;
        border: none;
        padding: 0;
        background: transparent;
        overflow: hidden;

        & > .toggle--button {
            color: $text;
            background: transparent;
        }

        &.-on > .toggle--button {
            color: $success;
            background: transparent;
        }

        &:hover {
            background: $primary;

            & > .toggle--button {
                color: $background;
                background: transparent;
            }

            &.-on > .toggle--button {
                color: $success;
                background: transparent;
            }
        }

        &:focus {
            border: none !important;
            background: $block-cursor-background;

            & > .toggle--button {
                color: $block-cursor-foreground;
                background: transparent;
            }

            &.-on > .toggle--button {
                color: $success;
                background: transparent;
            }
        }

        &:disabled {
            opacity: 0.5;

            & > .toggle--button {
                color: $text-muted;
            }
        }

        &:disabled:hover {
            background: transparent;
        }
    }
    """

    @property
    def _button(self) -> "Content":
        """The button, reflecting the current value."""
        from textual.content import Content
        from textual.style import Style

        # Grab the button style.
        button_style = self.get_visual_style("toggle--button")

        # Building the style for the side characters (brackets)
        side_style = Style(
            foreground=button_style.foreground,
            background=self.background_colors[1],
        )

        # For unchecked state, use space instead of X
        inner_char = self.BUTTON_INNER if self.value else " "

        return Content.assemble(
            (self.BUTTON_LEFT, side_style),
            (inner_char, button_style),
            (self.BUTTON_RIGHT, side_style),
        )

    def render(self) -> "Content":
        """Render just the button without label padding.

        Overrides ToggleButton.render() which adds .pad(1,1) to the label,
        causing a 2-cell discrepancy between rendered content (5 cells) and
        get_content_width() (3 cells) when label is empty. This was a
        breaking change in Textual 6.x/7.x that causes truncation.
        """
        return self._button

    def watch_value(self, value: bool) -> None:
        """Watch for value changes and log them for debugging."""
        # Get the old value before calling super
        old_value = getattr(self, "_previous_value", False)
        self._previous_value = value

        # Log the checkbox toggle for debugging
        from ..debug import get_debug_logger

        logger = get_debug_logger()

        # Only log if widget is properly mounted and value actually changed
        if logger and logger.enabled and old_value != value:
            try:
                # Check if widget has a screen (is mounted)
                screen = None
                try:
                    screen = self.screen
                except Exception:
                    # Widget not mounted yet, skip logging
                    return

                # Extract plugin info from widget ID and context
                plugin_name = "unknown"
                plugin_type = "unknown"

                if hasattr(self, "id") and self.id:
                    # Extract plugin name from checkbox ID (format: checkbox_plugin_name)
                    if self.id.startswith("checkbox_"):
                        plugin_name = self.id[9:]  # Remove 'checkbox_' prefix

                        # Determine plugin type based on the parent widget context
                        try:
                            # Walk up the widget tree to find the plugin type
                            current = self.parent
                            while current:
                                if hasattr(current, "__class__"):
                                    class_name = current.__class__.__name__
                                    if "Security" in class_name:
                                        plugin_type = "security"
                                        break
                                    elif "Auditing" in class_name:
                                        plugin_type = "auditing"
                                        break
                                current = getattr(current, "parent", None)
                        except Exception:
                            pass  # Fallback to unknown

                logger.log_checkbox_toggle(
                    widget=self,
                    old_checked=old_value,
                    new_checked=value,
                    plugin_name=plugin_name,
                    plugin_type=plugin_type,
                    screen=screen,
                )
            except Exception:
                # Ignore any logging errors to prevent disrupting the TUI
                pass

        # Call the parent's method to update CSS classes (if parent is GlobalPluginItem)
        if old_value != value and hasattr(self.parent, "on_checkbox_value_changed"):
            try:
                self.parent.on_checkbox_value_changed(self, value)
            except Exception:
                # Ignore any errors to prevent disrupting the TUI
                pass
