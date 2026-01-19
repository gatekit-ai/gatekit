"""TUI Debug Logger - Runtime debugging infrastructure for Gatekit TUI.

This module provides the core logging capabilities used during TUI operation
to capture user interactions, widget state changes, and navigation events.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import glob

from textual.widget import Widget
from textual.screen import Screen

from ..platform_paths import get_user_log_dir


class TUIDebugLogger:
    """Debug logger for TUI events and state changes."""

    def __init__(self, enabled: bool = False, log_path: Optional[str] = None):
        """Initialize the debug logger.

        Args:
            enabled: Whether debugging is enabled
            log_path: Optional custom log file path (defaults to system temp dir)
        """
        self.enabled = enabled
        self.session_id = str(uuid.uuid4())

        if not enabled:
            self.log_file = None
            return

        # Set up log file path
        if log_path:
            self.log_path = Path(log_path)
        else:
            log_dir = get_user_log_dir('gatekit')
            self.log_path = log_dir / "gatekit_tui_debug.log"

        # Open log file for writing (overwrite existing)
        try:
            # Ensure parent directory exists
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = open(self.log_path, "w", encoding="utf-8")
            # Log session start and print debug info to stderr
            self._write_event(
                {
                    "event_id": str(uuid.uuid4()),
                    "timestamp": self._get_timestamp(),
                    "session_id": self.session_id,
                    "event_type": "session_start",
                    "screen": None,
                    "widget": None,
                    "context": {"log_path": str(self.log_path)},
                    "data": {},
                }
            )

            # Print debug info to stderr (visible before TUI starts)
            import sys

            print("🔍 TUI Debug Mode Enabled", file=sys.stderr)
            print(f"📝 Debug log: {self.log_path}", file=sys.stderr)
            print("⌨️  Press Ctrl+Shift+D for state dump", file=sys.stderr)
            print("", file=sys.stderr)  # Extra newline before TUI starts
        except Exception:
            # Graceful degradation if logging fails
            self.log_file = None
            self.enabled = False

    def _get_timestamp(self) -> str:
        """Get ISO 8601 timestamp in UTC."""
        return datetime.now(timezone.utc).isoformat()

    def _write_event(self, event: Dict[str, Any]) -> None:
        """Write an event to the log file."""
        if not self.enabled or not self.log_file:
            return

        try:
            json_line = json.dumps(event, ensure_ascii=False)
            self.log_file.write(json_line + "\n")
            self.log_file.flush()

            # Check if log file needs rotation (10MB = 10 * 1024 * 1024 bytes)
            self._check_log_rotation()
        except Exception:
            # Ignore logging errors to prevent disrupting TUI
            pass

    def _check_log_rotation(self) -> None:
        """Check if log file needs rotation and rotate if necessary."""
        try:
            if not self.log_file:
                return

            # Check current file size
            current_size = self.log_path.stat().st_size
            max_size = 10 * 1024 * 1024  # 10MB

            if current_size >= max_size:
                self._rotate_log_file()
        except Exception:
            # Ignore rotation errors to prevent disrupting TUI
            pass

    def _rotate_log_file(self) -> None:
        """Rotate the current log file."""
        try:
            # Close current file
            self.log_file.close()

            # Create timestamped backup name
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = self.log_path.with_suffix(f".{timestamp_str}.log")

            # Rename current log to backup
            if self.log_path.exists():
                self.log_path.rename(backup_path)

            # Open new log file
            self.log_file = open(self.log_path, "w", encoding="utf-8")

            # Log rotation event
            self._write_event(
                {
                    "event_id": str(uuid.uuid4()),
                    "timestamp": self._get_timestamp(),
                    "session_id": self.session_id,
                    "event_type": "log_rotation",
                    "screen": None,
                    "widget": None,
                    "context": {"backup_path": str(backup_path)},
                    "data": {},
                }
            )
        except Exception:
            # If rotation fails, try to continue with current file or disable logging
            try:
                if not self.log_file or self.log_file.closed:
                    self.log_file = open(self.log_path, "w", encoding="utf-8")
            except Exception:
                self.enabled = False
                self.log_file = None

    def _get_widget_info(self, widget: Optional[Widget]) -> Optional[Dict[str, Any]]:
        """Extract widget information for logging."""
        if not widget:
            return None

        try:
            # Get widget path (parent chain)
            path = []
            current = widget
            max_depth = 20  # Prevent infinite loops with Mock objects
            depth = 0

            while current and depth < max_depth:
                if hasattr(current, "__class__"):
                    path.append(current.__class__.__name__)
                else:
                    path.append(str(type(current).__name__))

                # Check for parent, but avoid infinite loops with Mock objects
                try:
                    parent = getattr(current, "parent", None)
                    if parent is None or parent is current:
                        break
                    current = parent
                except (AttributeError, RecursionError):
                    break

                if isinstance(current, Screen):
                    break

                depth += 1

            return {
                "id": getattr(widget, "id", None),
                "class": widget.__class__.__name__,
                "path": list(reversed(path)),  # Root to target order
            }
        except Exception:
            # Fallback to basic info
            return {
                "id": getattr(widget, "id", None),
                "class": widget.__class__.__name__,
                "path": [],
            }

    def _get_screen_name(self, screen: Optional[Any]) -> Optional[str]:
        """Get screen name for logging."""
        if not screen:
            return None
        try:
            return screen.__class__.__name__
        except Exception:
            return str(type(screen).__name__)

    def log_event(
        self,
        event_type: str,
        widget: Optional[Widget] = None,
        screen: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None,
        **data,
    ) -> None:
        """Log a generic TUI event.

        Args:
            event_type: Type of event (focus_change, navigation, etc.)
            widget: Widget involved in the event
            screen: Screen where event occurred
            context: Additional context information
            **data: Additional data to include in the event
        """
        if not self.enabled:
            return

        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": self._get_timestamp(),
            "session_id": self.session_id,
            "event_type": event_type,
            "screen": self._get_screen_name(screen),
            "widget": self._get_widget_info(widget),
            "context": context or {},
            "data": data,
        }

        self._write_event(event)

    def log_focus_change(
        self,
        old_widget: Optional[Widget],
        new_widget: Optional[Widget],
        screen: Optional[Any] = None,
        reason: str = "unknown",
    ) -> None:
        """Log a focus change event.

        Args:
            old_widget: Previously focused widget
            new_widget: Newly focused widget
            screen: Screen where focus change occurred
            reason: Reason for focus change (user_tab, remembered, fallback, etc.)
        """
        self.log_event(
            "focus_change",
            widget=new_widget,
            screen=screen,
            context={"reason": reason},
            old_widget=self._get_widget_info(old_widget),
            new_widget=self._get_widget_info(new_widget),
        )

    def log_navigation(
        self,
        direction: str,
        from_container: Optional[str],
        to_container: Optional[str],
        screen: Optional[Any] = None,
        widget: Optional[Widget] = None,
    ) -> None:
        """Log a navigation event.

        Args:
            direction: Navigation direction (next, previous)
            from_container: Container navigated from
            to_container: Container navigated to
            screen: Screen where navigation occurred
            widget: Widget that received focus after navigation
        """
        self.log_event(
            "navigation",
            widget=widget,
            screen=screen,
            context={
                "direction": direction,
                "from_container": from_container,
                "to_container": to_container,
            },
        )

    def log_state_change(
        self,
        component: str,
        old_value: Any,
        new_value: Any,
        screen: Optional[Any] = None,
        widget: Optional[Widget] = None,
    ) -> None:
        """Log a state change event.

        Args:
            component: Component that changed (focus_memory, container_index, etc.)
            old_value: Previous value
            new_value: New value
            screen: Screen where state change occurred
            widget: Widget associated with state change
        """
        self.log_event(
            "state_change",
            widget=widget,
            screen=screen,
            context={"component": component},
            old_value=old_value,
            new_value=new_value,
        )

    def log_user_input(
        self,
        input_type: str,
        key: Optional[str] = None,
        screen: Optional[Any] = None,
        widget: Optional[Widget] = None,
        **context,
    ) -> None:
        """Log a user input event.

        Args:
            input_type: Type of input (keypress, mouse, etc.)
            key: Key pressed (if keyboard input)
            screen: Screen where input occurred
            widget: Widget that handled the input
            **context: Additional context about the input
        """
        self.log_event(
            "user_input",
            widget=widget,
            screen=screen,
            context={"input_type": input_type, "key": key, **context},
        )

    def log_widget_lifecycle(
        self,
        lifecycle_event: str,
        widget: Optional[Widget] = None,
        screen: Optional[Any] = None,
        **context,
    ) -> None:
        """Log a widget lifecycle event.

        Args:
            lifecycle_event: Type of lifecycle event (mount, unmount, update, etc.)
            widget: Widget involved in the lifecycle event
            screen: Screen where lifecycle event occurred
            **context: Additional context about the lifecycle event
        """
        self.log_event(
            "widget_lifecycle",
            widget=widget,
            screen=screen,
            context={"lifecycle_event": lifecycle_event, **context},
        )

    def log_value_change(
        self,
        widget: Optional[Widget] = None,
        old_value: Any = None,
        new_value: Any = None,
        value_type: str = "unknown",
        screen: Optional[Any] = None,
        user_action: str = "unknown",
        **context,
    ) -> None:
        """Log a widget value change event.

        Args:
            widget: Widget whose value changed
            old_value: Previous value
            new_value: New value
            value_type: Type of value (checkbox, input, dropdown, etc.)
            screen: Screen where value change occurred
            user_action: Description of what the user did (toggled, typed, selected, etc.)
            **context: Additional context about the value change
        """
        self.log_event(
            "value_change",
            widget=widget,
            screen=screen,
            context={"value_type": value_type, "user_action": user_action, **context},
            old_value=old_value,
            new_value=new_value,
        )

    def log_checkbox_toggle(
        self,
        widget: Optional[Widget] = None,
        old_checked: bool = False,
        new_checked: bool = False,
        plugin_name: Optional[str] = None,
        plugin_type: Optional[str] = None,
        screen: Optional[Any] = None,
        **context,
    ) -> None:
        """Log a checkbox toggle event with plugin context.

        Args:
            widget: Checkbox widget that was toggled
            old_checked: Previous checkbox state
            new_checked: New checkbox state
            plugin_name: Name of the plugin being toggled
            plugin_type: Type of plugin (security, auditing)
            screen: Screen where toggle occurred
            **context: Additional context
        """
        action_description = f"{'enabled' if new_checked else 'disabled'} {plugin_type} plugin '{plugin_name}'"

        self.log_event(
            "checkbox_toggle",
            widget=widget,
            screen=screen,
            context={
                "plugin_name": plugin_name,
                "plugin_type": plugin_type,
                "action_description": action_description,
                **context,
            },
            old_checked=old_checked,
            new_checked=new_checked,
        )

    def log_input_change(
        self,
        widget: Optional[Widget] = None,
        old_text: str = "",
        new_text: str = "",
        field_name: Optional[str] = None,
        screen: Optional[Any] = None,
        **context,
    ) -> None:
        """Log an input field change event.

        Args:
            widget: Input widget that changed
            old_text: Previous text value
            new_text: New text value
            field_name: Name/purpose of the input field
            screen: Screen where input change occurred
            **context: Additional context
        """
        # Don't log empty changes or just cursor movements
        if old_text == new_text:
            return

        action_description = f"changed {field_name or 'input field'}"
        if len(new_text) > len(old_text):
            action_description = f"typed in {field_name or 'input field'}"
        elif len(new_text) < len(old_text):
            action_description = f"deleted from {field_name or 'input field'}"

        self.log_event(
            "input_change",
            widget=widget,
            screen=screen,
            context={
                "field_name": field_name,
                "action_description": action_description,
                "text_length_change": len(new_text) - len(old_text),
                **context,
            },
            old_text=old_text,
            new_text=new_text,
        )

    def log_selection_change(
        self,
        widget: Optional[Widget] = None,
        old_selection: Any = None,
        new_selection: Any = None,
        selection_type: str = "dropdown",
        screen: Optional[Any] = None,
        **context,
    ) -> None:
        """Log a selection change event (dropdown, list, etc.).

        Args:
            widget: Widget with selection that changed
            old_selection: Previous selection
            new_selection: New selection
            selection_type: Type of selection widget
            screen: Screen where selection change occurred
            **context: Additional context
        """
        action_description = f"selected '{new_selection}' in {selection_type}"

        self.log_event(
            "selection_change",
            widget=widget,
            screen=screen,
            context={
                "selection_type": selection_type,
                "action_description": action_description,
                **context,
            },
            old_selection=old_selection,
            new_selection=new_selection,
        )

    def dump_state(self, screen: Optional[Any] = None) -> str:
        """Create a comprehensive state dump.

        Args:
            screen: Screen to dump state for

        Returns:
            JSON string of the state dump
        """
        if not self.enabled:
            return "{}"

        try:
            state_data = {
                "timestamp": self._get_timestamp(),
                "session_id": self.session_id,
                "screen_type": self._get_screen_name(screen),
                "focused_widget": None,
                "navigation_state": {},
                "focus_memory": {},
                "widget_tree": {},
            }

            if screen:
                # Get focused widget info
                if hasattr(screen, "app") and hasattr(screen.app, "focused"):
                    state_data["focused_widget"] = self._get_widget_info(
                        screen.app.focused
                    )

                # Extract navigation state if available (ConfigEditorScreen specific)
                if hasattr(screen, "navigation_containers"):
                    container_names = [
                        c.get("name", "unknown") for c in screen.navigation_containers
                    ]
                    state_data["navigation_state"] = {
                        "current_container_index": getattr(
                            screen, "current_container_index", 0
                        ),
                        "container_names": container_names,
                    }

                # Extract focus memory if available
                if hasattr(screen, "container_focus_memory"):
                    # Convert widgets to widget info for serialization
                    focus_memory = {}
                    for container, widget in screen.container_focus_memory.items():
                        focus_memory[container] = self._get_widget_info(widget)
                    state_data["focus_memory"] = focus_memory

                # Extract widget tree (basic version)
                state_data["widget_tree"] = self._extract_widget_tree(screen)

            # Save state dump to file
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            log_dir = get_user_log_dir('gatekit')
            state_dump_path = log_dir / f"gatekit_tui_state_{timestamp_str}.json"

            try:
                with open(state_dump_path, "w", encoding="utf-8") as f:
                    json.dump(state_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass  # Ignore file writing errors

            # Also log the state dump as an event
            self.log_event(
                "state_dump",
                screen=screen,
                context={"state_dump_path": str(state_dump_path)},
                state_data=state_data,
            )

            return json.dumps(state_data, indent=2, ensure_ascii=False)

        except Exception as e:
            # Return error info on failure
            error_data = {
                "error": str(e),
                "timestamp": self._get_timestamp(),
                "session_id": self.session_id,
            }
            return json.dumps(error_data, indent=2, ensure_ascii=False)

    def _extract_widget_tree(self, root: Any) -> Dict[str, Any]:
        """Extract a simplified widget tree structure.

        Args:
            root: Root widget/screen to extract from

        Returns:
            Dictionary representation of the widget tree
        """
        try:
            tree = {
                "class": root.__class__.__name__,
                "id": getattr(root, "id", None),
                "can_focus": getattr(root, "can_focus", False),
                "visible": getattr(root, "visible", True),
                "children": [],
            }

            # Extract widget values for interactive elements
            class_name = root.__class__.__name__

            # Capture checkbox states
            if (
                "Checkbox" in class_name
                or hasattr(root, "value")
                and isinstance(getattr(root, "value", None), bool)
            ):
                tree["value"] = getattr(root, "value", None)
                tree["widget_type"] = "checkbox"

                # Extract plugin info from checkbox ID
                if hasattr(root, "id") and root.id and root.id.startswith("checkbox_"):
                    tree["plugin_name"] = root.id[9:]  # Remove 'checkbox_' prefix

            # Capture input field values
            elif (
                "Input" in class_name
                or hasattr(root, "value")
                and isinstance(getattr(root, "value", None), str)
            ):
                value = getattr(root, "value", None)
                if value is not None:
                    tree["value"] = value
                    tree["widget_type"] = "input"
                    tree["text_length"] = len(value) if isinstance(value, str) else 0

            # Capture selection states (for dropdowns, lists, etc.)
            elif hasattr(root, "selected") or hasattr(root, "current_selection"):
                selected = getattr(root, "selected", None) or getattr(
                    root, "current_selection", None
                )
                if selected is not None:
                    tree["selected"] = str(selected)
                    tree["widget_type"] = "selection"

            # Capture button states
            elif "Button" in class_name:
                tree["widget_type"] = "button"
                if hasattr(root, "label"):
                    tree["label"] = str(root.label)

            # Capture static text content (for labels, etc.)
            elif "Static" in class_name and hasattr(root, "content"):
                try:
                    content = str(root.content)
                    if content and len(content) < 100:  # Only capture short text
                        tree["content"] = content
                        tree["widget_type"] = "static"
                except Exception:
                    pass

            # Get children if available
            if hasattr(root, "children"):
                for child in root.children:
                    if hasattr(child, "__class__"):
                        tree["children"].append(self._extract_widget_tree(child))
            elif hasattr(root, "query"):
                # Try to get all child widgets via query
                try:
                    child_widgets = root.query("*")
                    for child in child_widgets:
                        if child != root:  # Avoid infinite recursion
                            tree["children"].append(self._extract_widget_tree(child))
                except Exception:
                    pass  # Ignore query errors

            return tree

        except Exception:
            # Fallback to minimal info
            return {
                "class": getattr(root, "__class__", type(root)).__name__,
                "error": "Could not extract full tree",
            }

    def close(self) -> None:
        """Close the debug logger and clean up resources."""
        if self.enabled and self.log_file:
            # Log session end
            try:
                self._write_event(
                    {
                        "event_id": str(uuid.uuid4()),
                        "timestamp": self._get_timestamp(),
                        "session_id": self.session_id,
                        "event_type": "session_end",
                        "screen": None,
                        "widget": None,
                        "context": {},
                        "data": {},
                    }
                )
                self.log_file.close()

                # Print debug info after TUI ends
                import sys

                print("", file=sys.stderr)
                print("TUI Debug Session Ended", file=sys.stderr)
                print(f"Debug log: {self.log_path}", file=sys.stderr)

            except Exception:
                pass  # Ignore errors during cleanup

        # Clean up old files
        self._cleanup_old_files()

    def _cleanup_old_files(self) -> None:
        """Clean up old debug files (older than 7 days)."""
        if not self.enabled:
            return

        try:
            import time

            current_time = time.time()
            seven_days_ago = current_time - (7 * 24 * 60 * 60)
            log_dir = get_user_log_dir('gatekit')

            # Clean up debug logs
            debug_log_pattern = os.path.join(log_dir, "gatekit_tui_debug*.log*")
            for log_file in glob.glob(debug_log_pattern):
                try:
                    if os.path.getmtime(log_file) < seven_days_ago:
                        os.remove(log_file)
                except Exception:
                    pass  # Ignore individual file errors

            # Clean up state dumps
            state_dump_pattern = os.path.join(log_dir, "gatekit_tui_state_*.json")
            for state_file in glob.glob(state_dump_pattern):
                try:
                    if os.path.getmtime(state_file) < seven_days_ago:
                        os.remove(state_file)
                except Exception:
                    pass  # Ignore individual file errors

        except Exception:
            pass  # Ignore all cleanup errors


# Global debug logger instance
_debug_logger: Optional[TUIDebugLogger] = None


def get_debug_logger() -> Optional[TUIDebugLogger]:
    """Get the global debug logger instance."""
    return _debug_logger


def initialize_debug_logger(enabled: bool = False) -> None:
    """Initialize the global debug logger.

    Args:
        enabled: Whether to enable debug logging
    """
    global _debug_logger
    if _debug_logger:
        _debug_logger.close()
    _debug_logger = TUIDebugLogger(enabled=enabled)


def cleanup_debug_logger() -> None:
    """Clean up the global debug logger."""
    global _debug_logger
    if _debug_logger:
        _debug_logger.close()
        _debug_logger = None
