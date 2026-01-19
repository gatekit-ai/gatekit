"""Pure helpers for translating plugin configs to/from TUI forms.

This module handles the translation between plugin configuration as stored
in the config dict and the form state used by the TUI config modal.

Framework fields (enabled, priority) are injected into plugin schemas
for form display. See ADR-005 for the consolidated configuration architecture.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Type

from gatekit.plugins.interfaces import AuditingPlugin, PluginInterface
from gatekit.config.framework_fields import (
    DEFAULT_FRAMEWORK_VALUES,
    get_framework_fields,
    inject_framework_fields,
)


@dataclass
class PluginFormState:
    """Captured state used by the TUI modal and tests."""

    schema: Dict[str, Any]
    initial_data: Dict[str, Any]
    passthrough: Dict[str, Any]
    schema_keys: frozenset[str]


def _get_plugin_type(plugin_class: Type[PluginInterface]) -> str:
    """Determine plugin type from class hierarchy.

    Args:
        plugin_class: The plugin class to check

    Returns:
        One of "auditing", "security", or "middleware"
    """
    if issubclass(plugin_class, AuditingPlugin):
        return "auditing"
    # SecurityPlugin inherits from MiddlewarePlugin, so check this way
    # Both security and middleware plugins get priority
    return "security"  # Treated same as middleware for framework fields


def _passthrough_keys(schema_keys: Iterable[str], config: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy of fields that are not represented in the schema."""

    schema_key_set = set(schema_keys)
    return {key: deepcopy(value) for key, value in config.items() if key not in schema_key_set}


