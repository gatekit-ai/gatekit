"""Tests for config save/reload/dirty-state functionality."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from gatekit.config.models import ProxyConfig, TimeoutConfig, UpstreamConfig
from gatekit.tui.screens.config_editor.config_persistence import ConfigPersistenceMixin


class MockConfigEditorScreen(ConfigPersistenceMixin):
    """Mock screen for testing save/reload functionality."""

    def __init__(self, config: ProxyConfig, config_file_path: Path):
        self.config = config
        self.config_file_path = config_file_path
        self.app = MagicMock()
        self.plugin_manager = None
        self._save_lock = asyncio.Lock()

        # Dirty state tracking
        self._config_dirty = False
        self._last_saved_config_hash = self._compute_config_hash()

        # Screen subtitle for header display
        self.sub_title = config_file_path.name

    @property
    def is_new_document(self) -> bool:
        """True if this is a new unsaved document (no file path yet)."""
        return self.config_file_path is None

    def _validate_can_save(self) -> bool:
        """Check if config is valid for saving. Always returns True for tests with existing docs."""
        # Check for empty upstreams
        if not self.config.upstreams:
            self.app.notify(
                "At least one MCP server must be configured before saving.",
                severity="warning",
            )
            return False

        # Check that at least one server is complete (not draft)
        has_complete_server = any(
            not getattr(u, "is_draft", False) for u in self.config.upstreams
        )
        if not has_complete_server:
            self.app.notify(
                "At least one MCP server must be fully configured before saving. "
                "Complete the server configuration (command or URL required).",
                severity="warning",
            )
            return False

        return True

    def _run_worker(self, coro):
        """Mock _run_worker - just run the coroutine."""
        asyncio.create_task(coro)

    async def _reset_runtime_from_disk(self):
        """Mock runtime reset."""
        pass

    async def _rebuild_runtime_state(self):
        """Mock runtime rebuild."""
        pass

    async def _populate_global_plugins(self):
        """Mock populate global plugins."""
        pass

    async def _populate_server_plugins(self):
        """Mock populate server plugins."""
        pass

    def _get_plugin_class(self, handler_name: str, plugin_type: str):
        """Mock plugin class lookup."""
        return None


@pytest.fixture
def temp_config_file(tmp_path):
    """Create a temporary config file."""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test-server
      transport: stdio
      command: echo
      args: ["test"]
""")
    return config_file


@pytest.fixture
def mock_screen(temp_config_file):
    """Create a mock screen with a simple config."""
    config = ProxyConfig(
        transport="stdio",
        upstreams=[
            UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["echo", "test"]
            )
        ],
        timeouts=TimeoutConfig(),
    )
    return MockConfigEditorScreen(config, temp_config_file)


class TestSaveAction:
    """Tests for action_save_config() and _save_config_with_notification()."""

    @pytest.mark.asyncio
    async def test_action_save_config_calls_save_and_rebuild(self, mock_screen):
        """Test that action_save_config triggers _save_and_rebuild."""
        with patch.object(mock_screen, '_save_and_rebuild', new_callable=AsyncMock) as mock_save:
            mock_save.return_value = True

            # Call action_save_config
            mock_screen.action_save_config()

            # Give the worker a moment to run
            await asyncio.sleep(0.1)

            # Verify _save_and_rebuild was called
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_success_marks_clean(self, mock_screen):
        """Test that successful save marks config clean."""
        # Mark dirty first
        mock_screen._mark_dirty()
        assert mock_screen._config_dirty is True

        with patch.object(mock_screen, '_persist_config', new_callable=AsyncMock) as mock_persist:
            with patch.object(mock_screen, '_rebuild_runtime_state', new_callable=AsyncMock):
                mock_persist.return_value = True

                # Call save
                await mock_screen._save_config_with_notification()

                # Verify marked clean
                assert mock_screen._config_dirty is False

    @pytest.mark.asyncio
    async def test_save_failure_reverts_and_marks_clean(self, mock_screen):
        """Test that save failure reverts config and clears dirty flag."""
        # Mark dirty first
        mock_screen._mark_dirty()
        assert mock_screen._config_dirty is True

        with patch.object(mock_screen, '_persist_config', new_callable=AsyncMock) as mock_persist:
            with patch.object(mock_screen, '_load_config_from_disk') as mock_load:
                with patch.object(mock_screen, '_reset_runtime_from_disk', new_callable=AsyncMock):
                    mock_persist.return_value = False
                    mock_load.return_value = mock_screen.config

                    # Call save_and_rebuild
                    result = await mock_screen._save_and_rebuild()

                    # Verify failed and marked clean (reverted to disk state)
                    assert result is False
                    assert mock_screen._config_dirty is False


