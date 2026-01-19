"""Tests for config error handling system."""

import pytest
import tempfile
from pathlib import Path
from gatekit.config.errors import ConfigError
from gatekit.config.loader import ConfigLoader
from gatekit.config.models import ProxyConfig


class TestConfigError:
    """Test ConfigError exception class behavior."""

    def test_minimal_config_error_creation(self):
        """Test creating a minimal ConfigError with just message and type."""
        error = ConfigError(message="Test error", error_type="yaml_syntax")

        assert error.message == "Test error"
        assert error.error_type == "yaml_syntax"
        assert error.error_code == "CFG_YAML_SYNTAX"
        assert error.file_path is None
        assert error.line_number is None
        assert error.field_path is None
        assert error.line_snippet is None
        assert error.suggestions == []
        assert error.can_edit is True
        assert error.can_ignore is False

    def test_config_error_with_all_fields(self):
        """Test creating a ConfigError with all fields populated."""
        file_path = Path("/test/config.yaml")
        suggestions = [
            "Fix indentation",
            "Check syntax",
            "",
        ]  # Include empty suggestion to test filtering

        error = ConfigError(
            message="YAML parse error",
            error_type="yaml_syntax",
            file_path=file_path,
            line_number=42,
            field_path="plugins.auditing.handler",
            suggestions=suggestions,
            line_snippet="  bad_indent: value",
        )

        assert error.message == "YAML parse error"
        assert error.error_type == "yaml_syntax"
        assert error.error_code == "CFG_YAML_SYNTAX"
        assert error.file_path == file_path
        assert error.line_number == 42
        assert error.field_path == "plugins.auditing.handler"
        assert error.line_snippet == "  bad_indent: value"
        # Empty suggestions should be filtered out
        assert error.suggestions == ["Fix indentation", "Check syntax"]
        assert error.can_edit is True
        assert error.can_ignore is False

    def test_missing_plugin_error_can_be_ignored(self):
        """Test that missing_plugin errors can be safely ignored."""
        error = ConfigError(message="Plugin not found", error_type="missing_plugin")

        assert error.can_ignore is True
        assert error.can_edit is True

    def test_validation_error_cannot_be_ignored(self):
        """Test that validation errors cannot be safely ignored."""
        error = ConfigError(
            message="Invalid configuration", error_type="validation_error"
        )

        assert error.can_ignore is False
        assert error.can_edit is True

    def test_suggestions_limited_to_three_maximum(self):
        """Test that suggestions are limited to maximum of 3."""
        many_suggestions = [
            "Suggestion 1",
            "Suggestion 2",
            "Suggestion 3",
            "Suggestion 4",
            "Suggestion 5",
        ]

        error = ConfigError(
            message="Test error", error_type="yaml_syntax", suggestions=many_suggestions
        )

        assert len(error.suggestions) == 3
        assert error.suggestions == ["Suggestion 1", "Suggestion 2", "Suggestion 3"]

    def test_error_code_generation(self):
        """Test that error codes are generated correctly."""
        yaml_error = ConfigError("Test", "yaml_syntax")
        plugin_error = ConfigError("Test", "missing_plugin")
        validation_error = ConfigError("Test", "validation_error")

        assert yaml_error.error_code == "CFG_YAML_SYNTAX"
        assert plugin_error.error_code == "CFG_MISSING_PLUGIN"
        assert validation_error.error_code == "CFG_VALIDATION_ERROR"

    def test_string_representation(self):
        """Test that ConfigError has a reasonable string representation."""
        error = ConfigError(message="Test error message", error_type="yaml_syntax")

        # Should use the Exception's default __str__ which returns the message
        assert str(error) == "Test error message"