def _resolve_ref(prop_schema: Dict[str, Any], definitions: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a $ref in a property schema to its definition.

    Args:
        prop_schema: Property schema that may contain a $ref
        definitions: The $defs dictionary from the root schema

    Returns:
        Resolved schema with $ref replaced by definition contents
    """
    if "$ref" not in prop_schema:
        return prop_schema

    ref = prop_schema["$ref"]
    if not ref.startswith("#/$defs/"):
        return prop_schema

    def_name = ref.split("/")[-1]
    if def_name not in definitions:
        return prop_schema

    # Merge definition with any additional properties from original (except $ref)
    resolved = deepcopy(definitions[def_name])
    for key, value in prop_schema.items():
        if key != "$ref":
            resolved[key] = value
    return resolved


def _apply_nested_defaults(
    schema: Dict[str, Any],
    config_dict: Dict[str, Any],
    definitions: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recursively apply schema defaults including $ref definitions.

    This handles nested object defaults like pii_types.email.enabled where
    the nested structure uses $ref to reference $defs definitions.

    Args:
        schema: JSON schema for the current level
        config_dict: Current configuration values
        definitions: The $defs dictionary from the root schema

    Returns:
        Config dict with defaults applied for missing values
    """
    if definitions is None:
        definitions = schema.get("$defs", {})

    result = deepcopy(config_dict)
    properties = schema.get("properties", {})

    for key, prop_schema in properties.items():
        # Resolve $ref if present
        resolved = _resolve_ref(prop_schema, definitions)

        if key not in result:
            # Key not in config - apply default if available
            if "default" in resolved:
                result[key] = deepcopy(resolved["default"])
            elif resolved.get("type") == "object" and "properties" in resolved:
                # For nested objects without a top-level default, recursively build defaults
                result[key] = _apply_nested_defaults(resolved, {}, definitions)
        elif isinstance(result[key], dict) and resolved.get("type") == "object":
            # Key exists and is an object - recursively apply defaults for missing sub-keys
            result[key] = _apply_nested_defaults(resolved, result[key], definitions)

    return result


def build_form_state(
    plugin_class: Type[PluginInterface],
    config: Mapping[str, Any] | None,
    plugin_type: Optional[str] = None,
) -> PluginFormState:
    """Prepare schema + initial data for a plugin configuration modal.

    Args:
        plugin_class: The plugin class being configured
        config: Current configuration dict (may be None or empty)
        plugin_type: Optional explicit plugin type ("security", "middleware", "auditing").
                    If not provided, determined from plugin class hierarchy.

    Returns:
        PluginFormState with schema (including framework fields), initial data,
        and passthrough keys for fields not in schema.
    """
    # Determine plugin type if not explicitly provided
    if plugin_type is None:
        plugin_type = _get_plugin_type(plugin_class)

    base_schema = plugin_class.get_json_schema()
    schema = inject_framework_fields(base_schema, plugin_type)
    schema_keys = frozenset(schema.get("properties", {}).keys())
    config_dict: Dict[str, Any] = deepcopy(config) if isinstance(config, Mapping) else {}

    passthrough = _passthrough_keys(schema_keys, config_dict)

    # Get framework fields for this plugin type to know which defaults apply
    framework_fields = get_framework_fields(plugin_type)

    # Get schema properties and definitions for extracting defaults
    schema_properties = schema.get("properties", {})
    definitions = schema.get("$defs", {})

    initial_data: Dict[str, Any] = {}
    for key in schema_keys:
        if key in config_dict:
            # For object properties, apply nested defaults to fill in missing sub-keys
            prop_schema = schema_properties.get(key, {})
            resolved = _resolve_ref(prop_schema, definitions)
            if resolved.get("type") == "object" and isinstance(config_dict[key], dict):
                initial_data[key] = _apply_nested_defaults(resolved, config_dict[key], definitions)
            else:
                initial_data[key] = deepcopy(config_dict[key])
        elif key in framework_fields and key in DEFAULT_FRAMEWORK_VALUES:
            initial_data[key] = deepcopy(DEFAULT_FRAMEWORK_VALUES[key])
        elif key in schema_properties:
            prop_schema = schema_properties[key]
            resolved = _resolve_ref(prop_schema, definitions)
            if "default" in resolved:
                # Use schema default for plugin-specific fields
                initial_data[key] = deepcopy(resolved["default"])
            elif resolved.get("type") == "object" and "properties" in resolved:
                # For object properties without top-level default, build from nested defaults
                initial_data[key] = _apply_nested_defaults(resolved, {}, definitions)

    return PluginFormState(
        schema=schema,
        initial_data=initial_data,
        passthrough=passthrough,
        schema_keys=schema_keys,
    )


def serialize_form_data(state: PluginFormState, form_values: Mapping[str, Any]) -> Dict[str, Any]:
    """Filter form values down to schema-defined keys."""
    from gatekit.tui.debug import get_debug_logger

    logger = get_debug_logger()
    if logger:
        logger.log_event(
            "serialize_form_data",
            context={
                "schema_keys": sorted(state.schema_keys),
                "form_values_keys": sorted(form_values.keys()),
            },
        )

    serialized: Dict[str, Any] = {}
    for key in state.schema_keys:
        if key in form_values:
            serialized[key] = deepcopy(form_values[key])

    if logger:
        logger.log_event(
            "serialize_form_data_result",
            context={"serialized_keys": sorted(serialized.keys())},
            data={"serialized": serialized},
        )

    return serialized


def merge_with_passthrough(state: PluginFormState, config_values: Mapping[str, Any]) -> Dict[str, Any]:
    """Merge sanitized config values with passthrough keys captured from input.

    Passthrough keys are config fields not in the schema (e.g., from older plugin
    versions or manually added). We preserve them while adding all form values.
    """
    from gatekit.tui.debug import get_debug_logger

    logger = get_debug_logger()
    if logger:
        logger.log_event(
            "merge_with_passthrough",
            context={
                "passthrough_keys": sorted(state.passthrough.keys()),
                "config_values_keys": sorted(config_values.keys()),
            },
        )

    merged = deepcopy(state.passthrough)
    merged.update(deepcopy(config_values))

    if logger:
        logger.log_event(
            "merge_with_passthrough_result",
            context={"merged_keys": sorted(merged.keys())},
            data={"merged": merged},
        )

    return merged


__all__ = [
    "PluginFormState",
    "build_form_state",
    "serialize_form_data",
    "merge_with_passthrough",
]
