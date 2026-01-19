"""Integration tests for textual-fspicker FileOpen dialog integration."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gatekit.tui.app import GatekitConfigApp


class TestFileOpenIntegration:
    """Test FileOpen modal integration with config loading."""

    @pytest.mark.asyncio
    async def test_open_config_file_async_success(self):
        """Test FileOpen modal integration with successful config loading."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_config_path = temp_path / "test.yaml"

            # Create a valid test config
            test_config_path.write_text("""
proxy:
  transport: stdio
  upstreams:
    - name: test-server
      transport: stdio
      command: echo
      args: ["hello"]
""")

            app = GatekitConfigApp()

            async with app.run_test():
                # Mock push_screen_wait to return our test config path
                mock_push = AsyncMock(return_value=test_config_path)

                with patch.object(app, 'push_screen_wait', mock_push):
                    with patch.object(app, '_load_config') as mock_load:
                        # Call the method we're testing
                        await app._open_config_file_async()

                        # Verify FileOpen was shown
                        assert mock_push.called, "push_screen_wait should be called to show FileOpen"

                        # Verify _load_config was called with selected path
                        mock_load.assert_called_once_with(test_config_path)

    @pytest.mark.asyncio
    async def test_open_config_file_async_cancel_with_config(self):
        """Test FileOpen cancellation when config already loaded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            existing_config = temp_path / "existing.yaml"
            existing_config.write_text("proxy:\n  transport: stdio\n")

            # Create app with existing config
            app = GatekitConfigApp(config_path=existing_config)

            async with app.run_test():
                # Mock push_screen_wait to return None (user cancelled)
                mock_push = AsyncMock(return_value=None)

                with patch.object(app, 'push_screen_wait', mock_push):
                    with patch.object(app, 'exit') as mock_exit:
                        await app._open_config_file_async()

                        # Should NOT exit when config already loaded
                        mock_exit.assert_not_called()

    @pytest.mark.asyncio
    async def test_open_config_file_async_cancel_no_config(self):
        """Test FileOpen cancellation when no config loaded - should return to welcome screen."""
        app = GatekitConfigApp()  # No config_path

        async with app.run_test():
            # Mock push_screen_wait to return None (user cancelled)
            mock_push = AsyncMock(return_value=None)

            with patch.object(app, 'push_screen_wait', mock_push):
                with patch.object(app, '_show_welcome_screen') as mock_welcome:
                    await app._open_config_file_async()

                    # Should return to welcome screen instead of exiting
                    mock_welcome.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_config_file_async_cancel_with_invalid_config_path(self):
        """Test FileOpen cancellation when config_path is set but config doesn't exist - should return to welcome screen."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_config = temp_path / "missing.yaml"

            # Create app with non-existent config (config_path set, config_exists=False)
            # Mock _show_config_selector to avoid triggering the config picker on mount
            with patch.object(GatekitConfigApp, '_show_config_selector'):
                app = GatekitConfigApp(config_path=missing_config)

                async with app.run_test():
                    # Verify test setup: config_path is set but config_exists is False
                    assert app.config_path == missing_config
                    assert app.config_exists is False

                    # Mock push_screen_wait to return None (user cancelled)
                    mock_push = AsyncMock(return_value=None)

                    with patch.object(app, 'push_screen_wait', mock_push):
                        with patch.object(app, '_show_welcome_screen') as mock_welcome:
                            await app._open_config_file_async()

                            # Should return to welcome screen instead of exiting
                            mock_welcome.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_config_file_async_uses_context_aware_directory(self):
        """Test that FileOpen starts in context-aware directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create configs subdirectory
            configs_dir = temp_path / "configs"
            configs_dir.mkdir()

            existing_config = configs_dir / "existing.yaml"
            existing_config.write_text("proxy:\n  transport: stdio\n")

            # Create app with existing config in configs/ directory
            app = GatekitConfigApp(config_path=existing_config)

            async with app.run_test():
                # Mock FileOpen at its import location (inside the method)
                with patch('textual_fspicker.FileOpen') as mock_file_open_class:
                    # Make the mock return a proper awaitable
                    mock_file_open_instance = MagicMock()
                    mock_file_open_class.return_value = mock_file_open_instance

                    with patch.object(app, 'push_screen_wait', AsyncMock(return_value=None)):
                        with patch.object(app, 'exit'):
                            await app._open_config_file_async()

                            # Verify FileOpen was instantiated
                            assert mock_file_open_class.called

                            # Get the arguments passed to FileOpen constructor
                            call_kwargs = mock_file_open_class.call_args[1]

                            # Verify location is the parent directory of existing config
                            # Use resolve() to handle symlinks (e.g., /var -> /private/var on macOS)
                            assert call_kwargs['location'].resolve() == configs_dir.resolve()
                            assert call_kwargs['title'] == "Open Configuration File"

    @pytest.mark.asyncio
    async def test_show_config_selector_runs_worker(self):
        """Test that _show_config_selector uses run_worker for async execution."""
        app = GatekitConfigApp()

        async with app.run_test():
            # Mock run_worker and capture/close the coroutine to avoid warning
            def mock_run_worker(coro, **kwargs):
                # Close the coroutine to prevent "never awaited" warning
                coro.close()
                return MagicMock()

            with patch.object(app, 'run_worker', side_effect=mock_run_worker) as mock_run_worker_patch:
                # Call the sync method
                app._show_config_selector()

                # Verify run_worker was called
                assert mock_run_worker_patch.called, "_show_config_selector should use run_worker"

    @pytest.mark.asyncio
    async def test_file_open_with_yaml_filters(self):
        """Test that FileOpen is configured with YAML file filters."""
        # Import outside run_test() to avoid side effects during app initialization
        from textual_fspicker import Filters

        app = GatekitConfigApp()

        async with app.run_test():
            with patch('textual_fspicker.FileOpen') as mock_file_open_class:
                # Make the mock return a proper awaitable
                mock_file_open_instance = MagicMock()
                mock_file_open_class.return_value = mock_file_open_instance

                with patch.object(app, 'push_screen_wait', AsyncMock(return_value=None)):
                    with patch.object(app, '_show_welcome_screen'):
                        await app._open_config_file_async()

                        # Verify FileOpen was instantiated
                        assert mock_file_open_class.called

                        # Get the arguments passed to FileOpen constructor
                        call_kwargs = mock_file_open_class.call_args[1]

                        # Verify filters were provided
                        assert 'filters' in call_kwargs
                        filters = call_kwargs['filters']
                        assert isinstance(filters, Filters)

                        # Verify filter functions work correctly
                        # Access internal _filters attribute
                        yaml_filter = filters._filters[0]  # ("YAML", lambda p: ...)
                        all_filter = filters._filters[1]   # ("All", lambda _: ...)

                        assert yaml_filter[0] == "YAML"
                        assert all_filter[0] == "All"

                        # Test YAML filter accepts .yaml and .yml files
                        from pathlib import Path
                        assert yaml_filter[1](Path("test.yaml")) is True
                        assert yaml_filter[1](Path("test.yml")) is True
                        assert yaml_filter[1](Path("test.YAML")) is True  # case insensitive
                        assert yaml_filter[1](Path("test.txt")) is False

                        # Test All filter accepts everything
                        assert all_filter[1](Path("anything.txt")) is True
