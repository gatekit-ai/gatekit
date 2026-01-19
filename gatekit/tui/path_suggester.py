"""Path suggester for directory autocomplete in Textual applications."""

import os
from pathlib import Path
from typing import Optional

from textual.binding import Binding
from textual.suggester import Suggester
from textual.widgets import Input


class PathSuggester(Suggester):
    """A suggester that provides directory path completions."""

    def __init__(self, *, use_cache: bool = True, case_sensitive: bool = True):
        """Initialize the path suggester.

        Args:
            use_cache: Whether to cache suggestion results
            case_sensitive: Whether path matching is case sensitive (typically True on Unix-like systems)
        """
        super().__init__(use_cache=use_cache, case_sensitive=case_sensitive)

    async def get_suggestion(self, value: str) -> Optional[str]:
        """Get a directory path completion for the given input.

        Args:
            value: The current input value (partial path)

        Returns:
            A suggested completion path, or None if no suggestion available
        """
        if not value:
            return None

        try:
            # Handle special cases
            if value == "~":
                return str(Path.home())

            # Expand user home directory and resolve relative paths
            expanded_path = Path(value).expanduser()

            # If the path ends with a separator, we're looking for completions in that directory
            if value.endswith(os.sep) or value.endswith("/"):
                parent_dir = expanded_path
                prefix = ""
            else:
                parent_dir = expanded_path.parent
                prefix = expanded_path.name

            # Make sure the parent directory exists and is accessible
            if not parent_dir.exists() or not parent_dir.is_dir():
                return None

            try:
                # Get all directories in the parent directory
                directories = [
                    item
                    for item in parent_dir.iterdir()
                    if item.is_dir() and not item.name.startswith(".")
                ]

                # Filter directories that start with our prefix
                if prefix:
                    if self.case_sensitive:
                        matching_dirs = [
                            d for d in directories if d.name.startswith(prefix)
                        ]
                    else:
                        prefix_lower = prefix.lower()
                        matching_dirs = [
                            d
                            for d in directories
                            if d.name.lower().startswith(prefix_lower)
                        ]
                else:
                    matching_dirs = directories

                if not matching_dirs:
                    return None

                # Sort alphabetically and take the first match
                matching_dirs.sort(key=lambda x: x.name.lower())
                suggested_dir = matching_dirs[0]

                # Build the full suggested path
                if value.endswith(os.sep) or value.endswith("/"):
                    # User is looking for subdirectories
                    suggestion = str(suggested_dir) + os.sep
                else:
                    # Complete the current directory name
                    suggestion = str(suggested_dir)

                return suggestion

            except (PermissionError, OSError):
                # Can't read the directory, no suggestions available
                return None

        except (OSError, ValueError):
            # Invalid path format or other error
            return None


class PathSuggesterWithCommonPaths(PathSuggester):
    """Extended path suggester that includes common system paths."""

    def __init__(self, common_paths: Optional[list[str]] = None, **kwargs):
        """Initialize with common paths.

        Args:
            common_paths: List of common paths to suggest (e.g., ["~/.config", "/etc"])
            **kwargs: Arguments passed to parent PathSuggester
        """
        super().__init__(**kwargs)
        self.common_paths = common_paths or [
            "~",
            "~/Documents",
            "~/Desktop",
            "~/.config",
            "configs",
            "./configs",
            "../configs",
            "/etc",
            "/usr/local/etc",
        ]

    async def get_suggestion(self, value: str) -> Optional[str]:
        """Get path suggestion, checking common paths first."""
        # First try common paths if the input is short
        if len(value) <= 2:
            for common_path in self.common_paths:
                expanded = str(Path(common_path).expanduser())
                if self.case_sensitive:
                    if expanded.startswith(value):
                        return expanded
                else:
                    if expanded.lower().startswith(value.lower()):
                        return expanded

        # Fall back to normal directory completion
        return await super().get_suggestion(value)


class PathInput(Input):
    """Custom Input widget that uses Tab key for accepting autocomplete suggestions."""

    BINDINGS = [
        # Keep all the default Input bindings
        Binding("left", "cursor_left", "Move cursor left", show=False),
        Binding(
            "shift+left", "cursor_left(True)", "Move cursor left and select", show=False
        ),
        Binding("ctrl+left", "cursor_left_word", "Move cursor left a word", show=False),
        Binding(
            "ctrl+shift+left",
            "cursor_left_word(True)",
            "Move cursor left a word and select",
            show=False,
        ),
        Binding(
            "right",
            "cursor_right",
            "Move cursor right or accept completion",
            show=False,
        ),
        Binding(
            "shift+right",
            "cursor_right(True)",
            "Move cursor right and select",
            show=False,
        ),
        Binding(
            "ctrl+right", "cursor_right_word", "Move cursor right a word", show=False
        ),
        Binding(
            "ctrl+shift+right",
            "cursor_right_word(True)",
            "Move cursor right a word and select",
            show=False,
        ),
        Binding("backspace", "delete_left", "Delete character left", show=False),
        Binding("home,ctrl+a", "home", "Go to start", show=False),
        Binding("end,ctrl+e", "end", "Go to end", show=False),
        Binding("shift+home", "home(True)", "Select line start", show=False),
        Binding("shift+end", "end(True)", "Select line end", show=False),
        Binding("delete,ctrl+d", "delete_right", "Delete character right", show=False),
        Binding("enter", "submit", "Submit", show=False),
        Binding(
            "ctrl+w", "delete_left_word", "Delete left to start of word", show=False
        ),
        Binding("ctrl+u", "delete_left_all", "Delete all to the left", show=False),
        Binding(
            "ctrl+f", "delete_right_word", "Delete right to start of word", show=False
        ),
        Binding("ctrl+k", "delete_right_all", "Delete all to the right", show=False),
        Binding("ctrl+x", "cut", "Cut selected text", show=False),
        Binding("ctrl+c", "copy", "Copy selected text", show=False),
        Binding("ctrl+v", "paste", "Paste text from the clipboard", show=False),
        # CUSTOM: Override Tab to accept autocomplete instead of focus navigation
        Binding("tab", "accept_suggestion", "Accept suggestion", show=False),
    ]

    def action_accept_suggestion(self) -> None:
        """Accept the current autocomplete suggestion using Tab key."""
        # Check if there's actually a suggestion to accept
        # In Textual's Input widget, suggestions are shown as grayed-out text
        # We can check if there's a suggestion by seeing if cursor_right would do anything
        current_value = self.value
        current_cursor = self.cursor_position

        # Try accepting suggestion with cursor_right
        self.action_cursor_right()

        # If nothing changed (no suggestion was accepted), treat Tab as navigation
        if self.value == current_value and self.cursor_position == current_cursor:
            # No suggestion was available, so Tab should move focus to directory tree
            # This is the same as the Down arrow behavior
            self.action_focus_tree()
        # If something changed, the suggestion was accepted and we're done

    def watch_value(self, value: str) -> None:
        """Watch for value changes and log them for debugging."""
        # Get the old value before updating
        old_value = getattr(self, "_previous_value", "")
        self._previous_value = value

        # Log input changes for debugging
        from .debug import get_debug_logger

        logger = get_debug_logger()
        if logger and logger.enabled and old_value != value:
            # Determine the field name based on widget ID or context
            field_name = "path input"
            if hasattr(self, "id") and self.id:
                field_name = self.id.replace("_", " ")

            # Safely get screen (may be None if widget not mounted yet)
            try:
                screen = self.screen
            except Exception:
                screen = None

            logger.log_input_change(
                widget=self,
                old_text=old_value,
                new_text=value,
                field_name=field_name,
                screen=screen,
            )
