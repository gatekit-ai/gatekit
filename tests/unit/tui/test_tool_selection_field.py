"""Unit tests for ToolSelectionField data shaping."""

from types import SimpleNamespace

from gatekit.tui.widgets.tool_selection_field import ToolSelectionField, _ToolRow


def _stub_checkbox(value: bool) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _stub_input(value: str = "") -> SimpleNamespace:
    return SimpleNamespace(value=value)


def test_tool_selection_field_normalizes_discovery_and_manual_entries():
    discovery = {
        "tools": [
            {"name": "summarize", "description": "Summaries"},
            {"name": "search", "description": "Search docs"},
        ],
        "status": "ok",
        "last_refreshed": None,
    }
    existing = [
        {"tool": "summarize", "display_name": "Summaries"},
        {"tool": "custom", "display_description": "Custom desc"},
    ]

    widget = ToolSelectionField("tools", initial_entries=existing, discovery=discovery)

    rows = widget._normalized_rows
    # Check that discovered tools exist (discovered_description contains the discovery data)
    assert any(row["tool_id"] == "summarize" and row["discovered_description"] == "Summaries" for row in rows)
    assert any(row["tool_id"] == "search" and row["discovered_description"] == "Search docs" for row in rows)
    # Only discovered tools are included - orphaned config entries are dropped
    # (Manual entries not in discovery are considered stale/invalid)
    assert not any(row["tool_id"] == "custom" for row in rows)
    assert len(rows) == 2  # Only discovered tools


def test_tool_selection_field_get_value_uses_checked_rows():
    widget = ToolSelectionField("tools", initial_entries=[], discovery={})

    widget._rows = {
        "alpha": _ToolRow(
            tool_id="alpha",
            checkbox=_stub_checkbox(True),
            display_name_input=_stub_input("Friendly Alpha"),
            display_description_input=_stub_input("Alpha desc"),
            discovered_name="Alpha",
            discovered_description="",
        ),
        "beta": _ToolRow(
            tool_id="beta",
            checkbox=_stub_checkbox(False),
            display_name_input=_stub_input(""),
            display_description_input=_stub_input(""),
            discovered_name="Beta",
            discovered_description="",
        ),
    }

    values = widget.get_value()
    assert values == [
        {
            "tool": "alpha",
            "display_name": "Friendly Alpha",
            "display_description": "Alpha desc",
        }
    ]


def test_tool_selection_field_set_value_updates_widget_state():
    widget = ToolSelectionField("tools", initial_entries=[], discovery={})

    manual_row = _ToolRow(
        tool_id="manual-tool",
        checkbox=_stub_checkbox(False),
        display_name_input=_stub_input(""),
        display_description_input=_stub_input(""),
        discovered_name=None,
        discovered_description=None,
    )

    discovered_row = _ToolRow(
        tool_id="alpha",
        checkbox=_stub_checkbox(False),
        display_name_input=_stub_input(""),
        display_description_input=_stub_input(""),
        discovered_name="Alpha",
        discovered_description=None,
    )

    widget._rows = {
        "manual": manual_row,
        "alpha": discovered_row,
    }

    widget.set_value(
        [
            {"tool": "alpha", "display_name": "Alpha Display"},
            {"tool": "manual-tool", "display_description": "Manual desc"},
        ]
    )

    assert discovered_row.checkbox.value is True
    assert discovered_row.display_name_input.value == "Alpha Display"
    assert manual_row.checkbox.value is True
    assert manual_row.display_description_input.value == "Manual desc"


def test_tool_selection_field_preserves_config_when_discovery_fails():
    """When discovery fails, get_value() should return original config to prevent data loss."""
    original_config = [
        {"tool": "my_tool", "display_name": "My Tool", "display_description": "Does stuff"},
        {"tool": "other_tool"},
    ]

    # Discovery failed - status is not "ok"
    discovery = {
        "status": "error",
        "message": "Server unavailable",
        "tools": [],  # No tools discovered
    }

    widget = ToolSelectionField("tools", initial_entries=original_config, discovery=discovery)

    # Even though _rows is empty (no discovered tools), get_value should
    # return the original config because discovery failed
    assert widget.get_value() == original_config


def test_tool_selection_field_returns_empty_when_discovery_succeeds_with_no_selections():
    """When discovery succeeds but user unchecks all, return empty list (not original config)."""
    original_config = [
        {"tool": "my_tool", "display_name": "My Tool"},
    ]

    # Discovery succeeded
    discovery = {
        "status": "ok",
        "tools": [{"name": "my_tool", "description": "A tool"}],
    }

    widget = ToolSelectionField("tools", initial_entries=original_config, discovery=discovery)

    # Simulate user unchecking all tools
    widget._rows = {
        "my_tool": _ToolRow(
            tool_id="my_tool",
            checkbox=_stub_checkbox(False),  # Unchecked
            display_name_input=_stub_input(""),
            display_description_input=_stub_input(""),
            discovered_name="my_tool",
            discovered_description="A tool",
        ),
    }

    # Discovery succeeded, so we build from UI state (empty since nothing checked)
    assert widget.get_value() == []
