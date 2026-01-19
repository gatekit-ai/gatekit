"""Adapter to generate Textual forms from JSON Schema."""

from typing import Dict, Any, Optional, Set
from textual.app import ComposeResult
from textual.widgets import Input, Checkbox, Select
from textual.containers import Container
from textual.validation import Number, Integer
from gatekit.tui.widgets.selectable_static import SelectableStatic
from gatekit.tui.utils.json_pointer import (
    extract_required_leaf_fields,
)
from gatekit.tui.utils.field_registry import FieldRegistry
from gatekit.config.framework_fields import get_framework_fields


class JSONFormAdapter:
    """Generates Textual forms from core JSON Schema types.

    Supported:
    - Basic types: string, number, integer, boolean
    - Structures: object, array
    - Constraints: enum, pattern, minimum/maximum, required
    - Validation: minLength/maxLength (strings), minItems/maxItems (arrays)

    NOT supported (will show warning):
    - Conditional: oneOf, anyOf, allOf, if/then/else
    - Advanced: $ref (beyond single level), patternProperties, dependencies
    - Format: Beyond basic pattern matching
    """

    def __init__(
        self,
        schema: Dict[str, Any],
        initial_data: Dict[str, Any] = None,
        json_pointer_base: str = "",
        field_registry: FieldRegistry = None,
        ui_context: Optional[Dict[str, Any]] = None,
        group_framework_fields: bool = False,
    ):
        """Initialize with JSON Schema.

        Args:
            schema: JSON Schema object
            initial_data: Initial form data
            json_pointer_base: Base path for nested forms
            field_registry: Central field registry (created if not provided)
            ui_context: Optional UI context for specialized widgets
            group_framework_fields: If True, groups framework fields (enabled,
                critical, priority) in a visual container. Only enable for
                plugin config modal; other contexts (e.g., ObjectItemModal)
                should leave this False to avoid incorrect grouping.
        """
        self.schema = schema
        self.initial_data = initial_data or {}
        self.json_pointer_base = json_pointer_base
        self.field_registry = field_registry or FieldRegistry()
        self.widgets = {}  # name -> widget mapping (for backward compat)
        self.array_editors = {}  # name -> ArrayEditor mapping
        self.required_fields = extract_required_leaf_fields(schema, json_pointer_base)
        self.definitions = schema.get(
            "$defs", {}
        )  # Store definitions for $ref resolution
        self.ui_context = ui_context or {}
        self.group_framework_fields = group_framework_fields

    def can_generate_form(self) -> bool:
        """Check if we can generate a form for this schema.

        Returns True for any valid object schema.
        """
        return self.schema.get("type") == "object"

    def generate_form(self) -> ComposeResult:
        """Generate form widgets from schema.

        When group_framework_fields is True, framework fields (enabled, critical,
        priority) are grouped in a visual container at the top, followed by
        plugin-specific fields. Otherwise, all fields render in order.
        """
        if not self.can_generate_form():
            raise ValueError("Schema must be type 'object' for form generation")

        properties = self.schema.get("properties", {})
        required = set(self.schema.get("required", []))

        if self.group_framework_fields:
            # Get framework field names from authoritative source
            # Use "security" type which includes all three fields (enabled, critical, priority)
            framework_field_names: Set[str] = set(get_framework_fields("security").keys())

            framework_props = [
                (k, v) for k, v in properties.items() if k in framework_field_names
            ]
            plugin_props = [
                (k, v)
                for k, v in properties.items()
                if k not in framework_field_names and k != "handler"
            ]

            # Render framework fields in a visual container
            if framework_props:
                with Container(classes="framework-fields-container") as container:
                    container.border_title = "Plugin Settings"
                    for prop_name, prop_schema in framework_props:
                        initial_value = self.initial_data.get(prop_name)
                        yield from self._generate_field(
                            prop_name, prop_schema, prop_name in required, initial_value
                        )
                yield container

            # Render plugin-specific fields
            for prop_name, prop_schema in plugin_props:
                initial_value = self.initial_data.get(prop_name)
                yield from self._generate_field(
                    prop_name, prop_schema, prop_name in required, initial_value
                )
        else:
            # No grouping - render all fields in order (skip handler field)
            for prop_name, prop_schema in properties.items():
                if prop_name == "handler":
                    continue
                initial_value = self.initial_data.get(prop_name)
                yield from self._generate_field(
                    prop_name, prop_schema, prop_name in required, initial_value
                )

    def _resolve_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve $ref and allOf references in a schema.

        Args:
            schema: Schema that may contain references

        Returns:
            Resolved schema with references expanded
        """
        if "$ref" in schema:
            # Handle $ref - resolve to actual schema
            ref = schema["$ref"]
            if ref.startswith("#/$defs/"):
                def_name = ref.split("/")[-1]
                if def_name in self.definitions:
                    # Merge the referenced schema with any additional properties
                    resolved = self.definitions[def_name].copy()
                    # Add any extra properties from the original schema (except $ref)
                    for key, value in schema.items():
                        if key != "$ref":
                            resolved[key] = value
                    return resolved
            return schema  # Can't resolve, return as-is

        if "allOf" in schema:
            # Handle allOf - merge all schemas
            merged = {}
            for sub_schema in schema["allOf"]:
                resolved_sub = self._resolve_schema(sub_schema)
                # Merge properties
                if "properties" in resolved_sub:
                    if "properties" not in merged:
                        merged["properties"] = {}
                    merged["properties"].update(resolved_sub["properties"])
                # Take other properties from resolved_sub
                for key, value in resolved_sub.items():
                    if key != "properties":
                        merged[key] = value

            # Add any additional properties from the original schema
            for key, value in schema.items():
                if key not in ["allOf"]:
                    if key == "properties":
                        if "properties" not in merged:
                            merged["properties"] = {}
                        merged["properties"].update(value)
                    else:
                        merged[key] = value
            return merged

        return schema

    def _generate_field(
        self,
        name: str,
        schema: Dict[str, Any],
        required: bool,
        initial_value: Any = None,
    ) -> ComposeResult:
        """Generate widgets for a single field.

        CRITICAL: Check for enum BEFORE type to avoid treating enums as free-form fields.

        Args:
            name: Field name
            schema: Field schema
            required: Whether field is required
            initial_value: Initial value for the field
        """
        # Resolve any $ref or allOf references first
        schema = self._resolve_schema(schema)

        # Use 'title' from schema if available, otherwise generate from name
        label = schema.get("title", name.replace("_", " ").title())
        description = schema.get("description", "")
        default = initial_value if initial_value is not None else schema.get("default")
        field_type = schema.get("type")

        # Generate canonical JSON Pointer path
        field_path = f"{self.json_pointer_base}/properties/{name}"

        # Label with required indicator
        # Skip for:
        # - boolean fields (have inline labels)
        # - object fields (rendered as containers with border titles)
        # - array fields (ArrayEditor shows its own title and description)
        required_mark = " *" if required else ""
        if field_type not in ["boolean", "object", "array"]:
            yield SelectableStatic(f"{label}{required_mark}", classes="field-label")

        # Show description for standalone fields (for visual separation)
        # Skip for:
        # - objects (display description inside their container)
        # - arrays (ArrayEditor displays its own description)
        if description and field_type not in ["boolean", "object", "array"]:
            yield SelectableStatic(description, classes="field-description")

        # CRITICAL: Check enum FIRST before type
        if "enum" in schema:
            # Enum field - use Select regardless of type
            # Use x-enum-labels from schema if available, otherwise use value as-is
            enum_labels = schema.get("x-enum-labels", {})
            options = []
            for v in schema["enum"]:
                # Use explicit label from schema, or fall back to the value itself
                display_label = enum_labels.get(v, str(v))
                options.append((display_label, v))

            # Find initial selection
            initial_selection = default
            if initial_selection not in schema["enum"] and schema["enum"]:
                initial_selection = schema["enum"][0]

            # Never allow blank selection for enum fields:
            # - Required fields must have a value
            # - Optional fields with defaults can just keep the default
            # - Enum fields always have a sensible first option as fallback
            widget = Select(options, value=initial_selection, allow_blank=False)
            # Register with field registry
            self.field_registry.register(
                field_path, widget, schema, required
            )
            yield widget

        elif field_type == "boolean":
            # Include required mark in checkbox label
            checkbox_label = f"{label}{required_mark}"
            widget = Checkbox(
                checkbox_label,
                value=bool(default) if default is not None else False,
                classes="inline-checkbox",
            )
            # Register with field registry
            self.field_registry.register(
                field_path, widget, schema, required
            )
            yield widget

        elif field_type in ["string", "number", "integer"]:
            # Build placeholder with validation hints
            placeholder = f"Enter {label.lower()}"

            # Add pattern hint
            if "pattern" in schema:
                placeholder += f" (pattern: {schema['pattern']})"

            # Add range hints
            if "minimum" in schema and "maximum" in schema:
                placeholder += f" ({schema['minimum']}-{schema['maximum']})"
            elif "minimum" in schema:
                placeholder += f" (min: {schema['minimum']})"
            elif "maximum" in schema:
                placeholder += f" (max: {schema['maximum']})"

            # Add length hints for strings
            if field_type == "string":
                if "minLength" in schema and "maxLength" in schema:
                    placeholder += (
                        f" ({schema['minLength']}-{schema['maxLength']} chars)"
                    )
                elif "minLength" in schema:
                    placeholder += f" (min {schema['minLength']} chars)"
                elif "maxLength" in schema:
                    placeholder += f" (max {schema['maxLength']} chars)"

            # Set the input type based on the field type
            input_type = "text"
            validators = []
            css_classes = ""

            if field_type == "integer":
                input_type = "integer"
                css_classes = "integer-input"
                # Add Integer validator with min/max if specified
                min_val = schema.get("minimum")
                max_val = schema.get("maximum")
                if min_val is not None or max_val is not None:
                    validators.append(Integer(minimum=min_val, maximum=max_val))
            elif field_type == "number":
                input_type = "number"
                css_classes = "number-input"
                # Add Number validator with min/max if specified
                min_val = schema.get("minimum")
                max_val = schema.get("maximum")
                if min_val is not None or max_val is not None:
                    validators.append(Number(minimum=min_val, maximum=max_val))

            # Check for custom widget type
            x_widget = schema.get("x-widget")
            if x_widget == "file-path" and field_type == "string":
                # Use FilePathField for file path inputs
                from gatekit.tui.widgets.file_path_field import FilePathField

                # Get config directory from ui_context for resolving relative paths
                config_dir = self.ui_context.get("config_dir") if self.ui_context else None

                widget = FilePathField(
                    value=str(default) if default is not None else "",
                    placeholder=placeholder,
                    config_dir=config_dir,
                )
                # Register with field registry
                self.field_registry.register(
                    field_path, widget, schema, required
                )
                yield widget
            else:
                widget = Input(
                    value=str(default) if default is not None else "",
                    placeholder=placeholder,
                    type=input_type,
                    validators=validators if validators else None,
                    classes=css_classes if css_classes else None,
                )
                # Register with field registry
                self.field_registry.register(
                    field_path, widget, schema, required
                )
                yield widget

        elif field_type == "array":
            if self._should_use_tool_selector(schema):
                yield SelectableStatic(f"{label}{required_mark}", classes="field-label")
                if description:
                    yield SelectableStatic(description, classes="field-description")

                from gatekit.tui.widgets.tool_selection_field import ToolSelectionField

                discovery_context = self.ui_context.get("tool_selector", {})
                discovery = discovery_context.get("discovery")

                initial_entries = initial_value if isinstance(initial_value, list) else []

                widget = ToolSelectionField(name, initial_entries, discovery)
                self.field_registry.register(field_path, widget, schema, required)
                yield widget
                return

            # Use ArrayEditor for array handling
            from gatekit.tui.utils.array_editor import ArrayEditor

            array_editor = ArrayEditor(
                name, schema, initial_value or [], self.json_pointer_base
            )
            self.field_registry.register(
                field_path, array_editor, schema, required
            )
            self.array_editors[name] = array_editor
            yield array_editor

        elif field_type == "object":
            # For all objects, use normal nested rendering
            # The pattern detection for objects with single "enabled" property
            # is now handled inside _generate_nested_object
            yield from self._generate_nested_object(name, schema, initial_value or {})

        else:
            # Fallback for any unhandled types
            yield SelectableStatic(f"Unsupported type: {field_type}", classes="error")

    def _generate_nested_object(
        self, name: str, schema: Dict[str, Any], initial_value: Dict[str, Any]
    ) -> ComposeResult:
        """Generate widgets for a nested object.

        Args:
            name: Object field name
            schema: Object schema
            initial_value: Initial object value
        """
        nested_path = f"{self.json_pointer_base}/properties/{name}"

        # Use title from schema if available, otherwise generate from name
        title = schema.get("title", name.replace("_", " ").title())

        # Create a container with border for the nested object
        with Container(classes="nested-object-container") as container:
            container.border_title = title

            # Show description if available
            description = schema.get("description")
            if description:
                yield SelectableStatic(description, classes="field-description")

            # Build all child widgets inside the container
            properties = schema.get("properties", {})
            required = set(schema.get("required", []))

            # First resolve all properties to check for patterns
            resolved_props = {}
            for prop_name, prop_schema in properties.items():
                resolved_props[prop_name] = self._resolve_schema(prop_schema)

            # Generate widgets inside the container
            for prop_name, prop_schema in resolved_props.items():
                # Check if this is an object with just an "enabled" boolean
                # If so, render as a single checkbox instead of nested structure
                if (
                    prop_schema.get("type") == "object"
                    and "properties" in prop_schema
                    and len(prop_schema["properties"]) == 1
                    and "enabled" in prop_schema["properties"]
                    and prop_schema["properties"]["enabled"].get("type") == "boolean"
                ):

                    # Render as single checkbox with property name as label
                    # Use schema title if available, otherwise generate from name
                    checkbox_label = prop_schema.get(
                        "title", prop_name.replace("_", " ").title()
                    )

                    # Add required mark if needed
                    if prop_name in required:
                        checkbox_label += " *"

                    # Get the initial value for this nested enabled property
                    nested_value = False
                    nested_initial = initial_value.get(prop_name)
                    if nested_initial and isinstance(nested_initial, dict):
                        nested_value = bool(nested_initial.get("enabled", False))

                    widget = Checkbox(
                        checkbox_label, value=nested_value, classes="inline-checkbox"
                    )

                    # Register with correct path to the enabled property
                    field_path = (
                        f"{nested_path}/properties/{prop_name}/properties/enabled"
                    )
                    self.field_registry.register(
                        field_path, widget, prop_schema["properties"]["enabled"], False
                    )

                    yield widget
                else:
                    # Normal nested field rendering
                    nested_initial = initial_value.get(prop_name)

                    # Generate field with nested path
                    yield from self._generate_nested_field(
                        name,
                        prop_name,
                        prop_schema,
                        prop_name in required,
                        nested_initial,
                        nested_path,
                    )

        # Yield the complete container
        yield container

    def _generate_nested_field(
        self,
        parent_name: str,
        field_name: str,
        schema: Dict[str, Any],
        required: bool,
        initial_value: Any,
        parent_path: str,
    ) -> ComposeResult:
        """Generate a field within a nested object.

        Args:
            parent_name: Parent object name
            field_name: Field name within object
            schema: Field schema
            required: Whether field is required
            initial_value: Initial value
            parent_path: Parent JSON Pointer path
        """
        # Create a temporary adapter for the nested field, sharing the registry
        # Include $defs in the temporary schema so references can be resolved
        temp_schema = {"type": "object", "properties": {field_name: schema}}
        if self.definitions:
            temp_schema["$defs"] = self.definitions

        nested_adapter = JSONFormAdapter(
            temp_schema,
            {field_name: initial_value} if initial_value is not None else {},
            parent_path,
            self.field_registry,  # Share the same registry
            ui_context=self.ui_context,
        )

        # Generate just this field
        yield from nested_adapter._generate_field(
            field_name, schema, required, initial_value
        )

        # No longer using compound names - registry handles all mapping

    def get_form_data(self) -> Dict[str, Any]:
        """Extract data from form widgets using field registry.

        Returns:
            Dictionary of form data
        """
        from gatekit.tui.debug import get_debug_logger

        logger = get_debug_logger()
        data = {}

        if logger:
            logger.log_event(
                "get_form_data_start",
                context={
                    "json_pointer_base": self.json_pointer_base,
                    "registry_count": len(self.field_registry.by_pointer),
                    "registry_pointers": sorted(self.field_registry.by_pointer.keys()),
                },
            )

        # Build data structure from registry
        for pointer, info in self.field_registry.by_pointer.items():
            if not pointer.startswith(self.json_pointer_base):
                continue  # Skip fields from other forms

            # Get widget value
            widget = info.widget
            value = None

            if isinstance(widget, Checkbox):
                value = widget.value
            elif isinstance(widget, Select):
                # Convert Select.BLANK to None so Pydantic sees it as missing
                value = widget.value if widget.value != Select.BLANK else None
            elif isinstance(widget, Input):
                value = widget.value
                # Type conversion based on schema
                field_type = info.schema.get("type")
                if field_type == "integer":
                    try:
                        value = int(value) if value else None
                    except ValueError:
                        value = None
                elif field_type == "number":
                    try:
                        value = float(value) if value else None
                    except ValueError:
                        value = None
            elif hasattr(widget, "value") and hasattr(widget, "_input"):
                # FilePathField and similar composite widgets with a value property
                value = widget.value
            elif hasattr(widget, "get_value"):
                # Handle ArrayEditor and other custom widgets with get_value
                value = widget.get_value()

            if value is not None:
                # Parse pointer to reconstruct data structure
                self._set_nested_value(data, pointer, value)

        # Array data is already handled by the registry via hasattr(widget, 'get_value')
        # No need for a second pass that would corrupt nested arrays

        if logger:
            logger.log_event(
                "get_form_data_result",
                context={"result_keys": sorted(data.keys())},
                data={"form_data": data},
            )

        return data

    def _set_nested_value(self, data: Dict[str, Any], pointer: str, value: Any):
        """Set a value in nested dict structure based on JSON Pointer.

        Args:
            data: Dictionary to update
            pointer: JSON Pointer path
            value: Value to set
        """
        # Remove base path if present
        if self.json_pointer_base and pointer.startswith(self.json_pointer_base):
            pointer = pointer[len(self.json_pointer_base) :]

        # Parse pointer path
        parts = pointer.strip("/").split("/")

        # Skip "properties" segments
        parts = [p for p in parts if p != "properties" and p != "items"]

        # Navigate to parent
        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        # Set the value
        if parts:
            current[parts[-1]] = value

    def _should_use_tool_selector(self, schema: Dict[str, Any]) -> bool:
        """Detect the Tool Manager tool array schema pattern."""
        # Resolved schema retains the fragment's $id; unresolved contains a $ref.
        fragment_ids = {
            "https://gatekit.ai/schemas/common/tool-selection.json",
            "#/$defs/tool_selection",
        }

        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id in fragment_ids:
            return True

        ref = schema.get("$ref")
        if isinstance(ref, str) and ref in fragment_ids:
            return True

        return False
