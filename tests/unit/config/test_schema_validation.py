"""Tests for strict plugin schema validation."""

import pytest
from gatekit.config.loader import ConfigLoader
from gatekit.config.errors import ConfigError


class TestPluginSchemaValidation:
    """Test that unknown plugin config options are rejected."""

    def test_unknown_option_rejected(self, tmp_path):
        """Unknown options should raise ConfigError."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  auditing:
    _global:
      - handler: audit_jsonl
        config:
          enabled: true
          output_file: /tmp/test.jsonl
          unknown_option: true
""")

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_file(config_file)

        assert "unknown_option" in str(exc_info.value.message).lower() or \
               "additional properties" in str(exc_info.value.message).lower()

    def test_valid_config_passes(self, tmp_path):
        """Valid configs should load without error."""
        # Use tmp_path for output file to avoid world-writable directory check
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "test.jsonl"

        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  auditing:
    _global:
      - handler: audit_jsonl
        config:
          enabled: true
          output_file: {log_file}
          include_request_body: true
""")

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        assert config is not None

    def test_plugin_without_schema_skipped(self, tmp_path):
        """Plugins without schemas should be skipped, not rejected."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  security:
    _global:
      - handler: nonexistent_custom_plugin
        config:
          enabled: true
          any_field: "should not trigger schema error"
          another_field: 123
""")

        loader = ConfigLoader()
        # Should NOT raise "No schema found" - schema validation skips unknown handlers
        # It WILL raise a handler discovery error later, which is expected
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_file(config_file)

        # Verify the error is about handler not found, NOT about schema validation
        error_msg = str(exc_info.value.message).lower()
        assert "no schema found" not in error_msg, \
            "Schema validation should skip plugins without schemas"
        assert "handler" in error_msg or "plugin" in error_msg or "not found" in error_msg, \
            "Error should be about handler discovery, not schema validation"

    def test_error_includes_valid_fields_suggestion(self, tmp_path):
        """Error message should suggest valid fields."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  auditing:
    _global:
      - handler: audit_jsonl
        config:
          enabled: true
          output_file: /tmp/test.jsonl
          bad_field: true
""")

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_file(config_file)

        # Should have suggestion with valid fields
        assert any("valid fields" in s.lower() for s in exc_info.value.suggestions)

    def test_critical_field_accepted(self, tmp_path):
        """The critical field should be accepted in plugin config."""
        # Use tmp_path for output file to avoid world-writable directory check
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "test.jsonl"

        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  auditing:
    _global:
      - handler: audit_jsonl
        config:
          enabled: true
          critical: false
          output_file: {log_file}
""")

        loader = ConfigLoader()
        # Should NOT raise an error - critical is a valid framework field
        config = loader.load_from_file(config_file)
        assert config is not None

    def test_non_critical_plugin_schema_error_skipped(self, tmp_path, caplog):
        """Non-critical plugins with schema errors should be skipped, not fatal."""
        import logging

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  auditing:
    _global:
      - handler: audit_jsonl
        config:
          enabled: true
          critical: false
          output_file: /tmp/test.jsonl
          unknown_option: "should trigger schema error"
""")

        loader = ConfigLoader()
        with caplog.at_level(logging.WARNING):
            # Should NOT raise ConfigError - plugin is non-critical
            config = loader.load_from_file(config_file)

        # Config should load successfully
        assert config is not None

        # Plugin should be skipped (removed from config)
        assert len(config.plugins.auditing["_global"]) == 0

        # Warning should have been logged
        assert any("non-critical" in record.message.lower() and
                   "schema validation" in record.message.lower()
                   for record in caplog.records)

    def test_critical_true_plugin_schema_error_fatal(self, tmp_path):
        """Critical plugins (default) with schema errors should fail startup."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test
      transport: stdio
      command: ["echo", "test"]
plugins:
  auditing:
    _global:
      - handler: audit_jsonl
        config:
          enabled: true
          critical: true
          output_file: /tmp/test.jsonl
          unknown_option: "should trigger fatal error"
""")

        loader = ConfigLoader()
        with pytest.raises(ConfigError) as exc_info:
            loader.load_from_file(config_file)

        # Error should mention the unknown option
        assert "unknown_option" in str(exc_info.value.message).lower() or \
               "additional properties" in str(exc_info.value.message).lower()
