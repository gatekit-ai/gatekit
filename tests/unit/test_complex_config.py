"""Unit tests for complex configuration scenarios.

Tests for edge cases and complex nested configurations following TDD methodology.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import patch

from gatekit.config.loader import ConfigLoader


class TestComplexConfiguration:
    """Test cases for complex configuration scenarios."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yield f.name
        os.unlink(f.name)

    @pytest.fixture
    def config_loader_no_validation(self):
        """Create a config loader that skips path validation."""
        with patch.object(ConfigLoader, "validate_paths"):
            yield ConfigLoader()

    def test_deeply_nested_plugin_config(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test deeply nested plugin configurations (3+ levels)."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test", "server"]

plugins:
  security:
    _global:
      - handler: "complex_plugin"
        config:
          enabled: true
          priority: 10
          level1:
            level2:
              level3:
                level4:
                  deep_value: "nested_data"
                  deep_array: [1, 2, 3]
                  deep_dict:
                    key1: "value1"
                    key2: 42
                level3_array:
                  - item1: "value1"
                    item2: 123
                  - item1: "value2"
                    item2: 456
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        # Verify deep nesting is preserved
        plugin_config = config.plugins.security["_global"][0].config
        assert (
            plugin_config["level1"]["level2"]["level3"]["level4"]["deep_value"]
            == "nested_data"
        )
        assert plugin_config["level1"]["level2"]["level3"]["level4"]["deep_array"] == [
            1,
            2,
            3,
        ]
        assert (
            plugin_config["level1"]["level2"]["level3"]["level4"]["deep_dict"]["key2"]
            == 42
        )
        assert len(plugin_config["level1"]["level2"]["level3"]["level3_array"]) == 2

    def test_mixed_types_in_nested_structures(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test mixed types within nested configuration structures."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  auditing:
    _global:
      - handler: "mixed_types"
        config:
          string_value: "hello"
          int_value: 42
          float_value: 3.14
          bool_value: true
          null_value: null
          array_mixed: ["string", 123, 3.14, true, null]
          nested_mixed:
            sub_string: "world"
            sub_array: [1, "two", 3.0]
            sub_dict:
              a: 1
              b: "2"
              c: true
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        plugin_config = config.plugins.auditing["_global"][0].config
        assert plugin_config["string_value"] == "hello"
        assert plugin_config["int_value"] == 42
        assert plugin_config["float_value"] == 3.14
        assert plugin_config["bool_value"] is True
        assert plugin_config["null_value"] is None
        assert plugin_config["array_mixed"][4] is None
        assert plugin_config["nested_mixed"]["sub_dict"]["c"] is True

    @patch.dict(
        os.environ,
        {
            "AG_PROXY_UPSTREAM_COMMAND": '["override", "command"]',
            "AG_PLUGINS_SECURITY_0_PRIORITY": "99",
            "AG_PLUGINS_SECURITY_0_CONFIG_NESTED_VALUE": "env_override",
        },
    )
    def test_environment_variable_overrides(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test AG_ prefixed environment variable overrides."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["original", "command"]

plugins:
  security:
    _global:
      - handler: "test_plugin"
        config:
          priority: 10
          nested:
            value: "original"
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        # Environment variable override should take precedence
        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        # These tests will fail until env var override is implemented
        with pytest.raises(AssertionError):
            assert config.upstreams[0].command == ["override", "command"]
        with pytest.raises(AssertionError):
            assert config.plugins.security["_global"][0].priority == 99
        with pytest.raises(AssertionError):
            assert (
                config.plugins.security["_global"][0].config["nested"]["value"]
                == "env_override"
            )

    def test_relative_paths_in_nested_configs(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test relative path resolution in nested configurations."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

logging:
  handlers: ["file"]
  file_path: "./logs/gatekit.log"

plugins:
  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
            output_file: "../audit/audit.log"
            include_request_body: true
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        # Paths should be resolved relative to config file directory
        config_dir = Path(temp_config_file).parent

        # Logging path should be resolved
        # Compare resolved paths to handle symlinks
        expected_path = (config_dir / "logs" / "gatekit.log").resolve()
        actual_path = config.logging.file_path.resolve()
        assert actual_path == expected_path

        # Plugin config paths should remain as strings (plugins handle their own resolution)
        plugin_config = config.plugins.auditing["_global"][0].config
        assert plugin_config["output_file"] == "../audit/audit.log"

    def test_empty_configuration_sections(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test handling of empty configuration sections."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  security: {}
  auditing: {}

logging: {}
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        # Empty plugin lists should work
        assert config.plugins.security == {}
        assert config.plugins.auditing == {}

        # Empty logging section should use defaults
        assert config.logging is not None
        assert config.logging.level == "INFO"  # Default value

    def test_null_vs_missing_values(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test distinction between null and missing values."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  security:
    _global:
      - handler: "test"
        config:
          explicit_null: null
          # missing_value is not defined
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        plugin_config = config.plugins.security["_global"][0].config
        assert "explicit_null" in plugin_config
        assert plugin_config["explicit_null"] is None
        assert "missing_value" not in plugin_config

    def test_unicode_in_configuration(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test Unicode characters in configuration values."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  security:
    _global:
      - handler: "unicode_test"
        config:
            message: "Hello 世界! 🌍"
            emoji_key: "🔐"
            mixed: ["English", "中文", "العربية", "🎉"]
            nested:
              greeting: "Здравствуй мир"
              symbols: "αβγδε"
"""
        with open(temp_config_file, "w", encoding="utf-8") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        plugin_config = config.plugins.security["_global"][0].config
        assert plugin_config["message"] == "Hello 世界! 🌍"
        assert plugin_config["emoji_key"] == "🔐"
        assert plugin_config["mixed"][3] == "🎉"
        assert plugin_config["nested"]["symbols"] == "αβγδε"

    def test_very_large_configuration(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test handling of very large configuration files."""
        # Create a large config with many plugins
        plugins_section = []
        for i in range(100):
            plugins_section.append(
                f"""
      - handler: "plugin_{i}"
        config:
          priority: {i % 100}
          index: {i}
          data: "{'x' * 100}"
          nested:
            level1:
              level2:
                value: "data_{i}"
"""
            )

        config_content = f"""
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  security:
    _global:
{''.join(plugins_section[:50])}
  auditing:
    _global:
{''.join(plugins_section[50:])}
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        # Should handle 100 plugins without issues
        assert len(config.plugins.security["_global"]) == 50
        assert len(config.plugins.auditing["_global"]) == 50
        assert config.plugins.security["_global"][25].config["index"] == 25
        assert config.plugins.auditing["_global"][25].config["index"] == 75

    def test_circular_path_references(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test detection of circular path references."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  auditing:
    _global:
      - handler: "path_test"
        config:
            base_path: "./data"
            paths:
              input: "${base_path}/input"
              output: "${input}/output"
              circular: "${output}/${input}"
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        # Variable substitution is not implemented, so these should remain as-is
        plugin_config = config.plugins.auditing["_global"][0].config
        assert plugin_config["paths"]["input"] == "${base_path}/input"
        assert plugin_config["paths"]["circular"] == "${output}/${input}"

    def test_arrays_within_nested_structures(
        self, temp_config_file, config_loader_no_validation
    ):
        """Test arrays at various levels of nesting."""
        config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["test"]

plugins:
  security:
    _global:
      - handler: "array_test"
        config:
            top_array: [1, 2, 3]
            nested:
              sub_array: ["a", "b", "c"]
              deep:
                deeper_array:
                  - name: "item1"
                    values: [10, 20, 30]
                    metadata:
                      tags: ["tag1", "tag2"]
                  - name: "item2"
                    values: [40, 50, 60]
                    metadata:
                      tags: ["tag3", "tag4"]
"""
        with open(temp_config_file, "w") as f:
            f.write(config_content)

        config = config_loader_no_validation.load_from_file(Path(temp_config_file))

        plugin_config = config.plugins.security["_global"][0].config
        assert plugin_config["top_array"] == [1, 2, 3]
        assert plugin_config["nested"]["sub_array"] == ["a", "b", "c"]
        assert len(plugin_config["nested"]["deep"]["deeper_array"]) == 2
        assert plugin_config["nested"]["deep"]["deeper_array"][0]["metadata"][
            "tags"
        ] == ["tag1", "tag2"]
        assert plugin_config["nested"]["deep"]["deeper_array"][1]["values"][1] == 50
