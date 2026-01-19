"""Directory browser modal using Textual's DirectoryTree widget."""

from pathlib import Path
from typing import Iterable, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Static

from ..path_suggester import PathSuggesterWithCommonPaths, PathInput


class ModalPathInput(PathInput):
    """PathInput with custom Up/Down arrow behavior for modal navigation."""

    BINDINGS = PathInput.BINDINGS + [
        # Add Up arrow to move focus to cancel button (complete the cycle)
        Binding("up", "focus_cancel", "Move to cancel button", show=False),
        # Add Down arrow to move focus to directory tree
        Binding("down", "focus_tree", "Move to directory tree", show=False),
    ]

    def action_focus_cancel(self) -> None:
        """Move focus to the cancel button."""
        try:
            cancel_button = self.screen.query_one("#cancel_btn", ModalCancelButton)
            cancel_button.focus()
        except Exception:
            pass

    def action_focus_tree(self) -> None:
        """Move focus to the directory tree."""
        tree = self.screen.query_one("#directory_tree", ModalDirectoryTree)
        tree.focus()


class DirectoryOnlyTree(DirectoryTree):
    """DirectoryTree subclass that shows only directories."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        """Filter to show only directories, hide files. Add '..' for parent navigation."""
        # Get only directories from the provided paths
        directories = [path for path in paths if path.is_dir()]

        # Add '..' entry for parent navigation if we're not at filesystem root
        current_path = Path(self.path)
        if current_path.parent != current_path:  # Not at filesystem root
            # Create a fake '..' path that we'll handle specially
            parent_indicator = current_path / ".."
            directories.insert(0, parent_indicator)

        return directories


class ModalDirectoryTree(DirectoryOnlyTree):
    """DirectoryTree with custom Up arrow behavior to return focus to input when at top."""

    BINDINGS = [
        # Copy all the DirectoryTree bindings except "up", then add our custom up binding
        Binding("shift+left", "cursor_parent", "Cursor to parent", show=False),
        Binding(
            "shift+right",
            "cursor_parent_next_sibling",
            "Cursor to next ancestor",
            show=False,
        ),
        Binding(
            "shift+up",
            "cursor_previous_sibling",
            "Cursor to previous sibling",
            show=False,
        ),
        Binding(
            "shift+down", "cursor_next_sibling", "Cursor to next sibling", show=False
        ),
        Binding("enter", "select_cursor", "Select", show=False),
        Binding("space", "toggle_node", "Toggle", show=False),
        Binding(
            "shift+space", "toggle_expand_all", "Expand or collapse all", show=False
        ),
        # Custom Up behavior - move focus to input when at top
        Binding("up", "cursor_up_or_focus_input", "Move up or to input", show=False),
        # Custom Down behavior - move focus to Select button when at bottom
        Binding(
            "down", "cursor_down_or_focus_button", "Move down or to button", show=False
        ),
    ]

    def action_cursor_up_or_focus_input(self) -> None:
        """Move cursor up, or if at top, move focus back to path input."""
        # Check if we're at the topmost item (cursor_line is 0-indexed)
        if self.cursor_line <= 0:
            # Move focus back to path input
            try:
                path_input = self.screen.query_one("#path_input", ModalPathInput)
                path_input.focus()
            except Exception:
                # Fallback to normal up behavior if something goes wrong
                self.action_cursor_up()
        else:
            # Normal up behavior
            self.action_cursor_up()

    def action_cursor_down_or_focus_button(self) -> None:
        """Move cursor down, or if at bottom, move focus to Select button."""
        # Check if we're at the bottommost item
        # We need to check if there are any more items below the current cursor
        current_line = self.cursor_line

        # Try to move down normally first
        self.action_cursor_down()

        # If cursor didn't move (we were already at bottom), focus the Select button
        if self.cursor_line == current_line:
            try:
                select_button = self.screen.query_one("#select_btn", ModalSelectButton)
                select_button.focus()
            except Exception:
                # If something goes wrong, just stay where we are
                pass


class ModalSelectButton(Button):
    """Select button with custom navigation behavior."""

    BINDINGS = Button.BINDINGS + [
        Binding("up", "focus_tree", "Move to directory tree", show=False),
        Binding("left", "focus_tree", "Move to directory tree", show=False),
        Binding("down", "focus_cancel", "Move to cancel button", show=False),
        Binding("right", "focus_cancel", "Move to cancel button", show=False),
    ]

    def action_focus_tree(self) -> None:
        """Move focus back to directory tree (at bottom)."""
        try:
            tree = self.screen.query_one("#directory_tree", ModalDirectoryTree)
            tree.focus()
            # Move cursor to bottom of tree for intuitive navigation
            tree.action_cursor_end()
        except Exception:
            pass

    def action_focus_cancel(self) -> None:
        """Move focus to cancel button."""
        try:
            cancel_button = self.screen.query_one("#cancel_btn", ModalCancelButton)
            cancel_button.focus()
        except Exception:
            pass


class ModalCancelButton(Button):
    """Cancel button with custom navigation behavior."""

    BINDINGS = Button.BINDINGS + [
        Binding("up", "focus_select", "Move to select button", show=False),
        Binding("left", "focus_select", "Move to select button", show=False),
        Binding("down", "focus_input", "Move to path input", show=False),
        Binding("right", "focus_input", "Move to path input", show=False),
    ]

    def action_focus_select(self) -> None:
        """Move focus to select button."""
        try:
            select_button = self.screen.query_one("#select_btn", ModalSelectButton)
            select_button.focus()
        except Exception:
            pass

    def action_focus_input(self) -> None:
        """Move focus to path input."""
        try:
            path_input = self.screen.query_one("#path_input", ModalPathInput)
            path_input.focus()
        except Exception:
            pass


class DirectoryBrowserModal(ModalScreen[Optional[Path]]):
    """Modal screen for browsing and selecting directories using a tree view."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    DirectoryBrowserModal {
        align: center middle;
    }
    
    .dialog {
        width: 80;
        height: 35;
        background: $surface;
        border: heavy $primary;
        padding: 1;
    }
    
    .title {
        text-align: center;
        margin-bottom: 1;
        color: $primary;
    }
    
    .path-input-section {
        height: 6;
        margin-bottom: 1;
    }
    
    .path-input-label {
        margin-bottom: 1;
    }
    
    .path-input {
        margin-bottom: 1;
    }
    
    .path-input.-valid {
        border: solid $success;
    }
    
    .path-input.-invalid {
        border: solid $error;
    }
    
    .tree-container {
        height: 1fr;
        margin-bottom: 1;
        border: solid $secondary;
    }
    
    .button-row {
        height: 3;
        align: center middle;
    }
    
    Button {
        margin: 0 1;
    }
    
    DirectoryTree {
        height: 1fr;
    }
    
    .help-text {
        color: $text-muted;
        text-style: italic;
    }
    """

    def __init__(self, start_directory: Path):
        """Initialize the directory browser modal.

        Args:
            start_directory: Directory to start browsing from
        """
        super().__init__()
        self.start_directory = start_directory
        self.selected_directory: Optional[Path] = (
            start_directory  # Pre-select the starting directory
        )
        # Start the tree from the current directory - users can navigate up using native tree controls
        self.root_directory = start_directory

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(classes="dialog"):
            yield Static("Select Directory", classes="title")

            # Path input section
            with Container(classes="path-input-section"):
                yield Static(
                    "Type path directly or select from tree below:",
                    classes="path-input-label",
                )
                yield ModalPathInput(
                    value=str(self.start_directory),
                    placeholder="Type directory path... (Tab to autocomplete)",
                    suggester=PathSuggesterWithCommonPaths(),
                    id="path_input",
                    classes="path-input",
                    select_on_focus=False,
                )
                yield Static(
                    "💡 Use Tab to accept autocomplete or move to tree",
                    classes="help-text",
                )

            # Directory tree - start from root (parent) directory to allow up/down navigation
            with Container(classes="tree-container"):
                yield ModalDirectoryTree(str(self.root_directory), id="directory_tree")

            # Action buttons
            with Horizontal(classes="button-row"):
                yield ModalSelectButton("Select", id="select_btn", variant="primary")
                yield ModalCancelButton("Cancel", id="cancel_btn")

    def on_mount(self) -> None:
        """Initialize the modal when mounted."""
        # Focus the path input field first for immediate typing
        path_input = self.query_one("#path_input", ModalPathInput)
        path_input.focus()

        # Set initial selection to the starting directory
        if self.start_directory.exists():
            self.selected_directory = self.start_directory
            self._validate_path_input(str(self.start_directory))

    @on(ModalPathInput.Changed, "#path_input")
    def on_path_input_changed(self, event: ModalPathInput.Changed) -> None:
        """Handle path input changes for validation and tree synchronization."""
        path_value = event.value.strip()
        self._validate_path_input(path_value)

        # Update selected directory if path is valid
        if path_value:
            try:
                expanded_path = Path(path_value).expanduser().resolve()
                if expanded_path.exists() and expanded_path.is_dir():
                    self.selected_directory = expanded_path
                    # Try to update tree view to show this directory
                    self._update_tree_to_path(expanded_path)
            except (OSError, ValueError):
                pass  # Invalid path, keep current selection

    @on(ModalPathInput.Submitted, "#path_input")
    def on_path_input_submitted(self, event: ModalPathInput.Submitted) -> None:
        """Handle Enter key in path input."""
        self._handle_select_action()

    @on(DirectoryTree.DirectorySelected)
    def on_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """Handle directory selection in the tree."""
        # Check if user selected the '..' parent directory indicator
        if event.path.name == "..":
            # Navigate to parent directory by changing the tree's path
            tree = self.query_one("#directory_tree", DirectoryTree)
            current_path = Path(tree.path)
            parent_path = current_path.parent

            if parent_path != current_path:  # Make sure we can go up
                tree.path = str(parent_path)
                self.selected_directory = parent_path
                # Update the path input to reflect tree selection
                path_input = self.query_one("#path_input", ModalPathInput)
                path_input.value = str(parent_path)
        else:
            # Normal directory selection - update both selected directory and input field
            self.selected_directory = event.path
            path_input = self.query_one("#path_input", ModalPathInput)
            path_input.value = str(event.path)

    @on(ModalSelectButton.Pressed, "#select_btn")
    def on_select_button(self) -> None:
        """Handle select button press."""
        self._handle_select_action()

    @on(ModalCancelButton.Pressed, "#cancel_btn")
    def on_cancel_button(self) -> None:
        """Handle cancel button press."""
        self.dismiss(None)

    def action_cancel(self) -> None:
        """Handle Escape key press to cancel modal."""
        self.dismiss(None)

    def _validate_path_input(self, path_str: str) -> None:
        """Validate the path input and update visual feedback."""
        path_input = self.query_one("#path_input", ModalPathInput)

        if not path_str:
            path_input.remove_class("-valid", "-invalid")
            return

        try:
            path = Path(path_str).expanduser()
            if path.exists() and path.is_dir():
                path_input.remove_class("-invalid")
                path_input.add_class("-valid")
            else:
                path_input.remove_class("-valid")
                path_input.add_class("-invalid")
        except (OSError, ValueError):
            path_input.remove_class("-valid")
            path_input.add_class("-invalid")

    def _update_tree_to_path(self, target_path: Path) -> None:
        """Update the tree view to navigate to and show the target directory."""
        try:
            tree = self.query_one("#directory_tree", ModalDirectoryTree)
            current_tree_path = Path(tree.path)

            # For true bidirectional sync, we want to navigate the tree to show the target directory

            # If the target is a child of the current tree path, expand to show it
            if target_path.is_relative_to(current_tree_path):
                # Target is within current tree - just select it if visible
                # Set the tree's path to the target directory to navigate there
                tree.path = str(target_path)
            else:
                # Target is outside current tree - change tree root to show target
                # Set tree to the target directory itself
                tree.path = str(target_path)

        except (OSError, ValueError):
            # If we can't navigate to target directly, try showing its parent
            try:
                tree = self.query_one("#directory_tree", ModalDirectoryTree)
                if target_path.parent.exists():
                    tree.path = str(target_path.parent)
            except Exception:
                pass  # Give up if parent doesn't work either

    def _handle_select_action(self) -> None:
        """Handle the select action from button or Enter key."""
        # First try to use the path from the input field
        path_input = self.query_one("#path_input", ModalPathInput)
        path_str = path_input.value.strip()

        if path_str:
            try:
                selected_path = Path(path_str).expanduser().resolve()
                if selected_path.exists() and selected_path.is_dir():
                    self.dismiss(selected_path)
                    return
            except (OSError, ValueError):
                pass  # Fall through to other options

        # Fall back to selected directory from tree or other selection
        if (
            self.selected_directory
            and self.selected_directory.exists()
            and self.selected_directory.is_dir()
        ):
            self.dismiss(self.selected_directory)
        else:
            # Last resort: use current tree directory
            tree = self.query_one("#directory_tree", DirectoryTree)
            current_path = Path(tree.path)
            if current_path.exists() and current_path.is_dir():
                self.dismiss(current_path)
            else:
                # Show error - invalid selection
                return
