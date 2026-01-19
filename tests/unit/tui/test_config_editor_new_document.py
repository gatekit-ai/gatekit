"""Tests for Create New (blank configuration) functionality in ConfigEditorScreen.

This tests the TUI workflow where a user creates a new configuration from scratch
without an existing file. The configuration is held in memory until the first save.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig


class TestProxyConfigCreateEmptyForEditing:
    """Tests for ProxyConfig.create_empty_for_editing() factory method."""

    def test_create_empty_for_editing_returns_proxy_config(self):
        """Factory method returns a ProxyConfig instance."""
        config = ProxyConfig.create_empty_for_editing()
        assert isinstance(config, ProxyConfig)

    def test_create_empty_for_editing_has_empty_upstreams(self):
        """Empty config has no upstreams."""
        config = ProxyConfig.create_empty_for_editing()
        assert config.upstreams == []

    def test_create_empty_for_editing_has_default_transport(self):
        """Empty config has stdio transport by default."""
        config = ProxyConfig.create_empty_for_editing()
        assert config.transport == "stdio"

    def test_create_empty_for_editing_has_default_timeouts(self):
        """Empty config has default timeout configuration."""
        config = ProxyConfig.create_empty_for_editing()
        assert config.timeouts is not None
        assert isinstance(config.timeouts, TimeoutConfig)

    def test_create_empty_for_editing_bypasses_validation(self):
        """Factory method doesn't raise despite empty upstreams (bypasses __post_init__)."""
        # Normal constructor would raise due to empty upstreams
        # The factory bypasses validation
        config = ProxyConfig.create_empty_for_editing()
        # If we got here without exception, validation was bypassed
        assert config.upstreams == []

    def test_create_empty_for_editing_optional_fields_are_none(self):
        """Empty config has None for optional configuration sections."""
        config = ProxyConfig.create_empty_for_editing()
        assert config.http is None
        assert config.plugins is None
        assert config.logging is None


class TestConfigEditorScreenNewDocument:
    """Tests for ConfigEditorScreen handling of new documents (no file path)."""

    def test_is_new_document_true_when_path_is_none(self):
        """is_new_document returns True when config_file_path is None."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )
        assert screen.is_new_document is True

    def test_is_new_document_false_when_path_exists(self):
        """is_new_document returns False when config_file_path is set."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=Path("/tmp/test.yaml"),
            loaded_config=empty_config,
        )
        assert screen.is_new_document is False

    def test_new_document_starts_dirty(self):
        """New document starts with _config_dirty=True."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )
        assert screen._config_dirty is True

    def test_new_document_has_empty_hash(self):
        """New document has empty _last_saved_config_hash."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )
        assert screen._last_saved_config_hash == ""

    def test_existing_document_starts_clean(self):
        """Existing document starts with _config_dirty=False."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        # Create a valid config with at least one upstream
        config = ProxyConfig.create_empty_for_editing()
        config.upstreams = [
            UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["echo", "test"],
            )
        ]

        screen = ConfigEditorScreen(
            config_file_path=Path("/tmp/test.yaml"),
            loaded_config=config,
        )
        assert screen._config_dirty is False


class TestConfigEditorScreenHeaderDisplay:
    """Tests for header display with new documents."""

    def test_update_header_shows_new_configuration_for_new_document(self):
        """Header shows '[New Configuration]' for new documents."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )
        # Call _update_header directly
        screen._update_header()

        assert "[New Configuration]" in screen.sub_title

    def test_update_header_shows_dirty_indicator_for_new_document(self):
        """Header shows dirty indicator (*) for new documents."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )
        screen._update_header()

        assert "*" in screen.sub_title

    def test_update_header_shows_filename_for_existing_document(self):
        """Header shows filename for existing documents."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        config = ProxyConfig.create_empty_for_editing()
        config.upstreams = [
            UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["echo", "test"],
            )
        ]

        screen = ConfigEditorScreen(
            config_file_path=Path("/tmp/my-config.yaml"),
            loaded_config=config,
        )
        screen._update_header()

        assert "my-config.yaml" in screen.sub_title


