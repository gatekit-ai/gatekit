"""Shared TUI constants for stable identifiers.

These IDs let us decouple UI labels from logic. Use these in code paths that
should remain stable even if we rename column headers or change text.
"""

# Plugin scope constants
GLOBAL_SCOPE = "_global"

# Plugin table column identifiers (DataTable variant)
PLUGIN_COL_ID_NAME = "name"
PLUGIN_COL_ID_SCOPE = "scope"
PLUGIN_COL_ID_PRIORITY = "priority"
PLUGIN_COL_ID_ACTIONS = "actions"