# COMMENTED OUT: Reload functionality is currently disabled in ConfigPersistenceMixin
# (see config_persistence.py lines 309-386). Uncomment these tests if/when reload is restored.
#
# class TestReloadAction:
#     """Tests for action_reload_config() and _reload_config_with_confirmation()."""
#
#     @pytest.mark.asyncio
#     async def test_reload_discards_in_memory_changes(self, mock_screen):
#         """Test that reload discards in-memory changes."""
#         # Create modified config
#         original_name = mock_screen.config.upstreams[0].name
#         mock_screen.config.upstreams[0].name = "modified-name"
#
#         # Mock loading original config from disk
#         original_config = ProxyConfig(
#             transport="stdio",
#             upstreams=[
#                 UpstreamConfig(
#                     name=original_name,
#                     transport="stdio",
#                     command=["echo", "test"]
#                 )
#             ],
#             timeouts=TimeoutConfig(),
#         )
#
#         with patch.object(mock_screen, '_load_config_from_disk') as mock_load:
#             with patch.object(mock_screen, '_reset_runtime_from_disk', new_callable=AsyncMock):
#                 mock_load.return_value = original_config
#
#                 # Skip dirty check for this test
#                 mock_screen._config_dirty = False
#
#                 # Call reload
#                 await mock_screen._reload_config_with_confirmation()
#
#                 # Verify config was reverted
#                 assert mock_screen.config.upstreams[0].name == original_name
#
#     @pytest.mark.asyncio
#     async def test_reload_shows_confirmation_when_dirty(self, mock_screen):
#         """Test that reload shows confirmation modal when config is dirty."""
#         mock_screen._mark_dirty()
#
#         with patch.object(mock_screen.app, 'push_screen_wait', new_callable=AsyncMock) as mock_modal:
#             mock_modal.return_value = False  # User cancelled
#
#             # Call reload
#             await mock_screen._reload_config_with_confirmation()
#
#             # Verify modal was shown
#             mock_modal.assert_called_once()
#
#     @pytest.mark.asyncio
#     async def test_reload_rollback_uses_rebuild_runtime_state(self, mock_screen):
#         """Test that reload rollback uses _rebuild_runtime_state (not _reset_runtime_from_disk)."""
#         with patch.object(mock_screen, '_load_config_from_disk') as mock_load:
#             with patch.object(mock_screen, '_reset_runtime_from_disk', new_callable=AsyncMock) as mock_reset:
#                 with patch.object(mock_screen, '_rebuild_runtime_state', new_callable=AsyncMock) as mock_rebuild:
#                     mock_load.return_value = ProxyConfig(
#                         transport="stdio",
#                         upstreams=[
#                             UpstreamConfig(
#                                 name="new-server",
#                                 transport="stdio",
#                                 command=["echo", "new"]
#                             )
#                         ],
#                         timeouts=TimeoutConfig(),
#                     )
#                     # Simulate reset failure
#                     mock_reset.side_effect = Exception("Reset failed")
#
#                     # Skip dirty check
#                     mock_screen._config_dirty = False
#
#                     # Call reload (should fail and rollback, exception caught internally)
#                     await mock_screen._reload_config_with_confirmation()
#
#                     # Verify _rebuild_runtime_state was called for rollback
#                     # This is the critical assertion: we use _rebuild_runtime_state (from self.config)
#                     # not _reset_runtime_from_disk (from disk) for rollback
#                     mock_rebuild.assert_called_once()


class TestDirtyStateTracking:
    """Tests for dirty state tracking (_mark_dirty, _mark_clean, _compute_config_hash)."""

    def test_mark_dirty_sets_flag_and_updates_header(self, mock_screen):
        """Test that _mark_dirty sets flag and updates header."""
        # Initially clean
        assert mock_screen._config_dirty is False

        # Mark dirty
        mock_screen._mark_dirty()

        # Verify flag set and subtitle updated
        assert mock_screen._config_dirty is True
        assert hasattr(mock_screen, 'sub_title')
        assert "*" in mock_screen.sub_title
        assert mock_screen.config_file_path.name in mock_screen.sub_title

    def test_mark_clean_clears_flag_and_updates_header(self, mock_screen):
        """Test that _mark_clean clears flag and updates header."""
        # Mark dirty first
        mock_screen._config_dirty = True

        # Mark clean
        mock_screen._mark_clean()

        # Verify flag cleared and subtitle updated
        assert mock_screen._config_dirty is False
        assert hasattr(mock_screen, 'sub_title')
        assert "*" not in mock_screen.sub_title
        assert mock_screen.config_file_path.name in mock_screen.sub_title

    def test_mark_clean_rejects_empty_hash(self, mock_screen):
        """Test that _mark_clean refuses to mark clean when hash is empty (unsaveable config)."""
        # Create config with draft upstream (unsaveable)
        draft = UpstreamConfig.create_draft("draft-server")
        mock_screen.config = ProxyConfig(
            transport="stdio",
            upstreams=[draft],
            timeouts=TimeoutConfig(),
        )

        # Mark dirty
        mock_screen._config_dirty = True

        # Try to mark clean (should fail because draft can't be serialized)
        mock_screen._mark_clean()

        # Verify still dirty (can't mark clean unsaveable config)
        assert mock_screen._config_dirty is True

    def test_compute_config_hash_returns_empty_for_draft_upstream(self, mock_screen):
        """Test that _compute_config_hash returns empty string for draft upstreams."""
        # Create config with draft upstream
        draft = UpstreamConfig.create_draft("draft-server")
        mock_screen.config = ProxyConfig(
            transport="stdio",
            upstreams=[draft],
            timeouts=TimeoutConfig(),
        )

        # Compute hash
        hash_result = mock_screen._compute_config_hash()

        # Verify returns empty string (not a valid hash)
        assert hash_result == ""

    def test_compute_config_hash_consistent_for_same_config(self, mock_screen):
        """Test that _compute_config_hash returns same hash for same config."""
        hash1 = mock_screen._compute_config_hash()
        hash2 = mock_screen._compute_config_hash()

        # Verify same hash
        assert hash1 == hash2
        assert hash1 != ""

    def test_compute_config_hash_changes_when_config_changes(self, mock_screen):
        """Test that _compute_config_hash returns different hash when config changes."""
        hash1 = mock_screen._compute_config_hash()

        # Modify config
        mock_screen.config.upstreams[0].name = "modified-name"

        hash2 = mock_screen._compute_config_hash()

        # Verify different hash
        assert hash1 != hash2