class TestValidateCanSave:
    """Tests for _validate_can_save() validation helper."""

    @pytest.fixture
    def mock_screen(self):
        """Create a mock screen with minimal dependencies."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )
        # Mock the app property using patch.object
        mock_app = MagicMock()
        mock_app.notify = MagicMock()
        with patch.object(type(screen), "app", property(lambda self: mock_app)):
            screen._mock_app = mock_app  # Store reference for assertions
            yield screen

    def test_validate_can_save_blocks_empty_upstreams(self, mock_screen):
        """Save is blocked when upstreams list is empty."""
        mock_screen.config.upstreams = []

        with patch.object(type(mock_screen), "app", property(lambda self: mock_screen._mock_app)):
            result = mock_screen._validate_can_save()

            assert result is False
            mock_screen._mock_app.notify.assert_called_once()
            call_args = mock_screen._mock_app.notify.call_args
            assert "At least one MCP server" in call_args[0][0]
            assert call_args[1]["severity"] == "warning"

    def test_validate_can_save_blocks_only_draft_servers(self, mock_screen):
        """Save is blocked when only draft servers exist."""
        mock_screen.config.upstreams = [
            UpstreamConfig.create_draft("draft-server"),
        ]

        with patch.object(type(mock_screen), "app", property(lambda self: mock_screen._mock_app)):
            result = mock_screen._validate_can_save()

            assert result is False
            mock_screen._mock_app.notify.assert_called_once()
            call_args = mock_screen._mock_app.notify.call_args
            assert "fully configured" in call_args[0][0]
            assert call_args[1]["severity"] == "warning"

    def test_validate_can_save_allows_complete_server(self, mock_screen):
        """Save is allowed when at least one complete server exists."""
        mock_screen.config.upstreams = [
            UpstreamConfig(
                name="complete-server",
                transport="stdio",
                command=["echo", "test"],
            )
        ]

        with patch.object(type(mock_screen), "app", property(lambda self: mock_screen._mock_app)):
            result = mock_screen._validate_can_save()

            assert result is True
            mock_screen._mock_app.notify.assert_not_called()

    def test_validate_can_save_allows_mix_of_draft_and_complete(self, mock_screen):
        """Save is allowed when there's a mix of draft and complete servers."""
        mock_screen.config.upstreams = [
            UpstreamConfig.create_draft("draft-server"),
            UpstreamConfig(
                name="complete-server",
                transport="stdio",
                command=["echo", "test"],
            ),
        ]

        with patch.object(type(mock_screen), "app", property(lambda self: mock_screen._mock_app)):
            result = mock_screen._validate_can_save()

            assert result is True
            mock_screen._mock_app.notify.assert_not_called()


