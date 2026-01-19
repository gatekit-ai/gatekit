"""Custom widget for file path input with browse button."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input
from textual.message import Message


def resolve_start_directory(
    value: str,
    start_directory: Optional[Path],
    config_dir: Optional[Path],
) -> Path:
    """Resolve the starting directory for the file picker.

    Args:
        value: Current path value from the input field
        start_directory: Explicit override directory (highest priority)
        config_dir: Config file directory for resolving relative paths

    Returns:
        The directory to open the file picker in
    """
    # Priority 1: Explicit start_directory override
    if start_directory and start_directory.exists():
        return start_directory

    # Priority 2: Derive from current value
    if value:
        # Expand ~ and environment variables
        expanded_value = os.path.expandvars(os.path.expanduser(value))
        expanded_path = Path(expanded_value)

        if expanded_path.is_absolute():
            # Absolute path (including expanded ~ and env vars)
            if expanded_path.parent.exists():
                return expanded_path.parent
            else:
                return config_dir or Path.cwd()
        elif config_dir:
            # Relative path with config_dir - resolve relative to config
            resolved_path = (config_dir / expanded_path).resolve()
            if resolved_path.parent.exists():
                return resolved_path.parent
            else:
                return config_dir
        else:
            # Relative path without config_dir - try cwd
            resolved_path = (Path.cwd() / expanded_path).resolve()
            if resolved_path.parent.exists():
                return resolved_path.parent
            else:
                return Path.cwd()

    # Priority 3: No value - use config_dir or cwd
    return config_dir or Path.cwd()


class FilePathField(Horizontal):
    """Widget combining an Input field with a Browse button for file paths.

    When the Browse button is clicked, a FileSave modal is shown allowing
    the user to select a file path. The selected path is then set in the
    Input field.
    """

    DEFAULT_CSS = """
    FilePathField {
        height: auto;
        width: 100%;
    }

    FilePathField > Input {
        width: 1fr;
    }

    FilePathField > Button {
        width: auto;
        min-width: 10;
        margin-left: 1;
    }
    """

    class Changed(Message):
        """Posted when the file path value changes."""

        def __init__(self, file_path_field: "FilePathField", value: str) -> None:
            super().__init__()
            self.file_path_field = file_path_field
            self.value = value
            self.input = file_path_field._input  # For compatibility with Input.Changed

    def __init__(
        self,
        value: str = "",
        placeholder: str = "",
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
        start_directory: Optional[Path] = None,
        config_dir: Optional[Path] = None,
    ) -> None:
        """Initialize the FilePathField.

        Args:
            value: Initial file path value
            placeholder: Placeholder text for the input
            name: Widget name
            id: Widget ID
            classes: CSS classes
            start_directory: Starting directory for the file picker (explicit override)
            config_dir: Config file directory for resolving relative paths
        """
        super().__init__(name=name, id=id, classes=classes)
        self._initial_value = value
        self._placeholder = placeholder
        self._start_directory = start_directory
        self._config_dir = config_dir
        self._input: Input = None  # Will be set in compose

    def compose(self) -> ComposeResult:
        """Compose the widget."""
        self._input = Input(
            value=self._initial_value,
            placeholder=self._placeholder,
            id=f"{self.id}_input" if self.id else None,
        )
        yield self._input
        yield Button("Browse...", id=f"{self.id}_browse" if self.id else None)

    @property
    def value(self) -> str:
        """Get the current file path value."""
        return self._input.value if self._input else self._initial_value

    @value.setter
    def value(self, new_value: str) -> None:
        """Set the file path value."""
        if self._input:
            self._input.value = new_value

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle browse button click."""
        event.stop()

        from textual_fspicker import FileSave

        start_dir = resolve_start_directory(
            self.value, self._start_directory, self._config_dir
        )

        # Get default filename from current value
        default_file = Path(self.value).name if self.value else ""

        # Show file picker
        selected_path = await self.app.push_screen_wait(
            FileSave(
                location=start_dir,
                title="Select Output File",
                default_file=default_file,
            )
        )

        if selected_path is not None:
            self._input.value = str(selected_path)
            # Post changed message
            self.post_message(self.Changed(self, str(selected_path)))

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes and re-post as FilePathField.Changed."""
        event.stop()
        self.post_message(self.Changed(self, event.value))
