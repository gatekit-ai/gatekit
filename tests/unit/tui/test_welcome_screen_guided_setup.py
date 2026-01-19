"""Unit tests for Welcome Screen Guided Setup feature (Phase 1)."""

from unittest.mock import Mock, patch

from gatekit.tui.screens.welcome import WelcomeScreen


class TestWelcomeScreenGuidedSetupPhase1:
    """Test Welcome Screen updates for Guided Setup (Phase 1: Welcome Screen).

    Phase 1 Requirements:
    - FR-1: First-run welcome experience (no recent files)
    - FR-2: Returning user experience (has recent files)
    - FR-3: Button hierarchy (Guided Setup primary, Open File secondary, Create New link)
    """

    def test_has_no_recent_files_when_list_is_empty(self, tmp_path):
        """Test has_recent_files() returns False when recent files list is empty."""
        # Setup: Mock RecentFiles to return empty list
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        with patch('gatekit.tui.screens.welcome.RecentFiles') as MockRecentFiles:
            mock_recent = MockRecentFiles.return_value
            mock_recent.get_all.return_value = []

            screen = WelcomeScreen()

            # Verify: Should detect no recent files
            assert not screen.has_recent_files()

    def test_has_recent_files_when_list_has_items(self, tmp_path):
        """Test has_recent_files() returns True when recent files list has items."""
        # Setup: Mock RecentFiles to return some files
        state_dir = tmp_path / 'state'
        state_dir.mkdir(parents=True)

        test_file = tmp_path / 'test.yaml'
        test_file.touch()

        with patch('gatekit.tui.screens.welcome.RecentFiles') as MockRecentFiles:
            mock_recent = MockRecentFiles.return_value
            mock_recent.get_all.return_value = [
                {
                    'path': str(test_file),
                    'display_name': 'test.yaml',
                    'last_opened': '2025-01-01T00:00:00Z'
                }
            ]

            screen = WelcomeScreen()

            # Verify: Should detect recent files exist
            assert screen.has_recent_files()

    # Note: Tests that require calling compose() need an active Textual app context.
    # Those are better tested as integration tests. For unit tests, we focus on
    # testing the logic (has_recent_files) and button press handling.
    # The compose() method's output will be tested through manual testing and
    # integration tests.

    def test_dismisses_with_guided_setup_when_button_pressed(self, tmp_path):
        """Test pressing Guided Setup button dismisses with 'guided_setup' result."""
        with patch('gatekit.tui.screens.welcome.RecentFiles') as MockRecentFiles:
            mock_recent = MockRecentFiles.return_value
            mock_recent.get_all.return_value = []

            screen = WelcomeScreen()

            # Mock the button press event
            from textual.widgets import Button
            mock_button = Mock(spec=Button)
            mock_button.id = 'guided_setup'

            # Create a mock event
            mock_event = Mock()
            mock_event.button = mock_button

            # Mock run_worker method to capture the coroutine
            screen.run_worker = Mock()

            # Trigger button press handler
            screen.on_button_pressed(mock_event)

            # Verify run_worker was called (to launch the wizard)
            screen.run_worker.assert_called_once()
            # The argument should be a coroutine for _launch_guided_setup
            call_args = screen.run_worker.call_args[0][0]
            assert hasattr(call_args, '__await__'), "Expected a coroutine"

            # Clean up the coroutine to avoid "was never awaited" warning
            call_args.close()
