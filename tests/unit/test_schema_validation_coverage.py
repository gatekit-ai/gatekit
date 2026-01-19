"""Tests verifying JSON schema catches validation errors.

These tests ensure schema validation provides the same protection that was
previously duplicated in runtime code. Schema validation runs BEFORE plugin
__init__ in both Gateway (ConfigLoader) and TUI (modal), so plugins can
trust schema validation has already occurred.

See docs/todos/plugin-validation-single-source-of-truth.md for context.
"""

import pytest
from gatekit.config.json_schema import get_schema_validator


class TestToolManagerSchemaValidation:
    """Verify tool_manager schema catches invalid configs."""

    @pytest.fixture
    def validator(self):
        return get_schema_validator()

    def test_schema_rejects_invalid_tool_name(self, validator):
        """Schema should reject tool names not starting with letter."""
        config = {
            "enabled": True,
            "tools": [{"tool": "123invalid"}]
        }
        errors = validator.validate("tool_manager", config)
        assert errors, "Schema should reject tool name starting with number"
        assert any("pattern" in e.lower() or "123invalid" in e for e in errors)

    def test_schema_rejects_invalid_display_name(self, validator):
        """Schema should reject display_name not matching pattern."""
        config = {
            "enabled": True,
            "tools": [{"tool": "test", "display_name": "Has Spaces"}]
        }
        errors = validator.validate("tool_manager", config)
        assert errors, "Schema should reject display_name with spaces"
        assert any("pattern" in e.lower() or "Has Spaces" in e for e in errors)

    def test_schema_rejects_display_name_starting_with_number(self, validator):
        """Schema should reject display_name starting with number."""
        config = {
            "enabled": True,
            "tools": [{"tool": "test", "display_name": "123invalid"}]
        }
        errors = validator.validate("tool_manager", config)
        assert errors, "Schema should reject display_name starting with number"

    def test_schema_rejects_display_description_null(self, validator):
        """Schema should reject display_description: null (use omission instead)."""
        config = {
            "enabled": True,
            "tools": [{"tool": "test", "display_description": None}]
        }
        errors = validator.validate("tool_manager", config)
        assert errors, "Schema should reject display_description: null"

    def test_schema_accepts_valid_tool_config(self, validator):
        """Schema should accept valid tool configuration."""
        config = {
            "enabled": True,
            "tools": [
                {"tool": "read_file"},
                {"tool": "execute", "display_name": "run_script", "display_description": "Run scripts"}
            ]
        }
        errors = validator.validate("tool_manager", config)
        assert not errors, f"Schema should accept valid config, got: {errors}"

    def test_schema_accepts_hyphens_and_underscores(self, validator):
        """Schema should accept tool names with hyphens and underscores."""
        config = {
            "enabled": True,
            "tools": [
                {"tool": "read-file"},
                {"tool": "list_directory"},
                {"tool": "test", "display_name": "my-custom_tool"}
            ]
        }
        errors = validator.validate("tool_manager", config)
        assert not errors, f"Schema should accept hyphens/underscores, got: {errors}"


class TestCsvSchemaValidation:
    """Verify audit_csv schema catches invalid configs."""

    @pytest.fixture
    def validator(self):
        return get_schema_validator()

    def test_schema_rejects_invalid_quote_style(self, validator):
        """Schema should reject invalid quote_style enum value."""
        config = {
            "enabled": True,
            "output_file": "test.csv",
            "csv_config": {"quote_style": "invalid_style"}
        }
        errors = validator.validate("audit_csv", config)
        assert errors, "Schema should reject invalid quote_style"
        assert any("invalid_style" in e or "enum" in e.lower() for e in errors)

    def test_schema_accepts_valid_quote_styles(self, validator):
        """Schema should accept all valid quote_style values."""
        for style in ["minimal", "all", "nonnumeric", "none"]:
            config = {
                "enabled": True,
                "output_file": "test.csv",
                "csv_config": {"quote_style": style}
            }
            errors = validator.validate("audit_csv", config)
            assert not errors, f"Schema should accept quote_style '{style}', got: {errors}"


class TestPiiFilterSchemaValidation:
    """Verify basic_pii_filter schema catches invalid configs."""

    @pytest.fixture
    def validator(self):
        return get_schema_validator()

    def test_schema_rejects_invalid_action(self, validator):
        """Schema should reject invalid action enum value."""
        config = {
            "enabled": True,
            "action": "invalid_action"
        }
        errors = validator.validate("basic_pii_filter", config)
        assert errors, "Schema should reject invalid action"

    def test_schema_accepts_valid_actions(self, validator):
        """Schema should accept all valid action values."""
        for action in ["block", "redact", "audit_only"]:
            config = {
                "enabled": True,
                "action": action
            }
            errors = validator.validate("basic_pii_filter", config)
            assert not errors, f"Schema should accept action '{action}', got: {errors}"

    def test_schema_rejects_custom_patterns_field(self, validator):
        """Schema should reject custom_patterns (removed feature)."""
        config = {
            "enabled": True,
            "action": "redact",
            "custom_patterns": [{"pattern": "test", "name": "test"}]
        }
        errors = validator.validate("basic_pii_filter", config)
        assert errors, "Schema should reject custom_patterns field"


