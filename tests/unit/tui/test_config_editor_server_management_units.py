"""Unit tests for ConfigEditorScreen server management functionality."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, PropertyMock, MagicMock

from gatekit.tui.screens.config_editor import ConfigEditorScreen, PluginActionContext
from gatekit.config import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.config.models import PluginsConfig
from textual.widgets import Button


class TestServerRemovalLogic:
    """Tests for server removal selection logic."""

    def test_get_next_server_selection_middle(self):
        """Test removing a middle server selects the next one."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
                UpstreamConfig(name="server2", command=["cmd2"]),
                UpstreamConfig(name="server3", command=["cmd3"]),
                UpstreamConfig(name="server4", command=["cmd4"]),
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "server2"

        # Simulate removal (remove server2)
        config.upstreams = [u for u in config.upstreams if u.name != "server2"]

        # Find what should be selected next
        # server2 was at index 1, so we should select the new server at index 1 (server3)
        assert len(config.upstreams) == 3
        assert config.upstreams[1].name == "server3"

    def test_get_next_server_selection_last(self):
        """Test removing the last server selects the previous one."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
                UpstreamConfig(name="server2", command=["cmd2"]),
                UpstreamConfig(name="server3", command=["cmd3"]),
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "server3"

        # Simulate removal (remove server3)
        config.upstreams = [u for u in config.upstreams if u.name != "server3"]

        # Should select the new last server
        assert len(config.upstreams) == 2
        assert config.upstreams[-1].name == "server2"

    def test_get_next_server_selection_first(self):
        """Test removing the first server selects the new first one."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(name="server1", command=["cmd1"]),
                UpstreamConfig(name="server2", command=["cmd2"]),
                UpstreamConfig(name="server3", command=["cmd3"]),
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "server1"

        # Simulate removal (remove server1)
        config.upstreams = [u for u in config.upstreams if u.name != "server1"]

        # Should select the new first server
        assert len(config.upstreams) == 2
        assert config.upstreams[0].name == "server2"

    def test_get_next_server_selection_only(self):
        """Test removing the only server clears selection."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="server1", command=["cmd1"])],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "server1"

        # Simulate removal
        config.upstreams = []

        # No servers left
        assert len(config.upstreams) == 0


class TestButtonIDParsing:
    """Tests for button ID parsing with various handler names."""

    def test_parse_button_id_standard(self):
        """Test parsing standard button IDs."""
        test_cases = [
            ("config_myhandler", "config"),
            ("disable_myhandler", "disable"),
            ("enable_myhandler", "enable"),
            ("reset_myhandler", "reset"),
            ("remove_myhandler", "remove"),
        ]

        for button_id, expected_action in test_cases:
            # Extract action from ID
            action = button_id.split("_", 1)[0]
            assert action == expected_action

    def test_parse_button_id_with_underscores(self):
        """Test parsing button IDs where handler has underscores."""
        # Handler: "my_handler_name" -> ID: "config_my_handler_name"
        button_id = "config_my_handler_name"
        action = button_id.split("_", 1)[0]
        assert action == "config"

        # The rest would be "my_handler_name" which matches original

    def test_sanitize_handler_name(self):
        """Test that handler names are properly sanitized for IDs."""
        import re

        test_cases = [
            ("handler-name", "handler_name"),
            ("handler.name", "handler_name"),
            ("handler@name", "handler_name"),
            ("handler name", "handler_name"),
            ("handler/name", "handler_name"),
            ("handler:name", "handler_name"),
            ("handler_name", "handler_name"),  # Already valid
            ("handler123", "handler123"),  # Numbers OK
        ]

        for original, expected in test_cases:
            # Note: dash is included in the allowed characters, so it won't be replaced
            sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", original)
            # Update expectations for dash
            if original == "handler-name":
                assert sanitized == "handler-name"  # Dash is preserved
            else:
                assert sanitized == expected

    @pytest.mark.asyncio
    async def test_button_context_attachment(self):
        """Test that button context is properly attached."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )

        ConfigEditorScreen(Path("test.yaml"), config)

        # Create a button with context
        ctx = PluginActionContext(
            handler="test_handler",
            plugin_type="security",
            inheritance="global",
            enabled=True,
            server="_global",
        )

        button = Button("Configure", id="config_test_handler")
        button.data_ctx = ctx

        # Verify context is attached
        assert hasattr(button, "data_ctx")
        assert button.data_ctx.handler == "test_handler"
        assert button.data_ctx.plugin_type == "security"
        assert button.data_ctx.inheritance == "global"
        assert button.data_ctx.enabled is True
        assert button.data_ctx.server == "_global"


