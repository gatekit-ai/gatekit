"""Test suite for consolidated plugin configuration.

This test file implements Phase 1 of the plugin configuration consolidation.
All tests should FAIL initially (RED phase of TDD).
"""

import pytest
from gatekit.config.models import PluginConfig
from gatekit.config.loader import ConfigLoader


class TestPluginConfigConsolidation:
    """Test suite for consolidated plugin configuration."""

    def test_plugin_config_enabled_property_access(self):
        """enabled property reads from config dict."""
        config = PluginConfig(handler="test", config={"enabled": False})
        assert not config.enabled

    def test_plugin_config_enabled_property_setter(self):
        """enabled property writes to config dict."""
        config = PluginConfig(handler="test", config={})
        config.enabled = False
        assert not config.config["enabled"]

    def test_plugin_config_priority_property_access(self):
        """priority property reads from config dict."""
        config = PluginConfig(handler="test", config={"priority": 20})
        assert config.priority == 20

    def test_plugin_config_priority_property_setter(self):
        """priority property writes to config dict."""
        config = PluginConfig(handler="test", config={})
        config.priority = 30
        assert config.config["priority"] == 30

    def test_plugin_config_priority_validation_upper_bound(self):
        """priority property validates upper bound (> 100)."""
        config = PluginConfig(handler="test", config={})
        with pytest.raises(TypeError, match="Priority must be 0-100"):
            config.priority = 101

    def test_plugin_config_priority_validation_lower_bound(self):
        """priority property validates lower bound (< 0)."""
        config = PluginConfig(handler="test", config={})
        with pytest.raises(TypeError, match="Priority must be 0-100"):
            config.priority = -1

    def test_plugin_config_priority_validation_type(self):
        """priority property validates type."""
        config = PluginConfig(handler="test", config={})
        with pytest.raises(TypeError):
            config.priority = "50"  # String instead of int

    def test_plugin_config_defaults(self):
        """enabled and priority have sensible defaults."""
        config = PluginConfig(handler="test", config={})
        assert config.enabled
        assert config.priority == 50

    def test_yaml_round_trip_new_format(self, tmp_path):
        """Config can be saved and loaded in new format."""
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
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        loader = ConfigLoader()
        config = loader.load_from_file(config_file)
        plugin = config.plugins.security["_global"][0]

        assert plugin.enabled
        assert plugin.priority == 10
        assert plugin.config["action"] == "block"

    def test_config_dict_contains_enabled_and_priority(self):
        """Config dict should contain enabled and priority fields."""
        config = PluginConfig(handler="test", config={"enabled": False, "priority": 20})
        assert "enabled" in config.config
        assert "priority" in config.config
        assert not config.config["enabled"]
        assert config.config["priority"] == 20
