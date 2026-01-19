"""Common JSON Schema definitions for all plugins."""

COMMON_DEFS = {
    "enabled": {
        "type": "boolean",
        "description": "Enable this plugin",
        "default": True,
    },
    "priority": {
        "type": "integer",
        "description": "Plugin execution priority (0-100, lower = higher priority)",
        "default": 50,
        "minimum": 0,
        "maximum": 100,
    },
    "file_path": {
        "type": "string",
        "description": "Path to file (supports ~ expansion and date formatting)",
    },
}
