"""Tests for plugin JSON schemas.

Note: Framework fields (enabled, priority) are injected by the framework layer,
not defined in individual plugin schemas. See gatekit/config/framework_fields.py.
"""

import pytest
from jsonschema import Draft202012Validator, ValidationError
from gatekit.plugins.security.pii import BasicPIIFilterPlugin
from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
from gatekit.plugins.security.secrets import BasicSecretsFilterPlugin
from gatekit.plugins.auditing.csv import CsvAuditingPlugin
from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin
from gatekit.config.framework_fields import inject_framework_fields


class TestPluginSchemas:
    """Test that all plugin JSON schemas are valid and complete."""

    def test_pii_plugin_schema(self):
        """Test PII plugin JSON schema is valid."""
        raw_schema = BasicPIIFilterPlugin.get_json_schema()
        # Framework fields are injected by the framework layer
        schema = inject_framework_fields(raw_schema, "security")

        # Should return a valid JSON Schema
        assert isinstance(schema, dict)
        assert "$schema" in schema
        assert schema["type"] == "object"

        # Validate the schema itself is valid JSON Schema
        Draft202012Validator.check_schema(schema)

        # Check required properties (enabled/priority are framework fields)
        properties = schema["properties"]
        assert "enabled" in properties
        assert "priority" in properties
        assert "action" in properties
        assert "pii_types" in properties

        # Check action enum contains valid values (schema is source of truth)
        assert properties["action"]["enum"] == ["block", "redact", "audit_only"]

        # Check pii_types structure
        assert properties["pii_types"]["type"] == "object"
        pii_properties = properties["pii_types"]["properties"]

        # Should have entries for each PII type (including ssn as alias)
        expected_pii_types = set(BasicPIIFilterPlugin.PII_TYPES.keys())
        actual_pii_types = set(pii_properties.keys())
        assert expected_pii_types == actual_pii_types

    def test_tool_manager_plugin_schema(self):
        """Test Tool Manager plugin JSON schema is valid."""
        raw_schema = ToolManagerPlugin.get_json_schema()
        # Framework fields are injected by the framework layer
        schema = inject_framework_fields(raw_schema, "middleware")

        assert isinstance(schema, dict)
        assert "$schema" in schema

        # Validate the schema itself
        Draft202012Validator.check_schema(schema)

        # Check required properties (enabled/priority are framework fields)
        properties = schema["properties"]
        assert "enabled" in properties
        assert "priority" in properties
        assert "tools" in properties

        # Check the tools field uses $ref to tool_selection
        assert "$ref" in properties["tools"]
        assert properties["tools"]["$ref"] == "#/$defs/tool_selection"

        # Check that $defs contains tool_selection definition
        assert "$defs" in schema
        assert "tool_selection" in schema["$defs"]

        # Check tool_selection structure
        tool_selection = schema["$defs"]["tool_selection"]
        assert tool_selection["type"] == "array"
        assert "items" in tool_selection

        # Check tool entry properties
        items_schema = tool_selection["items"]
        tool_props = items_schema["properties"]
        assert "tool" in tool_props
        assert "action" not in tool_props  # Action field removed
        assert "display_name" in tool_props
        assert "display_description" in tool_props

    def test_secrets_plugin_schema(self):
        """Test Secrets plugin JSON schema is valid."""
        raw_schema = BasicSecretsFilterPlugin.get_json_schema()
        # Framework fields are injected by the framework layer
        schema = inject_framework_fields(raw_schema, "security")

        assert isinstance(schema, dict)
        assert "$schema" in schema

        # Validate the schema itself
        Draft202012Validator.check_schema(schema)

        # Check required properties (enabled/priority are framework fields)
        properties = schema["properties"]
        assert "enabled" in properties
        assert "priority" in properties
        assert "action" in properties
        assert "secret_types" in properties

        # Check action enum contains valid values (schema is source of truth)
        assert properties["action"]["enum"] == ["block", "redact", "audit_only"]

    def test_csv_auditing_plugin_schema(self):
        """Test CSV auditing plugin JSON schema is valid."""
        raw_schema = CsvAuditingPlugin.get_json_schema()
        # Auditing plugins only get enabled (no priority)
        schema = inject_framework_fields(raw_schema, "auditing")

        assert isinstance(schema, dict)
        assert "$schema" in schema

        # Validate the schema itself
        Draft202012Validator.check_schema(schema)

        # Check required properties (enabled is framework field, no priority for auditing)
        properties = schema["properties"]
        assert "enabled" in properties
        assert "priority" not in properties  # Auditing plugins don't have priority
        assert "output_file" in properties
        assert "csv_config" in properties

        # Check csv_config structure
        format_config = properties["csv_config"]
        assert format_config["type"] == "object"

        format_props = format_config["properties"]
        assert "delimiter" in format_props
        assert "quote_style" in format_props

        # Check delimiter options
        assert format_props["delimiter"]["enum"] == [",", "\t", ";", "|"]

    def test_json_auditing_plugin_schema(self):
        """Test JSON auditing plugin JSON schema is valid."""
        raw_schema = JsonAuditingPlugin.get_json_schema()
        # Auditing plugins only get enabled (no priority)
        schema = inject_framework_fields(raw_schema, "auditing")

        assert isinstance(schema, dict)
        assert "$schema" in schema

        # Validate the schema itself
        Draft202012Validator.check_schema(schema)

        # Check required properties (enabled is framework field, no priority for auditing)
        properties = schema["properties"]
        assert "enabled" in properties
        assert "priority" not in properties  # Auditing plugins don't have priority
        assert "output_file" in properties
        assert "include_request_body" in properties

        # Check boolean fields
        assert properties["include_request_body"]["type"] == "boolean"


