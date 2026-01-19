"""Unit tests for plugin inheritance logic in ConfigEditorScreen."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from pathlib import Path
import asyncio
import tempfile
import os

from gatekit.tui.screens.config_editor import ConfigEditorScreen
from gatekit.plugins.manager import PluginManager
from gatekit.config.models import (
    ProxyConfig,
    PluginConfig,
    PluginsConfig,
    TimeoutConfig,
)


class TestPluginInheritance:
    """Test the _compute_plugin_inheritance method."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create a minimal config with required upstream
        from gatekit.config.models import UpstreamConfig

        self.config = ProxyConfig(
            upstreams=[UpstreamConfig(name="test-server", command=["echo", "test"])],
            plugins=PluginsConfig(security={}, middleware={}, auditing={}),
            transport="stdio",
            timeouts=TimeoutConfig(),
        )

        # Create screen instance with minimal setup
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            self.config_path = Path(f.name)

        # Create a mock screen object without invoking Textual's __init__
        self.screen = MagicMock(spec=ConfigEditorScreen)
        self.screen.config_file_path = self.config_path
        self.screen.config = self.config
        self.screen.plugin_manager = MagicMock()
        self.screen.available_handlers = {
            "security": {},
            "middleware": {},
            "auditing": {},
        }
        self.screen._save_lock = asyncio.Lock()
        self.screen._override_stash = {}
        self.screen.app = MagicMock()
        self.screen.server_identity_map = {}
        self.screen._identity_discovery_attempted = set()
        self.screen.server_tool_map = {}
        self.screen._tool_discovery_attempted = set()
        # Add the actual method we're testing
        self.screen._compute_plugin_inheritance = (
            ConfigEditorScreen._compute_plugin_inheritance.__get__(self.screen)
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        if self.config_path.exists():
            os.unlink(self.config_path)

    def test_global_only_plugin(self):
        """Test plugin that only exists at global scope."""
        # Add global plugin
        self.config.plugins.security["_global"] = [
            PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
        ]

        # Check at global scope
        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "test_plugin", "security", "_global"
        )
        assert status == "global"
        assert enabled
        assert priority == 10

        # Check at server scope (should be inherited)
        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "test_plugin", "security", "server1"
        )
        assert status == "inherited"
        assert enabled
        assert priority == 10

    def test_server_override_enabled(self):
        """Test server override of global plugin (enabled)."""
        # Add global plugin
        self.config.plugins.security["_global"] = [
            PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
        ]
        # Add server override
        self.config.plugins.security["server1"] = [
            PluginConfig(
                handler="test_plugin",
                config={"enabled": True, "priority": 20, "custom": "value"},
            )
        ]

        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "test_plugin", "security", "server1"
        )
        assert status == "overrides"
        assert enabled
        assert priority == 20

    def test_server_override_disabled(self):
        """Test server override that disables global plugin."""
        # Add global plugin
        self.config.plugins.security["_global"] = [
            PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
        ]
        # Add disable override
        self.config.plugins.security["server1"] = [
            PluginConfig(handler="test_plugin", config={"enabled": False, "priority": 10})
        ]

        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "test_plugin", "security", "server1"
        )
        assert status == "disabled"
        assert not enabled
        assert priority == 10

    def test_server_only_plugin(self):
        """Test plugin that only exists at server scope."""
        # Add server-only plugin
        self.config.plugins.security["server1"] = [
            PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 30})
        ]

        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "test_plugin", "security", "server1"
        )
        assert status == "server-only"
        assert enabled
        assert priority == 30

    def test_absent_plugin(self):
        """Test plugin that doesn't exist anywhere."""
        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "nonexistent", "security", "server1"
        )
        assert status == "server-only"  # Default for unconfigured
        assert not enabled  # Not configured = disabled
        assert priority == 50  # Default priority

    def test_disabled_server_only_plugin(self):
        """Test server-only plugin that is disabled."""
        # Add disabled server-only plugin
        self.config.plugins.security["server1"] = [
            PluginConfig(handler="test_plugin", config={"enabled": False, "priority": 30})
        ]

        status, enabled, priority = self.screen._compute_plugin_inheritance(
            "test_plugin", "security", "server1"
        )
        assert status == "server-only"
        assert not enabled
        assert priority == 30

    @pytest.mark.asyncio
    async def test_discover_identity_for_upstream_updates_map(self):
        """Identity discovery should record handshake names and refresh UI state."""

        from gatekit.config.models import UpstreamConfig

        upstream = UpstreamConfig(
            name="filesystem", command=["fake"], is_draft=False
        )
        upstream.server_identity = None

        self.screen.selected_server = "filesystem"
        self.screen._refresh_discovery_state = MagicMock()
        self.screen._render_server_plugin_groups = AsyncMock()
        self.screen._handshake_upstream = AsyncMock(
            return_value=(
                "secure-filesystem-server",
                {"tools": [], "status": "ok", "message": None},
            )
        )

        method = ConfigEditorScreen._discover_identity_for_upstream.__get__(
            self.screen
        )
        await method(upstream)

        assert (
            self.screen.server_identity_map["filesystem"]
            == "secure-filesystem-server"
        )
        assert "filesystem" in self.screen.server_tool_map
        tool_entry = self.screen.server_tool_map["filesystem"]
        assert tool_entry["status"] == "ok"
        self.screen._refresh_discovery_state.assert_called_once()
        self.screen._render_server_plugin_groups.assert_awaited()

    def test_contextual_handlers_respect_server_identity(self):
        """Server-specific handlers require MCP handshake identity to appear."""

        class GlobalPlugin:
            DISPLAY_SCOPE = "global"

        class FilesystemPlugin:
            DISPLAY_SCOPE = "server_specific"
            COMPATIBLE_SERVERS = ["secure-filesystem-server"]

        manager = PluginManager({})
        manager._handler_cache.clear()

        handler_map = {
            "global_plugin": GlobalPlugin,
            "filesystem_server": FilesystemPlugin,
        }

        with patch.object(manager, "_discover_handlers", return_value=handler_map):
            self.screen.plugin_manager = manager
            self.screen.available_handlers = {
                "security": handler_map,
                "middleware": {},
                "auditing": {},
            }

            self.screen.server_identity_map = {
                "test-server": "secure-filesystem-server"
            }

            self.screen._get_server_identity = (
                ConfigEditorScreen._get_server_identity.__get__(self.screen)
            )
            self.screen._get_contextual_handlers = (
                ConfigEditorScreen._get_contextual_handlers.__get__(self.screen)
            )

            handlers = self.screen._get_contextual_handlers("security", "test-server")
            assert "filesystem_server" in handlers

            # Without identity, server-specific handler should be filtered out
            self.screen.server_identity_map = {}
            handlers_no_identity = self.screen._get_contextual_handlers(
                "security", "test-server"
            )
            assert "filesystem_server" not in handlers_no_identity


