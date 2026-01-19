"""Shared framework field definitions for plugin configuration.

Framework fields (enabled, priority, critical) are stored in the plugin config dict
and injected into plugin schemas at runtime. This module provides the
canonical definitions used by both:
- TUI config adapter (for form generation)
- Schema validator (for validation)

See ADR-005 for the consolidated configuration architecture.
"""

from copy import deepcopy
from typing import Any, Dict, Mapping, MutableMapping


ENABLED_FIELD_SCHEMA: Dict[str, Any] = {
    "type": "boolean",
    "title": "Plugin Enabled",
    "description": "Enable this plugin instance",
    "default": True,
}

CRITICAL_FIELD_SCHEMA: Dict[str, Any] = {
    "type": "boolean",
    "title": "Critical (True = terminate gateway on plugin failure)",
    "description": "If true (default), plugin failures cause startup to fail. If false, plugin failures are logged but startup continues.",
    "default": True,
}

PRIORITY_FIELD_SCHEMA: Dict[str, Any] = {
    "type": "integer",
    "title": "Execution Priority",
    "description": "0-100, lower value = higher priority",
    "default": 50,
    "minimum": 0,
    "maximum": 100,
}

# Default values for framework fields when not specified in config
DEFAULT_FRAMEWORK_VALUES: Dict[str, Any] = {
    "enabled": False,  # Default to disabled for new plugins in TUI
    "priority": 50,
    "critical": True,  # Default to fail-closed (secure by default)
}


def get_framework_fields(plugin_type: str) -> Dict[str, Dict[str, Any]]:
    """Get framework field schemas for a plugin type.

    Args:
        plugin_type: One of "security", "middleware", or "auditing"

    Returns:
        Dict mapping field name to JSON schema definition.
        - Auditing plugins get "enabled" and "critical" (no priority by design)
        - Security/middleware plugins get "enabled", "priority", and "critical"
    """
    if plugin_type == "auditing":
        return {
            "enabled": deepcopy(ENABLED_FIELD_SCHEMA),
            "critical": deepcopy(CRITICAL_FIELD_SCHEMA),
        }
    else:
        return {
            "enabled": deepcopy(ENABLED_FIELD_SCHEMA),
            "critical": deepcopy(CRITICAL_FIELD_SCHEMA),
            "priority": deepcopy(PRIORITY_FIELD_SCHEMA),
        }


def inject_framework_fields(
    base_schema: Mapping[str, Any],
    plugin_type: str,
) -> Dict[str, Any]:
    """Inject framework fields into a plugin schema.

    Framework fields are added at the start of the properties dict,
    before plugin-specific fields. If the plugin schema already defines
    these fields, they are replaced with the framework definitions.

    Args:
        base_schema: The plugin's original JSON schema
        plugin_type: One of "security", "middleware", or "auditing"

    Returns:
        A new schema dict with framework fields injected
    """
    schema = deepcopy(base_schema) if base_schema else {}
    properties: MutableMapping[str, Any] = deepcopy(schema.get("properties", {}))

    # Get framework fields for this plugin type
    framework_fields = get_framework_fields(plugin_type)

    # Remove any existing framework fields from plugin properties
    plugin_properties = {
        key: value for key, value in properties.items() if key not in framework_fields
    }

    # Build merged properties: framework fields first, then plugin fields
    merged_properties: Dict[str, Any] = {}
    for key, value in framework_fields.items():
        merged_properties[key] = deepcopy(value)
    merged_properties.update(plugin_properties)

    schema["properties"] = merged_properties
    return schema


__all__ = [
    "ENABLED_FIELD_SCHEMA",
    "PRIORITY_FIELD_SCHEMA",
    "CRITICAL_FIELD_SCHEMA",
    "DEFAULT_FRAMEWORK_VALUES",
    "get_framework_fields",
    "inject_framework_fields",
]