class TestConfigLoaderErrorHandling:
    """Test ConfigLoader enhanced error handling."""

    def test_empty_config_file_raises_config_error(self):
        """Test that empty config files raise ConfigError with yaml_syntax type."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")  # Empty file
            config_path = Path(f.name)

        try:
            loader = ConfigLoader()
            with pytest.raises(ConfigError) as exc_info:
                loader.load_from_file(config_path)

            error = exc_info.value
            assert error.error_type == "yaml_syntax"
            assert error.message == "Configuration file is empty"
            assert str(error.file_path) == str(config_path.resolve())
            assert error.line_number is None
            assert error.line_snippet is None
            assert "Add basic config structure" in error.suggestions
            assert "Check file was saved properly" in error.suggestions
        finally:
            config_path.unlink()

    def test_yaml_syntax_error_with_line_number(self):
        """Test YAML syntax errors include line numbers and snippets."""
        bad_yaml = """proxy:
  transport: stdio
  upstreams:
    - name: test
      command: echo hello
    bad_indent: value  # Wrong indentation
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(bad_yaml)
            config_path = Path(f.name)

        try:
            loader = ConfigLoader()
            with pytest.raises(ConfigError) as exc_info:
                loader.load_from_file(config_path)

            error = exc_info.value
            assert error.error_type == "yaml_syntax"
            assert "YAML syntax error:" in error.message
            assert str(error.file_path) == str(config_path.resolve())
            assert error.line_number == 6  # The problematic line
            assert "bad_indent: value" in error.line_snippet
            assert len(error.suggestions) >= 1
        finally:
            config_path.unlink()

    def test_yaml_error_suggestions_generation(self):
        """Test that YAML error suggestions are generated based on error type."""
        # Test tab character error
        bad_yaml = "proxy:\n\ttransport: stdio\n  upstreams:\n    - name: test"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(bad_yaml)
            config_path = Path(f.name)

        try:
            loader = ConfigLoader()
            with pytest.raises(ConfigError) as exc_info:
                loader.load_from_file(config_path)

            error = exc_info.value
            assert error.error_type == "yaml_syntax"
            assert len(error.suggestions) <= 3  # Max 3 suggestions
            # Should specifically suggest replacing tabs with spaces for tab character errors
            assert error.suggestions[0] == "Replace tabs with spaces"
        finally:
            config_path.unlink()

    def test_line_snippet_secret_redaction(self):
        """Test that secrets are redacted from line snippets."""
        # Create YAML with a tab character (causes parsing error) and password
        yaml_with_secret = "proxy:\n  transport: stdio\n  password: secret123\n\tupstreams:\n    - name: test"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_with_secret)
            config_path = Path(f.name)

        try:
            loader = ConfigLoader()
            with pytest.raises(ConfigError) as exc_info:
                loader.load_from_file(config_path)

            error = exc_info.value
            # Should have line snippet but with redacted secrets if any
            if error.line_snippet and "password" in error.line_snippet:
                assert "****" in error.line_snippet
                assert "secret123" not in error.line_snippet
        finally:
            config_path.unlink()

    def test_line_snippet_truncation(self):
        """Test that very long line snippets are truncated."""
        long_line = "a" * 100  # 100 character line
        # Create YAML with tab character and long line
        yaml_with_long_line = f"proxy:\n  transport: stdio\n  {long_line}: value\n\tupstreams:\n    - name: test"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_with_long_line)
            config_path = Path(f.name)

        try:
            loader = ConfigLoader()
            with pytest.raises(ConfigError) as exc_info:
                loader.load_from_file(config_path)

            error = exc_info.value
            if error.line_snippet and len(error.line_snippet) > 80:
                assert error.line_snippet.endswith("...")
        finally:
            config_path.unlink()


