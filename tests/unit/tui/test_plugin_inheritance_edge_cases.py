"""Tests for plugin inheritance edge cases in ConfigEditorScreen."""

from pathlib import Path
from gatekit.tui.screens.config_editor import ConfigEditorScreen
from gatekit.config import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.config.models import PluginsConfig, PluginConfig


class TestPluginInheritanceEdgeCases:
    """Tests for edge cases in plugin inheritance logic."""

    def test_server_only_disabled_plugin(self):
        """Test that server-only disabled plugins show correct status."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # Add plugins configuration with a server-only disabled plugin
        config.plugins = PluginsConfig()
        config.plugins.security = {
            "server1": [PluginConfig(handler="test_security", config={"enabled": False})]
        }

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Check inheritance computation for server-only disabled
        status, enabled, priority = screen._compute_plugin_inheritance(
            "test_security", "security", "server1"
        )

        assert status == "server-only"
        assert enabled is False
        assert priority == 50  # Default priority

        # Check display formatting
        # Note: disabled plugins return empty string for display (shown differently in UI)
        display_status = screen._format_inheritance_status(status, enabled)
        assert display_status == ""

    def test_global_plugin_disabled_at_server(self):
        """Test that global plugins disabled at server level show 'disabled' status."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # Add plugins configuration with global and server override
        config.plugins = PluginsConfig()
        config.plugins.security = {
            "_global": [PluginConfig(handler="test_security", config={"enabled": True})],
            "server1": [
                PluginConfig(
                    handler="test_security",
                    config={"enabled": False},  # Disabled at server level
                )
            ],
        }

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Check inheritance computation
        status, enabled, priority = screen._compute_plugin_inheritance(
            "test_security", "security", "server1"
        )

        assert status == "disabled"
        assert enabled is False

        # Check display formatting
        # Note: disabled status returns "disabled" so "Use Global" button can detect it
        display_status = screen._format_inheritance_status(status, enabled)
        assert display_status == "disabled"

    def test_global_plugin_overridden_at_server(self):
        """Test that global plugins with config override show 'overrides' status."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # Add plugins configuration with global and server override
        config.plugins = PluginsConfig()
        config.plugins.middleware = {
            "_global": [
                PluginConfig(
                    handler="test_middleware",
                    config={"enabled": True, "priority": 10, "key1": "value1"},
                )
            ],
            "server1": [
                PluginConfig(
                    handler="test_middleware",
                    config={"enabled": True, "priority": 20, "key1": "value2", "key2": "new"},
                )
            ],
        }

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Check inheritance computation
        status, enabled, priority = screen._compute_plugin_inheritance(
            "test_middleware", "middleware", "server1"
        )

        assert status == "overrides"
        assert enabled is True
        assert priority == 20  # Server priority

        # Check display formatting
        display_status = screen._format_inheritance_status(status, enabled)
        assert display_status == "overrides (config)"

    def test_inherited_plugin_at_server(self):
        """Test that plugins inherited from global show 'inherited' status."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # Add plugins configuration with only global
        config.plugins = PluginsConfig()
        config.plugins.auditing = {
            "_global": [
                PluginConfig(
                    handler="test_auditing",
                    config={"enabled": True, "log_file": "test.log"},
                )
            ]
        }

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Check inheritance computation for server that inherits
        status, enabled, priority = screen._compute_plugin_inheritance(
            "test_auditing", "auditing", "server1"
        )

        assert status == "inherited"
        assert enabled is True

        # Check display formatting
        display_status = screen._format_inheritance_status(status, enabled)
        assert display_status == "inherited"

    def test_plugin_actions_for_disabled_server_only(self):
        """Test that disabled server-only plugins get correct actions."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # Add a disabled server-only plugin
        config.plugins = PluginsConfig()
        config.plugins.security = {
            "server1": [PluginConfig(handler="test_security", config={"enabled": False})]
        }

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "server1"

        from gatekit.tui.screens.config_editor import PluginActionContext

        # Create context for disabled server-only plugin
        ctx = PluginActionContext(
            handler="test_security",
            plugin_type="security",
            inheritance="server-only",
            enabled=False,
            server="server1",
        )

        # Get actions for this plugin
        actions = screen._get_plugin_actions(ctx)
        action_names = [name for name, _ in actions]

        # Should have Enable (not Disable), Reset, and Remove
        assert "Enable" in action_names
        assert "Disable" not in action_names
        assert "Configure" not in action_names  # Not available when disabled
        assert "Reset" in action_names  # Can reset server-only
        assert "Remove" in action_names  # Can remove server-specific

    def test_no_plugins_config_defaults(self):
        """Test behavior when plugins configuration is None."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
            ],
            timeouts=TimeoutConfig(),
        )

        # No plugins configuration
        config.plugins = None

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Check inheritance computation with no config
        status, enabled, priority = screen._compute_plugin_inheritance(
            "any_plugin", "security", "server1"
        )

        assert status == "server-only"
        assert enabled is False  # Default to disabled (consistent with unconfigured plugins)
        assert priority == 50  # Default priority
