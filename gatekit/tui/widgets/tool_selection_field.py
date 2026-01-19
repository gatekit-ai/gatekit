"""Custom widget for selecting tools with discovery metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Input, Label

from gatekit.tui.widgets.ascii_checkbox import ASCIICheckbox
from gatekit.tui.widgets.selectable_static import SelectableStatic
from gatekit.tui.debug import get_debug_logger


@dataclass
class _ToolRow:
    """Internal representation of a tool row."""

    tool_id: str
    checkbox: ASCIICheckbox
    display_name_input: Input
    display_description_input: Input
    discovered_name: Optional[str] = None
    discovered_description: Optional[str] = None


class ToolSelectionField(Container):
    """Widget rendering discovered tools with display overrides."""

    DEFAULT_CSS = """
    ToolSelectionField {
        layout: vertical;
        height: auto;
        border: round $surface-lighten-2;
        padding: 1;
        margin-top: 1;
        background: transparent;
    }

    ToolSelectionField > .tool-status {
        height: auto;
    }

    ToolSelectionField > .tool-rows {
        layout: vertical;
        align: left top;
        height: auto;
        width: 100%;
    }

    ToolSelectionField .tool-row {
        layout: vertical;
        border: round $surface-lighten-3;
        padding: 1;
        background: $surface-lighten-1;
        margin-bottom: 1;
        height: auto;
        width: 100%;
        min-height: 3;
    }

    ToolSelectionField .tool-row-header {
        height: 1;
    }

    ToolSelectionField .tool-row-header Label {
        text-style: bold;
        min-height: 1;
    }

    ToolSelectionField .tool-row-description {
        color: $text-muted;
        text-wrap: wrap;
        padding-bottom: 1;
    }

    ToolSelectionField .tool-inputs {
        height: auto;
    }

    ToolSelectionField Input {
        background: $surface-lighten-2;
        min-height: 3;
    }

    ToolSelectionField .tool-input-label {
        color: $text-muted;
        min-height: 1;
    }

    ToolSelectionField .tool-id-label {
        color: $text;
        text-style: bold;
        padding-left: 1;
        min-height: 3;
    }

    ToolSelectionField .tool-alt-label {
        color: $text-muted;
        padding-left: 1;
        min-height: 3;
    }

    ToolSelectionField .field-error {
        color: $error;
        text-style: italic;
        padding-left: 1;
        min-height: 1;
    }

    """

    # Validation pattern for display_name (must match tool_manager schema)
    DISPLAY_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
    DISPLAY_NAME_ERROR = "Must start with a letter and contain only letters, numbers, underscores, or hyphens"

    def __init__(
        self,
        field_name: str,
        initial_entries: Optional[List[Dict[str, Any]]] = None,
        discovery: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(classes="tool-selection-field")
        self.field_name = field_name
        self.initial_entries = initial_entries or []
        self.discovery = discovery or {}
        self._rows: Dict[str, _ToolRow] = {}
        self._status_label: Optional[Label] = None
        self._normalized_rows = self._build_row_models()
        self._is_mounted = False
        self._error_labels: Dict[str, Label] = {}  # Track error labels by widget ID

    def update_discovery(self, discovery: Dict[str, Any]) -> None:
        """Update discovery data and rebuild the widget if mounted."""
        debug_logger = get_debug_logger()
        if debug_logger:
            debug_logger.log_event(
                "tool_selection_update_discovery",
                widget=self,
                context={
                    "discovery_status": discovery.get("status"),
                    "tool_count": len(discovery.get("tools", [])),
                    "is_mounted": self._is_mounted,
                },
            )
        
        self.discovery = discovery
        self._normalized_rows = self._build_row_models()
        
        if debug_logger:
            debug_logger.log_event(
                "tool_selection_rows_rebuilt",
                widget=self,
                context={
                    "row_count": len(self._normalized_rows),
                },
            )
        
        if self._is_mounted:
            # Schedule rebuild after current refresh cycle completes
            if debug_logger:
                debug_logger.log_event(
                    "tool_selection_scheduling_rebuild",
                    widget=self,
                    context={
                        "row_count": len(self._normalized_rows),
                    },
                )
            self.call_after_refresh(self._rebuild_widget)

    def _build_row_models(self) -> List[Dict[str, Any]]:
        """Pre-compute row metadata for composition."""
        existing_map = {
            entry.get("tool"): entry for entry in self.initial_entries if entry.get("tool")
        }

        discovered = self.discovery.get("tools") or []
        debug_logger = get_debug_logger()
        seen: set[str] = set()
        rows: List[Dict[str, Any]] = []

        for raw_tool in discovered:
            if debug_logger:
                try:
                    debug_logger.log_event(
                        "tool_selection_discovery_entry",
                        widget=self,
                        context={
                            "tool_type": type(raw_tool).__name__,
                            "keys": list(raw_tool.keys()) if isinstance(raw_tool, dict) else None,
                            "sample": str(raw_tool)[:200],
                        },
                    )
                except Exception:
                    pass

            summary = self._extract_tool_summary(raw_tool)
            tool_id = summary.get("tool_id")
            if not tool_id or tool_id in seen:
                continue
            seen.add(tool_id)

            existing = existing_map.pop(tool_id, None)
            # If there's an existing config, only tools in that config should be checked
            # If no config (new plugin), all tools start checked for convenience
            is_checked = existing is not None if self.initial_entries else True
            rows.append(
                {
                    "tool_id": tool_id,
                    "checked": is_checked,
                    "display_name": existing.get("display_name") if existing else "",
                    "display_description": existing.get("display_description") if existing else "",
                    "discovered_name": summary.get("display_name"),
                    "discovered_description": summary.get("description"),
                }
            )

        if debug_logger:
            try:
                debug_logger.log_event(
                    "tool_selection_rows_built",
                    widget=self,
                    context={
                        "row_count": len(rows),
                        "first_row": rows[0] if rows else None,
                    },
                )
            except Exception:
                pass

        return rows

    def _extract_tool_summary(self, tool: Any) -> Dict[str, Optional[str]]:
        """Extract identifier, display name, and description from discovery data."""

        result: Dict[str, Optional[str]] = {
            "tool_id": None,
            "display_name": None,
            "description": None,
        }

        if not isinstance(tool, dict):
            return result

        candidates: List[str] = []

        for key in ("name", "id", "identifier", "tool"):
            value = tool.get(key)
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, dict):
                nested_id = value.get("name") or value.get("id")
                if isinstance(nested_id, str):
                    candidates.append(nested_id)
                if result["display_name"] is None:
                    nested_display = (
                        value.get("display_name")
                        or value.get("displayName")
                        or value.get("title")
                    )
                    if isinstance(nested_display, str):
                        result["display_name"] = nested_display
                if result["description"] is None:
                    nested_desc = value.get("description") or value.get("summary")
                    if isinstance(nested_desc, str):
                        result["description"] = nested_desc

        if result["display_name"] is None:
            root_display = (
                tool.get("display_name")
                or tool.get("displayName")
                or tool.get("title")
            )
            if isinstance(root_display, str):
                result["display_name"] = root_display

        if result["description"] is None:
            root_desc = tool.get("description") or tool.get("summary")
            if isinstance(root_desc, str):
                result["description"] = root_desc

        for candidate in candidates:
            candidate = candidate.strip()
            if candidate:
                result["tool_id"] = candidate
                break

        return result

    def on_mount(self) -> None:
        """Track when widget is mounted."""
        self._is_mounted = True

    def _build_tool_row_widgets(self, index: int, row: Dict[str, Any]) -> Tuple[Vertical, _ToolRow]:
        """Build a single tool row widget tree and its internal representation.
        
        Args:
            index: The row index (for generating widget IDs)
            row: The row data dictionary containing tool_id, checked, display names, etc.
            
        Returns:
            A tuple of (tool_row_container, tool_row_data) where:
            - tool_row_container is the Vertical widget tree for this row
            - tool_row_data is the _ToolRow dataclass with references to the widgets
        """
        checkbox = ASCIICheckbox(
            label="",
            value=row["checked"],
            id=f"{self.field_name}_checkbox_{index}",
            classes="tool-checkbox",
        )
        checkbox.can_focus = True

        display_name_input = Input(
            value=row.get("display_name", ""),
            placeholder="Optional display name",
            id=f"{self.field_name}_display_name_{index}",
        )

        display_description_input = Input(
            value=row.get("display_description", ""),
            placeholder="Optional description",
            id=f"{self.field_name}_display_description_{index}",
        )

        # Build header widgets
        header_widgets = [checkbox]
        
        primary_label = row["tool_id"]
        id_label = SelectableStatic(primary_label, classes="tool-id-label")
        header_widgets.append(id_label)
        
        alt_label = row.get("discovered_name")
        if alt_label and alt_label != primary_label:
            alt = SelectableStatic(f"({alt_label})", classes="tool-alt-label")
            header_widgets.append(alt)
        
        # Build header container
        header = Horizontal(*header_widgets, classes="tool-row-header")
        
        # Build tool row container widgets
        row_widgets = [header]
        
        # Add description if present
        description = row.get("discovered_description")
        if description:
            desc = SelectableStatic(description, classes="tool-row-description")
            row_widgets.append(desc)
        
        # Build input fields container
        inputs_widgets = [
            SelectableStatic("Display name", classes="tool-input-label"),
            display_name_input,
            SelectableStatic("Display description", classes="tool-input-label"),
            display_description_input,
        ]
        inputs_container = Vertical(*inputs_widgets, classes="tool-inputs")
        row_widgets.append(inputs_container)
        
        # Build tool row container
        tool_row_container = Vertical(*row_widgets, classes="tool-row")
        
        # Build the data representation
        tool_row_data = _ToolRow(
            tool_id=row["tool_id"],
            checkbox=checkbox,
            display_name_input=display_name_input,
            display_description_input=display_description_input,
            discovered_name=row.get("discovered_name"),
            discovered_description=row.get("discovered_description"),
        )
        
        return tool_row_container, tool_row_data

    def _rebuild_widget(self) -> None:
        """Rebuild the widget with new data after discovery update."""
        debug_logger = get_debug_logger()
        if debug_logger:
            debug_logger.log_event(
                "tool_selection_rebuild_start",
                widget=self,
                context={
                    "child_count_before": len(list(self.children)),
                    "row_count": len(self._normalized_rows),
                },
            )
        
        # Clear the rows dictionary
        self._rows.clear()
        
        # Remove the old tool-rows container(s) - there may be multiple from previous rebuilds
        old_containers = self.query(".tool-rows").results()
        for container in old_containers:
            container.remove()
        
        # Update status label if it exists, or create it if needed
        status_message = self._build_status_message()
        if self._status_label is not None:
            if status_message:
                self._status_label.update(status_message)
            else:
                self._status_label.remove()
                self._status_label = None
        elif status_message:
            # Create new status label if we need one and don't have one
            self._status_label = Label(status_message, classes="tool-status")
            self.mount(self._status_label)
        
        # Build tool rows
        tool_row_widgets = []
        
        if not self._normalized_rows:
            # No tools discovered - add helpful messages
            tool_row_widgets.append(
                SelectableStatic(
                    "Waiting for tool discovery from MCP server...",
                    classes="no-tools-message"
                )
            )
            tool_row_widgets.append(
                SelectableStatic(
                    "This list will update automatically when tools are discovered.",
                    classes="no-tools-hint"
                )
            )
        else:
            # Build each tool row widget tree
            for index, row in enumerate(self._normalized_rows):
                if debug_logger:
                    debug_logger.log_event(
                        "tool_selection_building_row",
                        widget=self,
                        context={
                            "index": index,
                            "tool_id": row["tool_id"],
                            "display_name": row.get("display_name"),
                            "discovered_description": row.get("discovered_description")[:50] if row.get("discovered_description") else None,
                        },
                    )
                
                # Use the extracted helper to build row
                tool_row_container, tool_row_data = self._build_tool_row_widgets(index, row)
                tool_row_widgets.append(tool_row_container)
                
                if debug_logger:
                    debug_logger.log_event(
                        "tool_selection_row_built",
                        widget=self,
                        context={
                            "index": index,
                            "tool_id": row["tool_id"],
                            "total_tool_row_widgets": len(tool_row_widgets),
                        },
                    )
                
                # Store the row
                self._rows[row["tool_id"]] = tool_row_data
        
        # Create the tool rows container with all tool rows
        if debug_logger:
            debug_logger.log_event(
                "tool_selection_creating_container",
                widget=self,
                context={
                    "tool_row_widgets_count": len(tool_row_widgets),
                    "tool_row_widgets_types": [type(w).__name__ for w in tool_row_widgets],
                },
            )
        
        tool_rows_container = Vertical(*tool_row_widgets, classes="tool-rows")
        
        if debug_logger:
            debug_logger.log_event(
                "tool_selection_rebuild_mounting",
                widget=self,
                context={
                    "tool_row_count": len(tool_row_widgets),
                    "rows_dict_count": len(self._rows),
                },
            )
        
        # Mount the new tool-rows container
        self.mount(tool_rows_container)
        
        if debug_logger:
            # Log detailed widget tree structure
            children_info = []
            for child in self.children:
                child_info = {
                    "type": type(child).__name__,
                    "classes": list(child.classes) if hasattr(child, 'classes') else [],
                    "id": child.id if hasattr(child, 'id') else None,
                    "display": str(child.styles.display) if hasattr(child, 'styles') else None,
                    "visible": child.visible if hasattr(child, 'visible') else None,
                    "child_count": len(list(child.children)) if hasattr(child, 'children') else 0,
                }
                # If this is the tool-rows container, log its children
                if "tool-rows" in child_info["classes"]:
                    child_info["tool_rows_children"] = [
                        {
                            "type": type(c).__name__,
                            "classes": list(c.classes) if hasattr(c, 'classes') else [],
                            "visible": c.visible if hasattr(c, 'visible') else None,
                            "display": str(c.styles.display) if hasattr(c, 'styles') else None,
                        }
                        for c in child.children
                    ]
                children_info.append(child_info)
            
            debug_logger.log_event(
                "tool_selection_rebuild_complete",
                widget=self,
                context={
                    "child_count_after": len(list(self.children)),
                    "final_row_count": len(self._rows),
                    "children_info": children_info,
                },
            )
        
        # Force a refresh to update the display
        self.refresh()

    def compose(self) -> ComposeResult:
        status_message = self._build_status_message()
        if status_message:
            self._status_label = Label(status_message, classes="tool-status")
            yield self._status_label

        with Vertical(classes="tool-rows"):
            if not self._normalized_rows:
                # No tools discovered - show helpful message
                yield SelectableStatic(
                    "Waiting for tool discovery from MCP server...",
                    classes="no-tools-message"
                )
                yield SelectableStatic(
                    "This list will update automatically when tools are discovered.",
                    classes="no-tools-hint"
                )
                return
            
            for index, row in enumerate(self._normalized_rows):
                # Use the extracted helper to build row
                tool_row_container, tool_row_data = self._build_tool_row_widgets(index, row)
                yield tool_row_container
                
                # Store the row
                self._rows[row["tool_id"]] = tool_row_data
            

    def _build_status_message(self) -> Optional[str]:
        status = self.discovery.get("status")
        message = self.discovery.get("message")
        last_refreshed = self.discovery.get("last_refreshed")

        if not status or status == "ok":
            if last_refreshed:
                return f"Discovered {len(self.discovery.get('tools') or [])} tools (last refreshed {self._format_timestamp(last_refreshed)})."
            return None

        base = status.replace("_", " ").title()
        details = message or "Tool discovery unavailable."
        timestamp = (
            f" Last attempt {self._format_timestamp(last_refreshed)}."
            if last_refreshed
            else ""
        )
        return f"{base}: {details}.{timestamp}"

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    def _discovery_failed(self) -> bool:
        """Check if tool discovery failed or is unavailable."""
        status = self.discovery.get("status")
        # If status is None or "ok", discovery succeeded (or hasn't been attempted)
        # Any other status indicates a failure
        return status is not None and status != "ok"

    def get_value(self) -> List[Dict[str, Any]]:
        """Return schema-compatible data.

        If discovery failed, preserves the original config to prevent data loss.
        """
        # If discovery failed, preserve original config - user can't meaningfully
        # interact with the widget anyway since no tools are displayed
        if self._discovery_failed():
            return self.initial_entries

        results: List[Dict[str, Any]] = []
        for _key, row in self._rows.items():
            if not row.checkbox.value:
                continue

            entry: Dict[str, Any] = {"tool": row.tool_id}

            display_name = row.display_name_input.value.strip()
            if display_name:
                entry["display_name"] = display_name

            display_description = row.display_description_input.value.strip()
            if display_description:
                entry["display_description"] = display_description

            results.append(entry)

        return results

    def set_value(self, entries: List[Dict[str, Any]]) -> None:
        """Update widget state from configuration."""
        entries_map = {entry.get("tool"): entry for entry in entries if entry.get("tool")}

        # Reset all rows to unchecked
        for _key, row in self._rows.items():
            row.checkbox.value = False
            row.display_name_input.value = ""
            row.display_description_input.value = ""

        for _key, row in self._rows.items():
            entry = entries_map.get(row.tool_id)

            if not entry:
                continue

            row.checkbox.value = True

            display_name = entry.get("display_name", "")
            row.display_name_input.value = display_name

            display_description = entry.get("display_description", "")
            row.display_description_input.value = display_description

    def focus_first(self) -> None:
        """Give focus to the first row checkbox."""
        for row in self._rows.values():
            if row.checkbox.can_focus:
                row.checkbox.focus()
                break

    @on(Input.Changed)
    def _on_input_changed(self, event: Input.Changed) -> None:
        """Validate display_name inputs in real-time."""
        input_widget = event.input
        if not input_widget.id:
            return

        # Only validate display_name inputs (not display_description)
        if "_display_name_" not in input_widget.id:
            return

        value = input_widget.value.strip()

        # Empty is valid (optional field)
        if not value:
            self._clear_field_error(input_widget.id)
            return

        # Validate against pattern
        if not self.DISPLAY_NAME_PATTERN.match(value):
            self._show_field_error(input_widget.id, self.DISPLAY_NAME_ERROR)
        else:
            self._clear_field_error(input_widget.id)

    def _show_field_error(self, widget_id: str, error_message: str) -> None:
        """Show an inline error message below a field."""
        error_label_id = f"{widget_id}_error"

        # Check if error label already exists
        if widget_id in self._error_labels:
            self._error_labels[widget_id].update(error_message)
            return

        # Find the widget and insert error label after it
        try:
            widget = self.query_one(f"#{widget_id}", Input)
            error_label = Label(error_message, id=error_label_id, classes="field-error")
            widget.parent.mount(error_label, after=widget)
            self._error_labels[widget_id] = error_label
        except Exception:
            pass  # Widget not found, skip error display

    def _clear_field_error(self, widget_id: str) -> None:
        """Clear any error message for a field."""
        if widget_id in self._error_labels:
            try:
                self._error_labels[widget_id].remove()
            except Exception:
                pass
            del self._error_labels[widget_id]

    def has_validation_errors(self) -> bool:
        """Check if any fields have validation errors."""
        return len(self._error_labels) > 0