class TestMissingPluginErrorHandling:
    """Test missing plugin error handling with fuzzy suggestions."""

    def test_missing_plugin_error_with_fuzzy_suggestion(self):
        """Test that missing plugins show fuzzy suggestions."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            },
            "plugins": {
                "auditing": {
                    "_global": [
                        {
                            "handler": "json_auditng",
                            "config": {"enabled": True},
                        }  # Typo: missing 'i'
                    ]
                }
            },
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "missing_plugin"
        assert "Plugin 'json_auditng' not found" in error.message
        assert error.field_path == "plugins.auditing.json_auditng"
        assert len(error.suggestions) >= 1
        # Should suggest the correct plugin name
        assert any("audit_jsonl" in s for s in error.suggestions)
        assert error.can_ignore is True  # Missing plugins can be ignored

    def test_missing_plugin_available_list(self):
        """Test that available plugins are listed when no good fuzzy match exists."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            },
            "plugins": {
                "auditing": {
                    "_global": [{"handler": "nonexistent_plugin_xyz", "config": {"enabled": True}}]
                }
            },
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "missing_plugin"
        assert "Plugin 'nonexistent_plugin_xyz' not found" in error.message
        assert len(error.suggestions) >= 1
        # Should list available plugins
        assert any("Available auditing:" in s for s in error.suggestions)

    def test_missing_middleware_plugin_error(self):
        """Test missing middleware plugin handling at config load time."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            },
            "plugins": {
                "middleware": {
                    "_global": [
                        {"handler": "tool_managr", "config": {"enabled": True}}  # Typo: missing 'e'
                    ]
                }
            },
        }

        loader = ConfigLoader()
        # Config loading now validates middleware plugins and raises ConfigError
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "missing_plugin"
        assert "Plugin 'tool_managr' not found" in error.message
        assert error.field_path == "plugins.middleware.tool_managr"
        assert len(error.suggestions) >= 1
        # Should suggest the correct plugin name
        assert any("tool_manager" in s for s in error.suggestions)

    def test_available_plugins_list_truncation(self):
        """Test that very long available plugin lists are truncated."""
        # This test is more conceptual since we can't easily create 10+ plugins
        # But we can test that the logic works
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            },
            "plugins": {
                "auditing": {
                    "_global": [{"handler": "missing_plugin", "config": {"enabled": True}}]
                }
            },
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "missing_plugin"
        # Should have suggestions with available plugins listed
        available_suggestion = next(
            (s for s in error.suggestions if "Available auditing:" in s), None
        )
        assert available_suggestion is not None
        # Should not be excessively long (reasonable limit)
        assert len(available_suggestion) < 200  # Reasonable character limit


class TestSafeIgnoreFunctionality:
    """Test safe ignore functionality for missing plugins."""

    def test_load_with_plugin_ignore_success(self):
        """Test successfully loading config with missing plugin ignored."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            },
            "plugins": {
                "auditing": {
                    "_global": [
                        {"handler": "audit_jsonl", "config": {"enabled": True, "output_file": "logs/audit.jsonl"}},  # This exists
                        {
                            "handler": "missing_plugin",
                            "config": {"enabled": True},
                        },  # This doesn't exist
                    ]
                }
            },
        }

        # Create error for missing plugin
        error = ConfigError(
            message="Plugin 'missing_plugin' not found",
            error_type="missing_plugin",
            field_path="plugins.auditing.missing_plugin",
        )

        loader = ConfigLoader()
        # Should successfully load with the missing plugin removed
        config = loader.load_with_plugin_ignore(config_dict, error)

        assert isinstance(config, ProxyConfig)
        assert config.transport == "stdio"
        # Plugin should be removed from the config dict used for loading

    def test_load_with_plugin_ignore_non_plugin_error_fails(self):
        """Test that non-plugin errors cannot be ignored."""
        config_dict = {"proxy": {"transport": "stdio"}}

        # Create validation error (cannot be ignored)
        error = ConfigError(
            message="Missing required field",
            error_type="validation_error",
            field_path="upstreams",
        )

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_with_plugin_ignore(config_dict, error)

        new_error = exc_info.value
        assert "Cannot ignore validation_error errors" in new_error.message
        assert "only missing plugins can be safely ignored" in new_error.message

    def test_disable_plugin_entry_removes_correct_plugin(self):
        """Test that _disable_plugin_entry removes the correct plugin."""
        config_dict = {
            "plugins": {
                "auditing": {
                    "_global": [
                        {"handler": "audit_jsonl", "config": {"enabled": True, "output_file": "logs/audit.jsonl"}},
                        {"handler": "bad_plugin", "config": {"enabled": True}},
                        {"handler": "audit_csv", "config": {"enabled": True, "output_file": "logs/audit.csv"}},
                    ],
                    "server1": [{"handler": "bad_plugin", "config": {"enabled": True}}],
                }
            }
        }

        loader = ConfigLoader()
        modified_config = loader._disable_plugin_entry(
            config_dict, "plugins.auditing.bad_plugin"
        )

        # Should remove bad_plugin from all scopes
        global_plugins = modified_config["plugins"]["auditing"]["_global"]
        server1_plugins = modified_config["plugins"]["auditing"]["server1"]

        # Should have 2 plugins left in _global (json_auditing and csv_auditing)
        assert len(global_plugins) == 2
        assert all(p["handler"] != "bad_plugin" for p in global_plugins)

        # Should have 0 plugins left in server1
        assert len(server1_plugins) == 0

        # Should preserve good plugins
        policies = [p["handler"] for p in global_plugins]
        assert "audit_jsonl" in policies
        assert "audit_csv" in policies

    def test_disable_plugin_entry_handles_invalid_paths(self):
        """Test that _disable_plugin_entry handles invalid paths gracefully."""
        config_dict = {
            "plugins": {
                "auditing": {"_global": [{"handler": "audit_jsonl", "config": {"enabled": True, "output_file": "logs/audit.jsonl"}}]}
            }
        }

        loader = ConfigLoader()

        # Test various invalid field paths
        test_cases = [
            "invalid.path",
            "plugins.nonexistent.plugin",
            "not_plugins.auditing.plugin",
            "plugins",
            "plugins.auditing",
        ]

        for field_path in test_cases:
            # Should return original config unchanged for invalid paths
            result = loader._disable_plugin_entry(config_dict, field_path)
            assert result == config_dict

    def test_disable_plugin_entry_preserves_original_config(self):
        """Test that _disable_plugin_entry doesn't modify the original config dict."""
        original_config = {
            "plugins": {
                "auditing": {"_global": [{"handler": "bad_plugin", "config": {"enabled": True}}]}
            }
        }

        loader = ConfigLoader()
        # Pass a copy to preserve original
        import copy

        modified_config = loader._disable_plugin_entry(
            copy.deepcopy(original_config), "plugins.auditing.bad_plugin"
        )

        # Original should be unchanged
        assert len(original_config["plugins"]["auditing"]["_global"]) == 1
        assert (
            original_config["plugins"]["auditing"]["_global"][0]["handler"]
            == "bad_plugin"
        )

        # Modified should have plugin removed
        assert len(modified_config["plugins"]["auditing"]["_global"]) == 0