class TestPluginSchemaDefaults:
    """Test plugin JSON schema default values."""

    def test_pii_plugin_defaults(self):
        """Test PII plugin default values are reasonable."""
        raw_schema = BasicPIIFilterPlugin.get_json_schema()
        schema = inject_framework_fields(raw_schema, "security")
        properties = schema["properties"]

        # Framework fields have defaults
        assert properties["enabled"]["default"] is True
        assert properties["priority"]["default"] == 50  # Framework default

        # Plugin-specific defaults
        assert properties["action"]["default"] == "redact"
        assert not properties["scan_base64"]["default"]

    def test_tool_manager_plugin_defaults(self):
        """Test Tool Manager plugin default values are reasonable."""
        raw_schema = ToolManagerPlugin.get_json_schema()
        schema = inject_framework_fields(raw_schema, "middleware")
        properties = schema["properties"]

        # Framework fields have defaults
        assert properties["enabled"]["default"] is True
        assert properties["priority"]["default"] == 50

    def test_csv_auditing_plugin_defaults(self):
        """Test CSV auditing plugin default values and required fields."""
        raw_schema = CsvAuditingPlugin.get_json_schema()
        schema = inject_framework_fields(raw_schema, "auditing")
        properties = schema["properties"]

        # Framework field defaults (auditing has no priority)
        assert properties["enabled"]["default"] is True

        # output_file is required and has a sensible default
        assert "output_file" in schema.get("required", [])
        assert properties["output_file"]["default"] == "logs/gatekit_audit.csv"

        format_props = properties["csv_config"]["properties"]
        assert format_props["delimiter"]["default"] == ","
        assert format_props["quote_style"]["default"] == "minimal"


class TestPluginSchemaValidation:
    """Test plugin JSON schema field validation rules."""

    def test_pii_plugin_priority_constraints(self):
        """Test PII plugin priority field constraints (from framework)."""
        raw_schema = BasicPIIFilterPlugin.get_json_schema()
        schema = inject_framework_fields(raw_schema, "security")
        priority_field = schema["properties"]["priority"]

        assert priority_field["type"] == "integer"
        assert priority_field["minimum"] == 0
        assert priority_field["maximum"] == 100

    def test_tool_manager_pattern_validation(self):
        """Test Tool Manager plugin tool name pattern validation."""
        schema = ToolManagerPlugin.get_json_schema()

        # Test tools field pattern validation - resolve $ref
        tool_selection = schema["$defs"]["tool_selection"]
        items_schema = tool_selection["items"]
        tool_props = items_schema["properties"]

        # Pattern is in the tool field
        assert "tool" in tool_props
        assert tool_props["tool"]["type"] == "string"
        assert "pattern" in tool_props["tool"]
        pattern = tool_props["tool"]["pattern"]

        # Test the pattern with valid/invalid tool names
        import re

        compiled_pattern = re.compile(pattern)

        # Valid tool names (new pattern allows hyphens)
        assert compiled_pattern.match("valid_tool_name")
        assert compiled_pattern.match("tool123")
        assert compiled_pattern.match("tool-with-hyphens")  # hyphens are now allowed

        # Invalid tool names
        assert not compiled_pattern.match("123invalid")  # starts with number
        assert not compiled_pattern.match(
            "_underscore_start"
        )  # can't start with underscore
        assert not compiled_pattern.match("invalid space")  # contains space

    def test_schema_validation_with_jsonschema(self):
        """Test that schemas can validate actual configurations."""
        # Test Tool Manager validation with framework fields injected
        raw_schema = ToolManagerPlugin.get_json_schema()
        schema = inject_framework_fields(raw_schema, "middleware")
        validator = Draft202012Validator(schema)

        # Valid configuration (includes framework field 'enabled')
        valid_config = {
            "enabled": True,
            "tools": [{"tool": "read_file"}, {"tool": "write_file"}],
        }
        # Should not raise
        validator.validate(valid_config)

        # Invalid configuration (missing required field)
        invalid_config = {
            "enabled": True
            # Missing required "tools" field
        }
        with pytest.raises(ValidationError) as exc_info:
            validator.validate(invalid_config)
        assert "'tools' is a required property" in str(exc_info.value)
