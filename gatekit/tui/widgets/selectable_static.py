"""SelectableStatic widget - A Static widget with text selection capabilities."""

from typing import Optional
from textual.widgets import Static
from textual.events import MouseDown, MouseMove, MouseUp, Key
from textual.geometry import Offset
from textual.reactive import reactive
from textual.message import Message
from textual.binding import Binding
from rich.text import Text
from rich.style import Style

from gatekit.tui.debug import get_debug_logger


class TextSelected(Message):
    """Message posted when text is selected."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class SelectableStatic(Static):
    """A Static widget that supports text selection with mouse and keyboard shortcuts."""

    # Track selection state
    selection_start: reactive[Optional[int]] = reactive(None)
    selection_end: reactive[Optional[int]] = reactive(None)
    is_selecting: reactive[bool] = reactive(False)
    mouse_captured: reactive[bool] = reactive(False)

    # Key bindings - use priority to override system handling
    BINDINGS = [
        Binding("ctrl+c", "smart_copy", "Copy/Interrupt", show=False, priority=True),
    ]

    DEFAULT_CSS = """
    SelectableStatic {
        background: transparent;
    }
    
    SelectableStatic:focus {
        background: transparent;
        /* Removed outline to avoid dotted border when selecting text */
    }
    """

    def __init__(
        self,
        renderable="",
        *,
        expand=False,
        shrink=False,
        markup=True,
        name=None,
        id=None,
        classes=None,
        disabled=False,
        can_focus=False,
    ):
        super().__init__(
            renderable,
            expand=expand,
            shrink=shrink,
            markup=markup,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        # Store original renderable to preserve styling (e.g., underlines)
        self._original_renderable = renderable
        # Extract plain text for selection purposes
        if isinstance(renderable, Text):
            self._text_content = renderable.plain
        else:
            self._text_content = str(renderable) if renderable else ""
        self._tooltip_shown = False  # Track if we've shown the tooltip
        self._original_can_focus = can_focus  # Store original focusable state
        self.can_focus = can_focus  # Set initial focusable state
        self._visual_lines: list[tuple[int, int]] = []  # (start, end) for each visual line

    def update(self, renderable, *, _preserve_original: bool = True) -> None:  # type: ignore[override]
        """Update renderable content while tracking the plain-text payload.

        Args:
            renderable: The content to display
            _preserve_original: If True (default), store as new original renderable.
                               If False, this is a temporary update (e.g., selection highlight).
        """
        if renderable is None:
            self._text_content = ""
            if _preserve_original:
                self._original_renderable = renderable
        elif isinstance(renderable, Text):
            self._text_content = renderable.plain
            if _preserve_original:
                self._original_renderable = renderable
        else:
            self._text_content = str(renderable)
            if _preserve_original:
                self._original_renderable = renderable

        super().update(renderable)

        # Recalculate visual lines when content changes
        if _preserve_original:
            self._recalculate_visual_lines()

    def _recalculate_visual_lines(self) -> None:
        """Calculate character ranges for each visual line based on widget width.

        This is needed because Textual soft-wraps text at widget boundaries,
        but the mouse offset.y reflects visual lines, not logical lines.
        We use textwrap to approximate where line breaks occur.
        """
        import textwrap

        if not self._text_content:
            self._visual_lines = [(0, 0)]
            return

        width = self.size.width if self.size else 80
        if width <= 0:
            width = 80

        # Use textwrap to simulate how text wraps
        wrapped = textwrap.wrap(
            self._text_content,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        )

        if not wrapped:
            self._visual_lines = [(0, len(self._text_content))]
            return

        # Map each wrapped line back to positions in original text
        lines: list[tuple[int, int]] = []
        search_pos = 0

        for wrapped_line in wrapped:
            # Find where this wrapped line's content starts in original
            # textwrap.wrap may strip leading/trailing spaces, so search for the content
            stripped = wrapped_line.strip()
            if stripped:
                idx = self._text_content.find(stripped, search_pos)
                if idx == -1:
                    idx = search_pos
                start = idx
                end = idx + len(stripped)
            else:
                start = search_pos
                end = search_pos

            lines.append((start, end))
            search_pos = end
            # Skip whitespace between wrapped segments
            while search_pos < len(self._text_content) and self._text_content[search_pos] in ' \t':
                search_pos += 1

        self._visual_lines = lines or [(0, len(self._text_content))]

    def on_resize(self, event) -> None:
        """Recalculate visual lines when widget size changes."""
        self._recalculate_visual_lines()

    def on_mount(self) -> None:
        """Calculate visual lines on mount."""
        self._recalculate_visual_lines()

    def _log_debug(self, event_type: str, **context: object) -> None:
        """Emit debug instrumentation without impacting runtime."""
        try:
            logger = get_debug_logger()
            if logger:
                logger.log_event(
                    event_type,
                    widget=self,
                    screen=self.screen,
                    context=context,
                )
        except Exception:
            # Never let debug logging break selection.
            pass

    def on_mouse_down(self, event: MouseDown) -> None:
        """Handle mouse down to start text selection."""

        if event.button != 1:  # Only handle left mouse button
            return

        # Don't capture mouse yet - wait for drag (mouse_move)
        # This allows Click events to propagate normally for simple clicks

        # Temporarily enable focus for text selection and keyboard shortcuts
        self.can_focus = True
        self.focus()

        # Calculate character position from mouse offset
        char_pos = self._offset_to_char_pos(event.offset)
        self.selection_start = char_pos
        self.selection_end = char_pos
        self.is_selecting = True

        self._log_debug(
            "selectable_static_mouse_down",
            offset=(event.offset.x, event.offset.y),
            char_pos=char_pos,
            text_length=len(self._text_content),
        )

        self._update_display()

    def on_mouse_move(self, event: MouseMove) -> None:
        """Handle mouse move during text selection."""
        if not self.is_selecting:
            return

        # Capture mouse on first drag movement (not on mouse_down)
        # This allows Click events to work normally for simple clicks
        if not self.mouse_captured:
            self.capture_mouse()
            self.mouse_captured = True

        # Update selection end position
        char_pos = self._offset_to_char_pos(event.offset)
        self.selection_end = char_pos

        self._log_debug(
            "selectable_static_mouse_move",
            offset=(event.offset.x, event.offset.y),
            char_pos=char_pos,
        )

        self._update_display()

    def on_mouse_up(self, event: MouseUp) -> None:
        """Handle mouse up to end text selection."""
        if self.is_selecting:
            self.is_selecting = False
            self.mouse_captured = False
            self.release_mouse()

            # Post message with selected text if any
            selected_text = self._get_selected_text()
            self._log_debug(
                "selectable_static_mouse_up",
                offset=(event.offset.x, event.offset.y),
                selected_length=len(selected_text),
                preview=selected_text[:80],
            )
            if selected_text:
                self.post_message(TextSelected(selected_text))
            else:
                # No text was selected, restore original focus state
                if not self._original_can_focus:
                    self.can_focus = False
                    self.blur()

    def on_key(self, event: Key) -> None:
        """Handle key events, especially Ctrl+C with priority."""
        if event.key == "ctrl+c":
            # Prevent the event from propagating further
            event.prevent_default()
            event.stop()
            # Call our smart copy action
            self.action_smart_copy()
        # Note: Static doesn't have on_key method, so we don't call super()

    def handle_smart_copy(self) -> bool:
        """Handle smart copy operation and return True if text was copied, False otherwise."""
        from gatekit.tui.clipboard import copy_to_clipboard, is_ssh_session, SSH_CLIPBOARD_HINT, SSH_CLIPBOARD_TOAST_TIMEOUT

        selected_text = self._get_selected_text()

        self._log_debug(
            "selectable_static_handle_smart_copy",
            has_selection=bool(selected_text),
            selection_length=len(selected_text),
            preview=selected_text[:80],
        )

        if selected_text:
            # Use shared clipboard utility (handles SSH sessions properly)
            success, error = copy_to_clipboard(self.app, selected_text)

            if success:
                self._log_debug(
                    "selectable_static_copy_success",
                    selection_length=len(selected_text),
                    preview=selected_text[:80],
                )
                # Show SSH-aware notification (no preview for SSH - too cluttered with hint)
                if is_ssh_session():
                    self.notify(
                        f"✅ Copied. Not working? {SSH_CLIPBOARD_HINT}",
                        timeout=SSH_CLIPBOARD_TOAST_TIMEOUT
                    )
                else:
                    preview = f'"{selected_text[:30]}{"..." if len(selected_text) > 30 else ""}"'
                    self.notify(f"📋 Copied: {preview}")
                return True
            else:
                self._log_debug(
                    "selectable_static_copy_failed",
                    error=error,
                )
                self.notify(f"❌ Copy failed: {error or 'Clipboard not available'}", severity="error")
                return False
        else:
            # No text selected
            self._log_debug("selectable_static_copy_no_selection")
            return False

    def action_smart_copy(self) -> None:
        """Legacy smart copy action - delegate to handle_smart_copy."""
        # Just attempt to copy - never quit the app
        # User must explicitly quit with Ctrl+Q or Escape
        self.handle_smart_copy()

    def _offset_to_char_pos(self, offset: Offset) -> int:
        """Convert mouse offset to character position in the text.

        This method maps visual (x, y) coordinates to an absolute character
        position in the underlying text. It accounts for soft-wrapping by
        using pre-calculated visual line boundaries.
        """
        if not self._text_content:
            return 0

        # Ensure visual lines are calculated
        if not self._visual_lines:
            self._recalculate_visual_lines()

        if not self._visual_lines:
            return min(offset.x, len(self._text_content))

        # Get the visual line for this y coordinate
        line_idx = min(max(offset.y, 0), len(self._visual_lines) - 1)
        line_start, line_end = self._visual_lines[line_idx]

        # Handle center alignment offset
        line_offset = 0
        line_len = line_end - line_start
        if hasattr(self, "styles") and hasattr(self.styles, "text_align"):
            if str(self.styles.text_align) == "center" and self.size:
                widget_width = self.size.width
                if widget_width > line_len:
                    line_offset = (widget_width - line_len) // 2

        adjusted_x = max(0, offset.x - line_offset)
        char_in_line = min(adjusted_x, line_len)

        return min(line_start + char_in_line, len(self._text_content))

    def _get_selected_text(self) -> str:
        """Get the currently selected text."""

        if (
            self.selection_start is None
            or self.selection_end is None
            or self.selection_start == self.selection_end
        ):
            return ""

        start = min(self.selection_start, self.selection_end)
        end = max(self.selection_start, self.selection_end)

        return self._text_content[start:end]

    def _update_display(self) -> None:
        """Update the widget display to show selection highlighting."""
        if (
            self.selection_start is None
            or self.selection_end is None
            or self.selection_start == self.selection_end
        ):
            # No selection, restore original content (preserves styling like underlines)
            self.update(self._original_renderable, _preserve_original=False)
            return

        # Create highlighted text
        start = min(self.selection_start, self.selection_end)
        end = max(self.selection_start, self.selection_end)

        # Build Rich Text with selection highlighting
        text = Text()

        # Text before selection
        if start > 0:
            text.append(self._text_content[:start])

        # Selected text (highlighted)
        if end > start:
            text.append(
                self._text_content[start:end],
                style=Style(bgcolor="white", color="black"),
            )

        # Text after selection
        if end < len(self._text_content):
            text.append(self._text_content[end:])

        # Update with selection highlighting (don't overwrite original)
        self.update(text, _preserve_original=False)

        # Show tooltip if text is selected and we haven't shown it yet
        if end > start and not self._tooltip_shown:
            self._show_copy_tooltip()
            self._tooltip_shown = True

    def _show_copy_tooltip(self) -> None:
        """Show a tooltip to inform the user about Ctrl+C copy functionality."""
        import platform

        # Platform-specific message (Mac users need to know Ctrl works, not Cmd)
        if platform.system() == "Darwin":
            message = "💡 Text selected. Press Ctrl+C to copy (not Cmd+C)"
        else:
            message = "💡 Text selected. Press Ctrl+C to copy"

        self.notify(message, title="Copy Tip", timeout=10.0)

    def clear_selection(self) -> None:
        """Clear the current text selection."""
        self.selection_start = None
        self.selection_end = None
        self.is_selecting = False
        self.mouse_captured = False
        self._tooltip_shown = False  # Reset tooltip state

        # Restore original focus state if we temporarily enabled it
        if not self._original_can_focus:
            self.can_focus = False
            # Blur the widget if it shouldn't be focusable
            self.blur()

        self._update_display()

    def select_all(self) -> None:
        """Select all text in the widget."""
        if self._text_content:
            self.selection_start = 0
            self.selection_end = len(self._text_content)
            self._update_display()

            # Post message with selected text
            self.post_message(TextSelected(self._text_content))
