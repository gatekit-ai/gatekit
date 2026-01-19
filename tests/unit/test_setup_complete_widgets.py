"""Tests for SetupCompleteScreen widgets.

Tests widgets used by SetupCompleteScreen (final summary):
- FileLocationsSummary: File paths display with action buttons
"""

import pytest
from pathlib import Path
from textual.app import App
from textual.widgets import Button, Static

from gatekit.tui.screens.setup_complete import FileLocationsSummary


class TestFileLocationsSummary:
    """Test FileLocationsSummary widget."""

    @pytest.mark.asyncio
    async def test_displays_success_message(self):
        """Summary should display success message."""
        class TestApp(App):
            pass

        app = TestApp()
        async with app.run_test() as pilot:
            summary = FileLocationsSummary(
                config_path=Path("/tmp/gatekit.yaml"),
                restore_dir=None
            )
            await app.mount(summary)

            # Find success message (now uses "success-title" class)
            success_msgs = summary.query(".success-title")
            assert len(success_msgs) == 1
            success_static = success_msgs[0]
            assert isinstance(success_static, Static)
            assert "Configuration created successfully" in str(success_static.content)
            assert "✅" in str(success_static.content)

    @pytest.mark.asyncio
    async def test_displays_gatekit_config_path(self):
        """Summary should display Gatekit config path."""
        config_path = Path("/home/user/gatekit/gatekit.yaml")

        class TestApp(App):
            pass

        app = TestApp()
        async with app.run_test() as pilot:
            summary = FileLocationsSummary(
                config_path=config_path,
                restore_dir=None
            )
            await app.mount(summary)

            # Find config path display (look for Static with path string)
            path_displays = [
                w for w in summary.query(Static)
                if str(config_path) in str(w.content)
            ]
            assert len(path_displays) >= 1

    @pytest.mark.asyncio
    async def test_includes_config_path_buttons(self):
        """Summary should include Open button for config."""
        class TestApp(App):
            pass

        app = TestApp()
        async with app.run_test() as pilot:
            summary = FileLocationsSummary(
                config_path=Path("/tmp/gatekit.yaml"),
                restore_dir=None
            )
            await app.mount(summary)

            # Find all buttons
            buttons = summary.query(Button)

            # Should have Open button (inline with path)
            button_ids = [b.id for b in buttons]
            assert "open_config_file" in button_ids

    @pytest.mark.asyncio
    async def test_displays_restore_dir_when_provided(self):
        """Summary should display restore scripts directory when provided."""
        restore_dir = Path("/home/user/gatekit/restore")

        class TestApp(App):
            pass

        app = TestApp()
        async with app.run_test() as pilot:
            summary = FileLocationsSummary(
                config_path=Path("/tmp/gatekit.yaml"),
                restore_dir=restore_dir
            )
            await app.mount(summary)

            # Find restore path display
            restore_displays = [
                w for w in summary.query(Static)
                if str(restore_dir) in str(w.content)
            ]
            assert len(restore_displays) >= 1

    @pytest.mark.asyncio
    async def test_includes_restore_dir_buttons_when_provided(self):
        """Summary should include Open button for restore directory when provided."""
        class TestApp(App):
            pass

        app = TestApp()
        async with app.run_test() as pilot:
            summary = FileLocationsSummary(
                config_path=Path("/tmp/gatekit.yaml"),
                restore_dir=Path("/tmp/restore")
            )
            await app.mount(summary)

            buttons = summary.query(Button)

            button_ids = [b.id for b in buttons]
            assert "open_restore_folder" in button_ids

    @pytest.mark.asyncio
    async def test_no_restore_section_when_not_provided(self):
        """Summary should not include restore section when restore_dir is None."""
        class TestApp(App):
            pass

        app = TestApp()
        async with app.run_test() as pilot:
            summary = FileLocationsSummary(
                config_path=Path("/tmp/gatekit.yaml"),
                restore_dir=None
            )
            await app.mount(summary)

            buttons = summary.query(Button)

            button_ids = [b.id for b in buttons]
            # Should not have restore button
            assert "open_restore_folder" not in button_ids

    def test_stores_paths(self):
        """Summary should store config and restore paths."""
        config_path = Path("/tmp/config.yaml")
        restore_dir = Path("/tmp/restore")

        summary = FileLocationsSummary(
            config_path=config_path,
            restore_dir=restore_dir
        )

        assert summary.config_path == config_path
        assert summary.restore_dir == restore_dir