class TestConfigErrorQuickWins:
    """Test the QC-requested quick wins: to_dict(), __repr__, convenience methods."""

    def test_config_error_to_dict_minimal(self):
        """Test to_dict() with minimal ConfigError."""
        error = ConfigError(message="Test error", error_type="yaml_syntax")

        result = error.to_dict()

        # Should include all required fields
        assert result["message"] == "Test error"
        assert result["error_type"] == "yaml_syntax"
        assert result["error_code"] == "CFG_YAML_SYNTAX"
        assert result["can_edit"] is True
        assert result["can_ignore"] is False

        # Should not include None fields
        assert "file_path" not in result
        assert "line_number" not in result
        assert "field_path" not in result
        assert "line_snippet" not in result
        assert "suggestions" not in result

    def test_config_error_to_dict_complete(self):
        """Test to_dict() with complete ConfigError."""
        error = ConfigError(
            message="Plugin missing",
            error_type="missing_plugin",
            file_path=Path("/test/config.yaml"),
            line_number=42,
            field_path="plugins.auditing.bad_plugin",
            suggestions=["Did you mean 'good_plugin'?", "Available plugins: ..."],
            line_snippet="  handler: bad_plugin",
        )

        result = error.to_dict()

        # Should include all fields
        assert result["message"] == "Plugin missing"
        assert result["error_type"] == "missing_plugin"
        assert result["error_code"] == "CFG_MISSING_PLUGIN"
        assert result["can_edit"] is True
        assert result["can_ignore"] is True
        # Path separators vary by platform (forward slashes on Unix, backslashes on Windows)
        assert result["file_path"].endswith("config.yaml")
        assert "test" in result["file_path"]
        assert result["line_number"] == 42
        assert result["field_path"] == "plugins.auditing.bad_plugin"
        assert result["line_snippet"] == "  handler: bad_plugin"
        assert result["suggestions"] == [
            "Did you mean 'good_plugin'?",
            "Available plugins: ...",
        ]

    def test_config_error_repr(self):
        """Test __repr__ method for debug output."""
        error = ConfigError(
            message="Test error", error_type="yaml_syntax", field_path="proxy.transport"
        )

        repr_str = repr(error)
        assert "ConfigError" in repr_str
        assert "yaml_syntax" in repr_str
        assert "Test error" in repr_str
        assert "proxy.transport" in repr_str

    def test_config_error_repr_no_field_path(self):
        """Test __repr__ method when field_path is None."""
        error = ConfigError(message="Generic error", error_type="validation_error")

        repr_str = repr(error)
        assert "ConfigError" in repr_str
        assert "validation_error" in repr_str
        assert "Generic error" in repr_str
        assert "field_path=None" in repr_str

    def test_loader_stores_config_dict(self):
        """Test that ConfigLoader stores the last config dict."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            }
        }

        loader = ConfigLoader()

        # Initially no stored config
        assert loader._last_config_dict is None
        assert loader._last_config_directory is None

        # Load config
        config = loader.load_from_dict(config_dict)

        # Should store config dict (as a copy)
        assert loader._last_config_dict == config_dict
        assert loader._last_config_dict is not config_dict  # Should be a copy
        assert loader._last_config_directory is None
        assert isinstance(config, ProxyConfig)

    def test_loader_stores_config_directory(self):
        """Test that ConfigLoader stores config directory."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            }
        }

        config_dir = Path("/test/config")
        loader = ConfigLoader()

        config = loader.load_from_dict(config_dict, config_dir)

        assert loader._last_config_dict == config_dict
        assert loader._last_config_directory == config_dir
        assert isinstance(config, ProxyConfig)

    def test_retry_with_plugin_ignore_convenience_method(self):
        """Test the convenience retry_with_plugin_ignore method."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            },
            "plugins": {
                "auditing": {
                    "_global": [{"handler": "missing_plugin", "config": {"enabled": True}}]
                }
            },
        }

        loader = ConfigLoader()

        # First load to store config dict
        try:
            loader.load_from_dict(config_dict)
        except ConfigError as error:
            # Use convenience method to retry
            config = loader.retry_with_plugin_ignore(error)
            assert isinstance(config, ProxyConfig)
            assert config.transport == "stdio"

    def test_retry_with_plugin_ignore_no_stored_config_fails(self):
        """Test retry_with_plugin_ignore fails when no config stored."""
        loader = ConfigLoader()

        error = ConfigError(message="Test error", error_type="missing_plugin")

        with pytest.raises(ConfigError) as exc_info:
            loader.retry_with_plugin_ignore(error)

        retry_error = exc_info.value
        assert "No stored configuration available" in retry_error.message
        assert retry_error.error_type == "validation_error"


class TestPydanticValidationErrorHandling:
    """Test Pydantic validation error wrapping."""

    def test_missing_required_field_error(self):
        """Test that missing required fields are wrapped with suggestions."""
        config_dict = {
            "proxy": {
                "transport": "stdio"
                # Missing required 'upstreams' field
            }
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "validation_error"
        assert (
            "Missing required" in error.message or "required" in error.message.lower()
        )
        assert error.field_path == "upstreams"
        assert len(error.suggestions) >= 1
        assert any("Add required field" in s for s in error.suggestions)
        assert error.can_ignore is False  # Validation errors cannot be ignored

    def test_type_error_with_suggestions(self):
        """Test that type errors include helpful suggestions."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": 123,  # Should be string, not int
                        "command": ["echo", "hello"],
                    }
                ],
            }
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "validation_error"
        assert (
            "input should be" in error.message.lower()
            or "type" in error.message.lower()
        )
        assert "upstreams" in error.field_path
        assert len(error.suggestions) >= 1
        # Should suggest correct type or common fix
        suggestions_text = " ".join(error.suggestions).lower()
        assert "change" in suggestions_text or "type" in suggestions_text

    def test_numeric_value_quoted_suggestion(self):
        """Test that numeric values in quotes get specific suggestions."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test",
                        "command": ["echo", "hello"],
                        "max_restart_attempts": "not_a_number",  # Should be int, invalid string
                    }
                ],
            }
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "validation_error"
        assert "upstreams" in error.field_path
        assert len(error.suggestions) >= 1
        # Should suggest checking field value since it's invalid
        assert error.suggestions[0] == "Check field value and type"

    def test_value_error_generic_suggestion(self):
        """Test that value errors get generic but helpful suggestions."""
        config_dict = {
            "proxy": {
                "transport": "invalid_transport",  # Should be 'stdio' or 'http'
                "upstreams": [{"name": "test", "command": ["echo", "hello"]}],
            }
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "validation_error"
        assert "transport" in error.field_path
        assert len(error.suggestions) >= 1
        # Should have generic validation suggestion
        assert any(
            "valid" in s.lower() or "check" in s.lower() for s in error.suggestions
        )

    def test_first_error_only_processed(self):
        """Test that only the first validation error is processed."""
        config_dict = {
            "proxy": {
                "transport": "invalid_transport",  # Error 1
                "upstreams": [
                    {"name": "test", "command": "invalid_command"}  # Error 2
                ],
            }
        }

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_dict(config_dict)

        error = exc_info.value
        assert error.error_type == "validation_error"
        # Should only report the first error (transport)
        assert "transport" in error.field_path
        # Should not mention the command error
        assert "command" not in error.message.lower()