class TestDisableEnableRoundtrip:
    """Test disable → enable roundtrip preserves config."""

    @pytest.mark.asyncio
    async def test_disable_enable_preserves_override(self):
        """Test that disabling then enabling an override preserves custom config."""
        # Setup
        from gatekit.config.models import UpstreamConfig

        config = ProxyConfig(
            upstreams=[UpstreamConfig(name="server1", command=["echo", "test"])],
            transport="stdio",
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(
                security={
                    "_global": [
                        PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
                    ],
                    "server1": [
                        PluginConfig(
                            handler="test_plugin",
                            config={"enabled": True, "priority": 20, "custom": "value", "foo": "bar"},
                        )
                    ],
                }
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, config)

            # Mock the app property
            mock_app = MagicMock()
            mock_app.notify = MagicMock()
            type(screen).app = PropertyMock(return_value=mock_app)

            screen.selected_server = "server1"
            screen.plugin_manager = AsyncMock()
            screen.available_handlers = {"security": {}}

            # Mock save to succeed and DOM queries
            with patch.object(screen, "_persist_config", return_value=True):
                with patch.object(
                    screen, "_rebuild_runtime_state", new_callable=AsyncMock
                ):
                    with patch.object(
                        screen, "_populate_server_plugins", new_callable=AsyncMock
                    ):
                        # Disable the plugin
                        await screen._handle_plugin_disable("test_plugin", "security")

                        # Check that config was stashed
                        stash_key = ("server1", "security", "test_plugin")
                        assert stash_key in screen._override_stash
                        stashed = screen._override_stash[stash_key]
                        # In new format, priority is in the config dict
                        assert stashed["config"]["custom"] == "value"
                        assert stashed["config"]["foo"] == "bar"
                        assert stashed["config"]["priority"] == 20

                        # Plugin should now be disabled
                        plugin = screen.config.plugins.security["server1"][0]
                        assert not plugin.enabled

                        # Re-enable the plugin
                        await screen._handle_plugin_enable("test_plugin", "security")

                        # Check that config was restored
                        plugin = screen.config.plugins.security["server1"][0]
                        assert plugin.enabled
                        assert plugin.config["custom"] == "value"
                        assert plugin.config["foo"] == "bar"
                        assert plugin.priority == 20

                        # Stash should be cleared
                        assert stash_key not in screen._override_stash

        finally:
            if config_path.exists():
                os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_disable_without_override_creates_disable(self):
        """Test that disabling a global plugin without override creates disable entry."""
        from gatekit.config.models import UpstreamConfig

        config = ProxyConfig(
            upstreams=[UpstreamConfig(name="server1", command=["echo", "test"])],
            transport="stdio",
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(
                security={
                    "_global": [
                        PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
                    ]
                }
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, config)

            # Mock the app property
            mock_app = MagicMock()
            mock_app.notify = MagicMock()
            type(screen).app = PropertyMock(return_value=mock_app)

            screen.selected_server = "server1"
            screen.plugin_manager = AsyncMock()
            screen.available_handlers = {"security": {}}

            with patch.object(screen, "_persist_config", return_value=True):
                with patch.object(
                    screen, "_rebuild_runtime_state", new_callable=AsyncMock
                ):
                    with patch.object(
                        screen, "_populate_server_plugins", new_callable=AsyncMock
                    ):
                        # Disable the plugin
                        await screen._handle_plugin_disable("test_plugin", "security")

                        # Should create disable override
                        assert "server1" in screen.config.plugins.security
                        plugins = screen.config.plugins.security["server1"]
                        assert len(plugins) == 1
                        assert plugins[0].handler == "test_plugin"
                        assert not plugins[0].enabled
                        assert plugins[0].priority == 10  # Copied from global

        finally:
            if config_path.exists():
                os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_enable_without_stash_removes_disable(self):
        """Test that enabling a disabled plugin without stash just removes the disable entry."""
        from gatekit.config.models import UpstreamConfig

        config = ProxyConfig(
            upstreams=[UpstreamConfig(name="server1", command=["echo", "test"])],
            transport="stdio",
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(
                security={
                    "_global": [
                        PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
                    ],
                    "server1": [
                        PluginConfig(handler="test_plugin", config={"enabled": False, "priority": 10})
                    ],
                }
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, config)

            # Mock the app property
            mock_app = MagicMock()
            mock_app.notify = MagicMock()
            type(screen).app = PropertyMock(return_value=mock_app)

            screen.selected_server = "server1"
            screen.plugin_manager = AsyncMock()
            screen.available_handlers = {"security": {}}

            # Ensure no stash exists for this plugin
            assert len(screen._override_stash) == 0

            with patch.object(screen, "_persist_config", return_value=True):
                with patch.object(
                    screen, "_rebuild_runtime_state", new_callable=AsyncMock
                ):
                    with patch.object(
                        screen, "_populate_server_plugins", new_callable=AsyncMock
                    ):
                        # Enable the plugin without any stashed config
                        await screen._handle_plugin_enable("test_plugin", "security")

                        # Should remove the disable override - check no test_plugin in server1 section
                        server_plugins = screen.config.plugins.security.get("server1", [])
                        assert not any(
                            p.handler == "test_plugin" for p in server_plugins
                        ), "test_plugin should be removed from server1 overrides after enable"

        finally:
            if config_path.exists():
                os.unlink(config_path)


class TestDuplicatePrevention:
    """Test that duplicate overrides are prevented."""

    @pytest.mark.asyncio
    async def test_multiple_disables_no_duplicates(self):
        """Test that multiple disable calls don't create duplicates."""
        from gatekit.config.models import UpstreamConfig

        config = ProxyConfig(
            upstreams=[UpstreamConfig(name="server1", command=["echo", "test"])],
            transport="stdio",
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(
                security={
                    "_global": [
                        PluginConfig(handler="test_plugin", config={"enabled": True, "priority": 10})
                    ]
                }
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, config)

            # Mock the app property
            mock_app = MagicMock()
            mock_app.notify = MagicMock()
            type(screen).app = PropertyMock(return_value=mock_app)

            screen.selected_server = "server1"
            screen.plugin_manager = AsyncMock()
            screen.available_handlers = {"security": {}}

            with patch.object(screen, "_persist_config", return_value=True):
                with patch.object(
                    screen, "_rebuild_runtime_state", new_callable=AsyncMock
                ):
                    with patch.object(
                        screen, "_populate_server_plugins", new_callable=AsyncMock
                    ):
                        # Disable multiple times
                        await screen._handle_plugin_disable("test_plugin", "security")
                        await screen._handle_plugin_disable("test_plugin", "security")
                        await screen._handle_plugin_disable("test_plugin", "security")

                        # Should still have only one override
                        plugins = screen.config.plugins.security.get("server1", [])
                        matching = [p for p in plugins if p.handler == "test_plugin"]
                        assert len(matching) == 1

        finally:
            if config_path.exists():
                os.unlink(config_path)


class TestConcurrencySafety:
    """Test concurrency safety with asyncio.Lock."""

    @pytest.mark.asyncio
    async def test_concurrent_saves_serialized(self):
        """Test that concurrent save operations are serialized."""
        from gatekit.config.models import UpstreamConfig

        config = ProxyConfig(
            upstreams=[UpstreamConfig(name="test-server", command=["echo", "test"])],
            transport="stdio",
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, config)

            # Mock the app property
            mock_app = MagicMock()
            type(screen).app = PropertyMock(return_value=mock_app)
            screen.plugin_manager = AsyncMock()

            # Track save order
            save_order = []

            async def mock_persist(id):
                save_order.append(f"start_{id}")
                await asyncio.sleep(0.01)  # Simulate I/O
                save_order.append(f"end_{id}")
                return True

            # Mock _load_config_from_disk to avoid actual file I/O
            with patch.object(screen, "_load_config_from_disk", return_value=config):
                with patch.object(
                    screen, "_rebuild_runtime_state", new_callable=AsyncMock
                ):
                    # Start multiple concurrent saves
                    tasks = []
                    for i in range(3):
                        with patch.object(
                            screen,
                            "_persist_config",
                            side_effect=lambda id=i: mock_persist(id),
                        ):
                            tasks.append(
                                asyncio.create_task(screen._save_and_rebuild())
                            )

                    await asyncio.gather(*tasks)

            # Verify saves were serialized (no interleaving)
            # Each save should complete before next starts
            for i in range(len(save_order) - 1):
                if save_order[i].startswith("start_"):
                    assert save_order[i + 1].startswith("end_")

        finally:
            if config_path.exists():
                os.unlink(config_path)


class TestSaveFailureRecovery:
    """Test save failure and recovery behavior."""

    @pytest.mark.asyncio
    async def test_save_failure_reverts_config(self):
        """Test that save failure reverts config and notifies user."""
        from gatekit.config.models import UpstreamConfig

        original_config = ProxyConfig(
            upstreams=[UpstreamConfig(name="test-server", command=["echo", "test"])],
            transport="stdio",
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(
                security={
                    "_global": [PluginConfig(handler="original", config={"enabled": True})]
                }
            ),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            # Patch Screen.__init__ to prevent Textual initialization
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, original_config)

            # Mock the app property
            mock_app = MagicMock()
            mock_app.notify = MagicMock()

            # Patch the app property using PropertyMock
            with patch.object(type(screen), "app", new_callable=PropertyMock, return_value=mock_app):
                screen.plugin_manager = AsyncMock()
                screen.available_handlers = {"security": {}}

                # Modify config
                screen.config.plugins.security["_global"][0].handler = "modified"

                # Mock save to fail
                with patch.object(screen, "_persist_config", return_value=False):
                    with patch.object(
                        screen, "_load_config_from_disk", return_value=original_config
                    ):
                        with patch.object(
                            screen, "_initialize_plugin_system", new_callable=AsyncMock
                        ):
                            with patch.object(
                                screen, "_rebuild_runtime_state", new_callable=AsyncMock
                            ):
                                result = await screen._save_and_rebuild()

                # Should return False
                assert not result

                # Should notify about revert
                mock_app.notify.assert_any_call(
                    "Configuration reverted to last saved state due to save failure",
                    severity="warning",
                )

                # Config should be reverted
                assert screen.config == original_config

        finally:
            if config_path.exists():
                os.unlink(config_path)