class TestSecretsFilterSchemaValidation:
    """Verify basic_secrets_filter schema catches invalid configs."""

    @pytest.fixture
    def validator(self):
        return get_schema_validator()

    def test_schema_rejects_invalid_action(self, validator):
        """Schema should reject invalid action enum value."""
        config = {
            "enabled": True,
            "action": "invalid_action"
        }
        errors = validator.validate("basic_secrets_filter", config)
        assert errors, "Schema should reject invalid action"

    def test_schema_rejects_custom_patterns_field(self, validator):
        """Schema should reject custom_patterns (removed feature)."""
        config = {
            "enabled": True,
            "action": "redact",
            "custom_patterns": [{"pattern": "test", "name": "test"}]
        }
        errors = validator.validate("basic_secrets_filter", config)
        assert errors, "Schema should reject custom_patterns field"

    def test_schema_rejects_allowlist_field(self, validator):
        """Schema should reject allowlist (removed feature)."""
        config = {
            "enabled": True,
            "action": "redact",
            "allowlist": {"patterns": ["test"]}
        }
        errors = validator.validate("basic_secrets_filter", config)
        assert errors, "Schema should reject allowlist field"

    def test_schema_rejects_detection_types_field(self, validator):
        """Schema should reject detection_types (use secret_types instead)."""
        config = {
            "enabled": True,
            "action": "redact",
            "detection_types": {}
        }
        errors = validator.validate("basic_secrets_filter", config)
        assert errors, "Schema should reject detection_types field"


class TestPromptInjectionSchemaValidation:
    """Verify basic_prompt_injection_defense schema catches invalid configs."""

    @pytest.fixture
    def validator(self):
        return get_schema_validator()

    def test_schema_rejects_invalid_action(self, validator):
        """Schema should reject invalid action enum value."""
        config = {
            "enabled": True,
            "action": "invalid_action"
        }
        errors = validator.validate("basic_prompt_injection_defense", config)
        assert errors, "Schema should reject invalid action"

    def test_schema_rejects_invalid_sensitivity(self, validator):
        """Schema should reject invalid sensitivity enum value."""
        config = {
            "enabled": True,
            "action": "block",
            "sensitivity": "invalid_level"
        }
        errors = validator.validate("basic_prompt_injection_defense", config)
        assert errors, "Schema should reject invalid sensitivity"

    def test_schema_accepts_valid_sensitivity_levels(self, validator):
        """Schema should accept all valid sensitivity values."""
        for level in ["relaxed", "standard", "strict"]:
            config = {
                "enabled": True,
                "action": "block",
                "sensitivity": level
            }
            errors = validator.validate("basic_prompt_injection_defense", config)
            assert not errors, f"Schema should accept sensitivity '{level}', got: {errors}"

    def test_schema_rejects_custom_patterns_field(self, validator):
        """Schema should reject custom_patterns (removed feature)."""
        config = {
            "enabled": True,
            "action": "block",
            "custom_patterns": [{"pattern": "test", "name": "test"}]
        }
        errors = validator.validate("basic_prompt_injection_defense", config)
        assert errors, "Schema should reject custom_patterns field"


class TestJsonLinesSchemaValidation:
    """Verify audit_jsonl schema catches invalid configs."""

    @pytest.fixture
    def validator(self):
        return get_schema_validator()

    def test_schema_rejects_pretty_print_field(self, validator):
        """Schema should reject pretty_print (removed feature)."""
        config = {
            "enabled": True,
            "output_file": "test.jsonl",
            "pretty_print": True
        }
        errors = validator.validate("audit_jsonl", config)
        assert errors, "Schema should reject pretty_print field"


class TestBusinessLogicStillWorks:
    """Verify business logic validation (not in schema) still works."""

    def test_duplicate_tool_still_rejected(self):
        """Business logic should catch duplicate tools."""
        from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
        config = {
            "enabled": True,
            "tools": [{"tool": "read_file"}, {"tool": "read_file"}]
        }
        with pytest.raises(ValueError, match="Duplicate"):
            ToolManagerPlugin(config)

    def test_self_rename_still_rejected(self):
        """Business logic should reject self-rename."""
        from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
        config = {
            "enabled": True,
            "tools": [{"tool": "test", "display_name": "test"}]
        }
        with pytest.raises(ValueError, match="Cannot rename.*to itself"):
            ToolManagerPlugin(config)

    def test_rename_collision_still_rejected(self):
        """Business logic should reject rename collisions."""
        from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin
        config = {
            "enabled": True,
            "tools": [
                {"tool": "execute", "display_name": "new_tool"},
                {"tool": "query", "display_name": "new_tool"},
            ]
        }
        with pytest.raises(ValueError, match="already renamed to"):
            ToolManagerPlugin(config)