class TestSaveLogicNewDocument:
    """Tests for save behavior with new documents."""

    @pytest.fixture
    def mock_screen_with_server(self):
        """Create a mock screen with a valid server configured."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        config = ProxyConfig.create_empty_for_editing()
        config.upstreams = [
            UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["echo", "test"],
            )
        ]

        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=config,
        )
        # Create mock app
        mock_app = MagicMock()
        mock_app.notify = MagicMock()
        mock_app.push_screen_wait = AsyncMock()
        screen._mock_app = mock_app
        return screen

    @pytest.mark.asyncio
    async def test_save_triggers_save_as_for_new_document(self, mock_screen_with_server):
        """Ctrl+S on new document triggers Save As flow."""
        # Mock _save_config_as_with_modal to track if it's called
        mock_screen_with_server._save_config_as_with_modal = AsyncMock()

        with patch.object(type(mock_screen_with_server), "app", property(lambda self: mock_screen_with_server._mock_app)):
            await mock_screen_with_server._save_config_with_notification()

        # Should have triggered Save As for new document
        mock_screen_with_server._save_config_as_with_modal.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_as_validates_before_modal(self, mock_screen_with_server):
        """Save As validates config before showing FileSave modal."""
        # Make config invalid (empty upstreams)
        mock_screen_with_server.config.upstreams = []

        with patch.object(type(mock_screen_with_server), "app", property(lambda self: mock_screen_with_server._mock_app)):
            await mock_screen_with_server._save_config_as_with_modal()

        # Should show warning and NOT show FileSave modal
        mock_screen_with_server._mock_app.notify.assert_called_once()
        mock_screen_with_server._mock_app.push_screen_wait.assert_not_called()


class TestSaveAsNewDocument:
    """Tests for Save As flow with new documents."""

    @pytest.fixture
    def mock_screen_with_server(self):
        """Create a mock screen with a valid server configured."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        config = ProxyConfig.create_empty_for_editing()
        config.upstreams = [
            UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["echo", "test"],
            )
        ]

        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=config,
        )
        # Create mock app
        mock_app = MagicMock()
        mock_app.notify = MagicMock()
        mock_app.push_screen_wait = AsyncMock()
        mock_app.config_path = None
        mock_app.config_exists = False
        screen._mock_app = mock_app
        screen._save_and_rebuild = AsyncMock(return_value=True)
        screen._mark_clean = MagicMock()
        screen._update_header = MagicMock()
        return screen

    @pytest.mark.asyncio
    async def test_save_as_updates_config_path_after_save(self, mock_screen_with_server):
        """After successful save, config_file_path is set."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            new_path = Path(f.name)

        mock_screen_with_server._mock_app.push_screen_wait.return_value = new_path

        with patch.object(type(mock_screen_with_server), "app", property(lambda self: mock_screen_with_server._mock_app)):
            with patch("gatekit.tui.recent_files.RecentFiles"):  # Don't pollute recent files
                await mock_screen_with_server._save_config_as_with_modal()

        assert mock_screen_with_server.config_file_path == new_path
        assert mock_screen_with_server.is_new_document is False

    @pytest.mark.asyncio
    async def test_save_as_updates_app_state_for_new_document(self, mock_screen_with_server):
        """After first save, app.config_path and app.config_exists are updated."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            new_path = Path(f.name)

        mock_screen_with_server._mock_app.push_screen_wait.return_value = new_path

        with patch.object(type(mock_screen_with_server), "app", property(lambda self: mock_screen_with_server._mock_app)):
            with patch("gatekit.tui.recent_files.RecentFiles"):  # Don't pollute recent files
                await mock_screen_with_server._save_config_as_with_modal()

        assert mock_screen_with_server._mock_app.config_path == new_path
        assert mock_screen_with_server._mock_app.config_exists is True

    @pytest.mark.asyncio
    async def test_save_as_adds_to_recent_files(self, mock_screen_with_server):
        """After first save, file is added to recent files."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            new_path = Path(f.name)

        mock_screen_with_server._mock_app.push_screen_wait.return_value = new_path

        with patch.object(type(mock_screen_with_server), "app", property(lambda self: mock_screen_with_server._mock_app)):
            # RecentFiles is imported locally, so we patch the module where it's imported from
            with patch("gatekit.tui.recent_files.RecentFiles") as mock_rf:
                mock_recent_files = MagicMock()
                mock_rf.return_value = mock_recent_files

                await mock_screen_with_server._save_config_as_with_modal()

                mock_recent_files.add.assert_called_once_with(new_path)

    @pytest.mark.asyncio
    async def test_save_as_rollback_on_failure(self, mock_screen_with_server):
        """If save fails, path remains None (still new document)."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            new_path = Path(f.name)

        mock_screen_with_server._mock_app.push_screen_wait.return_value = new_path
        mock_screen_with_server._save_and_rebuild = AsyncMock(return_value=False)

        with patch.object(type(mock_screen_with_server), "app", property(lambda self: mock_screen_with_server._mock_app)):
            await mock_screen_with_server._save_config_as_with_modal()

        # Path should be rolled back to None
        assert mock_screen_with_server.config_file_path is None
        assert mock_screen_with_server.is_new_document is True