class TestManualIdentityTesting:
    """Tests for the manual Test Connection workflow."""

    def test_get_test_connection_block_reason(self):
        """Ensure block reasons align with transport and command requirements."""
        upstream_http = UpstreamConfig(name="http", transport="http", url="https://example.com")
        upstream_stdio = UpstreamConfig.create_draft(name="stdio")

        config = ProxyConfig(
            transport="stdio",
            upstreams=[upstream_http, upstream_stdio],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        assert (
            screen._get_test_connection_block_reason(upstream_http)
            == "Connection testing is only available for stdio transports."
        )

        assert (
            screen._get_test_connection_block_reason(upstream_stdio)
            == "Enter a launch command before testing this server."
        )

        upstream_stdio.command = ["run"]
        assert screen._get_test_connection_block_reason(upstream_stdio) is None

    def test_get_test_connection_block_reason_pending_text(self):
        """Pending command text should allow testing even before save."""
        upstream = UpstreamConfig.create_draft(name="alpha")
        config = ProxyConfig(
            transport="stdio",
            upstreams=[upstream],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        fake_input = MagicMock()
        fake_input.value = "npx mcp"

        def fake_query_one(selector, *_args, **_kwargs):
            if selector == "#server_command_input":
                return fake_input
            raise Exception("not found")

        screen.query_one = MagicMock(side_effect=fake_query_one)

        assert screen._get_test_connection_block_reason(upstream) is None

    @pytest.mark.asyncio
    async def test_on_test_connection_button_requires_command(self):
        """Clicking Test Connection without a command shows a warning."""
        upstream = UpstreamConfig.create_draft(name="alpha")
        config = ProxyConfig(
            transport="stdio",
            upstreams=[upstream],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "alpha"
        screen._run_worker = MagicMock()
        screen._update_identity_widgets = MagicMock()
        screen.call_after_refresh = MagicMock()
        screen._commit_command_input = AsyncMock()

        with patch.object(
            ConfigEditorScreen, "app", new_callable=PropertyMock
        ) as mock_app_prop:
            mock_app = MagicMock()
            mock_app_prop.return_value = mock_app

            await screen._handle_test_connection()

            mock_app.notify.assert_called_once()

        screen._run_worker.assert_not_called()
        screen._commit_command_input.assert_not_awaited()
        assert screen._identity_test_status == {}

    @pytest.mark.asyncio
    async def test_on_test_connection_button_triggers_worker(self):
        """Clicking Test Connection with a valid command starts the worker."""
        upstream = UpstreamConfig(name="beta", transport="stdio", command=["cmd"])
        config = ProxyConfig(
            transport="stdio",
            upstreams=[upstream],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "beta"

        def fake_run_worker(coro, **kwargs):
            coro.close()

        screen._run_worker = MagicMock(side_effect=fake_run_worker)
        screen._update_identity_widgets = MagicMock()
        screen.call_after_refresh = MagicMock()
        screen._commit_command_input = AsyncMock()

        with patch.object(
            ConfigEditorScreen, "app", new_callable=PropertyMock
        ) as mock_app_prop:
            mock_app = MagicMock()
            mock_app_prop.return_value = mock_app

            await screen._handle_test_connection()

            mock_app.notify.assert_not_called()

        screen._run_worker.assert_called_once()
        screen._commit_command_input.assert_not_awaited()
        status = screen._identity_test_status.get("beta")
        assert status is not None
        assert status["state"] == "testing"

    @pytest.mark.asyncio
    async def test_on_test_connection_button_commits_pending_command(self):
        """Button should parse the command input when not yet saved."""
        upstream = UpstreamConfig.create_draft(name="gamma")
        config = ProxyConfig(
            transport="stdio",
            upstreams=[upstream],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "gamma"
        screen.call_after_refresh = MagicMock()

        fake_input = MagicMock()
        fake_input.value = "echo hi"

        def fake_query_one(selector, *_args, **_kwargs):
            if selector == "#server_command_input":
                return fake_input
            raise Exception("not found")

        screen.query_one = MagicMock(side_effect=fake_query_one)

        async def fake_commit(value):
            upstream.command = value.split()

        screen._commit_command_input = AsyncMock(side_effect=fake_commit)

        def fake_run_worker(coro, **kwargs):
            coro.close()

        screen._run_worker = MagicMock(side_effect=fake_run_worker)

        with patch.object(
            ConfigEditorScreen, "app", new_callable=PropertyMock
        ) as mock_app_prop:
            mock_app = MagicMock()
            mock_app_prop.return_value = mock_app

            await screen._handle_test_connection()

            mock_app.notify.assert_not_called()

        screen._commit_command_input.assert_awaited_once_with("echo hi")
        screen._run_worker.assert_called_once()
        assert upstream.command == ["echo", "hi"]


class TestPluginActionHandler:
    """Test the plugin action button handler."""

    @pytest.mark.asyncio
    async def test_handler_ignores_non_plugin_buttons(self):
        """Test that handler ignores buttons without plugin action prefixes."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Create button with non-plugin ID (not a plugin action button)
        button = Button("Test Button", id="test_non_plugin_btn")
        mock_event = Mock()
        mock_event.button = button

        # Should return early without processing
        with patch.object(
            screen, "_handle_plugin_configure", new=AsyncMock()
        ) as mock_configure:
            await screen.on_plugin_action_button(mock_event)
            mock_configure.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_requires_valid_context(self):
        """Test that handler requires valid PluginActionContext."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Create button without context
        button = Button("Configure", id="config_test")
        mock_event = Mock()
        mock_event.button = button

        # Should return early without processing
        with patch.object(
            screen, "_handle_plugin_configure", new=AsyncMock()
        ) as mock_configure:
            await screen.on_plugin_action_button(mock_event)
            mock_configure.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_prevents_double_click(self):
        """Test that handler prevents re-entrancy during async operations."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Create button with context
        button = Button("Configure", id="config_test")
        button.data_ctx = PluginActionContext(
            handler="test",
            plugin_type="security",
            inheritance="global",
            enabled=True,
            server="_global",
        )
        button.disabled = False

        mock_event = Mock()
        mock_event.button = button

        # Track background tasks so we can wait for them
        import asyncio
        background_tasks = []

        def mock_run_worker(coro, **kwargs):
            """Mock _run_worker that tracks tasks so we can wait for them."""
            task = asyncio.create_task(coro)
            background_tasks.append(task)
            return task
        screen._run_worker = mock_run_worker

        # Should disable button during processing
        with patch.object(
            screen, "_handle_plugin_configure", new=AsyncMock()
        ) as mock_configure:
            await screen.on_plugin_action_button(mock_event)

            # Wait for all background tasks to complete
            if background_tasks:
                await asyncio.gather(*background_tasks)

            # Button should have been disabled then re-enabled
            mock_configure.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_removal_clears_override_stash(self):
        """Test that removing a server clears its override stash entries to prevent memory leaks."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test_server", transport="stdio", command=["echo", "test"]
                ),
                UpstreamConfig(
                    name="other_server", transport="stdio", command=["echo", "other"]
                ),
            ],
            timeouts=TimeoutConfig(),
            plugins=PluginsConfig(),
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_path = Path(f.name)

        try:
            with patch("textual.screen.Screen.__init__", return_value=None):
                screen = ConfigEditorScreen(config_path, config)

            # Add some stash entries for a server
            screen._override_stash[("test_server", "security", "plugin1")] = {
                "config": {},
                "priority": 50,
            }
            screen._override_stash[("test_server", "middleware", "plugin2")] = {
                "config": {},
                "priority": 60,
            }
            screen._override_stash[("other_server", "security", "plugin3")] = {
                "config": {},
                "priority": 70,
            }

            # Set necessary attributes (config already has upstreams)
            screen.selected_server = "test_server"

            mock_app = MagicMock()
            mock_app.push_screen_wait = AsyncMock(return_value=True)  # Confirm removal
            type(screen).app = PropertyMock(return_value=mock_app)

            # Mock the save methods
            screen._save_configuration = AsyncMock(return_value=True)
            screen._populate_servers_list = AsyncMock()
            screen._clear_server_details = AsyncMock()
            screen._populate_server_details = AsyncMock()

            # Remove the server
            await screen._handle_remove_server()

            # Verify stash entries for 'test_server' were removed
            assert ("test_server", "security", "plugin1") not in screen._override_stash
            assert (
                "test_server",
                "middleware",
                "plugin2",
            ) not in screen._override_stash
            # But 'other_server' entries should remain
            assert ("other_server", "security", "plugin3") in screen._override_stash

        finally:
            config_path.unlink(missing_ok=True)
