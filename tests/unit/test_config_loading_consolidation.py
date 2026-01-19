"""Test config loader handles new consolidated format.

This test file implements Phase 1 of the plugin configuration consolidation for config loading.
All tests should FAIL initially (RED phase of TDD).
"""

import pytest
from pydantic import ValidationError
from gatekit.config.loader import ConfigLoader
from gatekit.config.errors import ConfigError
from gatekit.config.models import PluginConfig


class TestConfigLoadingConsolidation:
    """Test config loader handles new consolidated format."""

    def test_load_new_format_directly(self, tmp_path):
        """New format loads with enabled/priority in config dict."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        config:
          enabled: true
          priority: 50
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugin = config.plugins.security["_global"][0]

        # Fields should be in config dict
        assert plugin.config["enabled"]
        assert plugin.config["priority"] == 50
        assert plugin.config["action"] == "block"

    def test_load_new_format_with_disabled_plugin(self, tmp_path):
        """New format correctly loads disabled plugins."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        config:
          enabled: false
          priority: 20
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugin = config.plugins.security["_global"][0]

        assert not plugin.config["enabled"]
        assert plugin.config["priority"] == 20

    def test_load_new_format_multiple_plugins(self, tmp_path):
        """New format loads multiple plugins correctly."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        config:
          enabled: true
          priority: 10
          action: block
      - handler: basic_pii_filter
        config:
          enabled: false
          priority: 20
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugins = config.plugins.security["_global"]

        assert len(plugins) == 2
        assert plugins[0].config["enabled"]
        assert plugins[0].config["priority"] == 10
        assert not plugins[1].config["enabled"]
        assert plugins[1].config["priority"] == 20

    def test_plugin_manager_instantiation(self):
        """PluginManager receives config with enabled/priority."""
        plugin_config = PluginConfig(
            handler="basic_secrets_filter",
            config={"enabled": True, "priority": 30, "action": "block"}
        )

        # Plugin receives full config
        # The plugin __init__ should receive config with enabled/priority
        # Base class extracts priority: self.priority = config.get("priority", 50)
        assert plugin_config.config["enabled"]
        assert plugin_config.config["priority"] == 30
        assert plugin_config.enabled
        assert plugin_config.priority == 30

    def test_old_format_not_supported(self, tmp_path):
        """Old format with top-level enabled/priority is not supported."""
        # This test intentionally uses the OLD format to verify it's rejected
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        enabled: false
        priority: 20
        config:
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        # This should fail validation or raise an error
        with pytest.raises((ValidationError, ValueError, TypeError, ConfigError)):
            loader = ConfigLoader()
            loader.load_from_file(config_file)

    def test_config_with_only_handler_field(self, tmp_path):
        """Config with only handler field (no config dict) should fail or use defaults."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugin = config.plugins.security["_global"][0]

        # Should use defaults from properties
        assert plugin.enabled
        assert plugin.priority == 50

    def test_config_partial_framework_fields(self, tmp_path):
        """Config with only some framework fields uses defaults for others."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        config:
          enabled: false
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugin = config.plugins.security["_global"][0]

        assert not plugin.enabled
        assert plugin.priority == 50  # Default
        assert plugin.config["action"] == "block"

    def test_config_invalid_priority_value(self, tmp_path):
        """Config with invalid priority value should fail validation during loading."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        config:
          enabled: true
          priority: 150
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        # Priority validation now happens during config loading
        with pytest.raises(ConfigError, match="priority must be an integer between 0 and 100"):
            loader.load_from_file(config_file)

    def test_config_round_trip(self, tmp_path):
        """Config can be loaded, modified, and maintains consistency."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: test_server
      command: ["python", "-m", "test"]

plugins:
  security:
    _global:
      - handler: basic_secrets_filter
        config:
          enabled: true
          priority: 30
          action: block
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugin = config.plugins.security["_global"][0]

        # Modify via properties
        plugin.enabled = False
        plugin.priority = 40

        # Config dict should reflect changes
        assert not plugin.config["enabled"]
        assert plugin.config["priority"] == 40
        assert plugin.config["action"] == "block"