class TestSaveAndRebuildNewDocument:
    """Tests for _save_and_rebuild() behavior with new documents."""

    @pytest.fixture
    def mock_screen_new_doc(self):
        """Create a mock screen for new document testing."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen
        import asyncio

        config = ProxyConfig.create_empty_for_editing()
        config.upstreams = [
            UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["echo", "test"],
            )
        ]

        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=config,
        )
        # Create mock app
        mock_app = MagicMock()
        mock_app.notify = MagicMock()
        screen._mock_app = mock_app
        screen._persist_config = AsyncMock(return_value=False)  # Simulate save failure
        screen._rebuild_runtime_state = AsyncMock()
        screen._save_lock = asyncio.Lock()
        return screen

    @pytest.mark.asyncio
    async def test_save_failure_does_not_reload_for_new_document(self, mock_screen_new_doc):
        """When save fails for new document, don't try to reload from disk."""
        # _load_config_from_disk should not be called for new documents
        mock_screen_new_doc._load_config_from_disk = MagicMock()
        mock_screen_new_doc._reset_runtime_from_disk = AsyncMock()
        mock_screen_new_doc._mark_clean = MagicMock()

        with patch.object(type(mock_screen_new_doc), "app", property(lambda self: mock_screen_new_doc._mock_app)):
            result = await mock_screen_new_doc._save_and_rebuild()

        assert result is False
        mock_screen_new_doc._load_config_from_disk.assert_not_called()
        mock_screen_new_doc._reset_runtime_from_disk.assert_not_called()
        # Should show appropriate error message
        mock_screen_new_doc._mock_app.notify.assert_called()

    @pytest.mark.asyncio
    async def test_save_failure_keeps_in_memory_config(self, mock_screen_new_doc):
        """When save fails for new document, in-memory config is preserved."""
        original_config = mock_screen_new_doc.config

        with patch.object(type(mock_screen_new_doc), "app", property(lambda self: mock_screen_new_doc._mock_app)):
            await mock_screen_new_doc._save_and_rebuild()

        # Config should be unchanged
        assert mock_screen_new_doc.config is original_config


class TestInitializePluginSystemNewDocument:
    """Tests for plugin system initialization with new documents."""

    @pytest.mark.asyncio
    async def test_initialize_plugin_system_uses_cwd_for_new_document(self):
        """Plugin system uses cwd as config_directory for new documents."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )

        with patch("gatekit.tui.screens.config_editor.base.PluginManager") as mock_pm:
            mock_instance = MagicMock()
            mock_instance.load_plugins = AsyncMock()
            mock_instance.get_available_handlers = MagicMock(return_value={})
            mock_pm.return_value = mock_instance

            await screen._initialize_plugin_system()

            # Should use cwd when no config_file_path
            call_args = mock_pm.call_args
            assert call_args[1]["config_directory"] == Path.cwd()


class TestRebuildRuntimeStateNewDocument:
    """Tests for _rebuild_runtime_state() with new documents."""

    @pytest.mark.asyncio
    async def test_rebuild_runtime_state_uses_cwd_for_new_document(self):
        """Runtime state rebuild uses cwd as config_directory for new documents."""
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        empty_config = ProxyConfig.create_empty_for_editing()
        screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )

        # Helper to close coroutines passed to mocked _run_worker
        def close_coro(coro):
            coro.close()

        # Mock methods called by _rebuild_runtime_state
        screen._refresh_discovery_state = MagicMock()
        screen._run_worker = MagicMock(side_effect=close_coro)
        screen._populate_server_plugins = AsyncMock()
        screen.refresh = MagicMock()

        with patch("gatekit.tui.screens.config_editor.config_persistence.PluginManager") as mock_pm:
            mock_instance = MagicMock()
            mock_instance.load_plugins = AsyncMock()
            mock_pm.return_value = mock_instance

            await screen._rebuild_runtime_state()

            call_args = mock_pm.call_args
            assert call_args[1]["config_directory"] == Path.cwd()


class TestCtrlOCancelNewDocument:
    """Tests for Ctrl+O cancel behavior with new documents."""

    @pytest.mark.asyncio
    async def test_cancel_file_open_stays_in_editor_for_new_document(self):
        """When user cancels FileOpen from a new document, stays in editor."""
        from gatekit.tui.app import GatekitConfigApp
        from gatekit.tui.screens.config_editor.base import ConfigEditorScreen

        app = GatekitConfigApp()
        app.config_exists = False
        app.config_path = None

        # Mock the current screen to be a ConfigEditorScreen
        empty_config = ProxyConfig.create_empty_for_editing()
        mock_screen = ConfigEditorScreen(
            config_file_path=None,
            loaded_config=empty_config,
        )

        # Mock push_screen_wait to return None (user cancelled)
        app.push_screen_wait = AsyncMock(return_value=None)

        # Mock _show_welcome_screen to track if it's called
        app._show_welcome_screen = MagicMock()

        # Mock the screen property to return our mock screen
        with patch.object(type(app), 'screen', property(lambda self: mock_screen)):
            await app._open_config_file_async()

        # Should NOT show welcome screen - should stay in editor
        app._show_welcome_screen.assert_not_called()
