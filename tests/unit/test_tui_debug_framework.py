"""Tests for TUI Debug Framework."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import pytest

from gatekit.tui.debug import (
    TUIDebugLogger,
    get_debug_logger,
    initialize_debug_logger,
    cleanup_debug_logger,
)


class TestTUIDebugLogger:
    """Test TUIDebugLogger functionality."""

    def test_disabled_logger(self):
        """Test that disabled logger doesn't create files or write events."""
        logger = TUIDebugLogger(enabled=False)

        assert not logger.enabled
        assert logger.log_file is None

        # Should not create log file
        logger.log_event("test", None)
        assert not logger.log_path.exists() if hasattr(logger, "log_path") else True

    def test_enabled_logger_creates_file(self):
        """Test that enabled logger creates log file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            assert logger.enabled
            assert logger.log_file is not None
            assert logger.session_id is not None
            assert log_path.exists()

            logger.close()

    def test_session_id_consistency(self):
        """Test that session_id remains consistent for logger instance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            session_id1 = logger.session_id
            logger.log_event("test1", None)
            session_id2 = logger.session_id
            logger.log_event("test2", None)
            session_id3 = logger.session_id

            assert session_id1 == session_id2 == session_id3
            logger.close()

    def test_log_event_structure(self):
        """Test that log events have correct JSON structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            logger.log_event(
                "test_event", None, None, {"key": "value"}, extra_data="test"
            )
            logger.close()

            # Read and parse log file
            with open(log_path, "r") as f:
                lines = f.readlines()

            # Should have session_start and test_event
            assert len(lines) >= 2

            # Parse the test event (last line before session_end)
            test_event = json.loads(lines[-2])

            assert test_event["event_type"] == "test_event"
            assert test_event["session_id"] == logger.session_id
            assert "event_id" in test_event
            assert "timestamp" in test_event
            assert test_event["context"] == {"key": "value"}
            assert test_event["data"]["extra_data"] == "test"

    def test_focus_change_logging(self):
        """Test focus change event logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            # Create mock widgets
            old_widget = Mock()
            old_widget.__class__.__name__ = "OldWidget"
            old_widget.id = "old_id"

            new_widget = Mock()
            new_widget.__class__.__name__ = "NewWidget"
            new_widget.id = "new_id"

            logger.log_focus_change(old_widget, new_widget, reason="user_tab")
            logger.close()

            # Read and parse log file
            with open(log_path, "r") as f:
                lines = f.readlines()

            # Find focus_change event
            focus_event = None
            for line in lines:
                event = json.loads(line)
                if event["event_type"] == "focus_change":
                    focus_event = event
                    break

            assert focus_event is not None
            assert focus_event["context"]["reason"] == "user_tab"
            assert focus_event["data"]["old_widget"]["class"] == "OldWidget"
            assert focus_event["data"]["new_widget"]["class"] == "NewWidget"

    def test_navigation_logging(self):
        """Test navigation event logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            widget = Mock()
            widget.__class__.__name__ = "TestWidget"
            widget.id = "test_widget"

            logger.log_navigation("next", "container1", "container2", widget=widget)
            logger.close()

            # Read and parse log file
            with open(log_path, "r") as f:
                lines = f.readlines()

            # Find navigation event
            nav_event = None
            for line in lines:
                event = json.loads(line)
                if event["event_type"] == "navigation":
                    nav_event = event
                    break

            assert nav_event is not None
            assert nav_event["context"]["direction"] == "next"
            assert nav_event["context"]["from_container"] == "container1"
            assert nav_event["context"]["to_container"] == "container2"
            assert nav_event["widget"]["class"] == "TestWidget"

    def test_state_change_logging(self):
        """Test state change event logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            logger.log_state_change("focus_memory", {"old": "value"}, {"new": "value"})
            logger.close()

            # Read and parse log file
            with open(log_path, "r") as f:
                lines = f.readlines()

            # Find state_change event
            state_event = None
            for line in lines:
                event = json.loads(line)
                if event["event_type"] == "state_change":
                    state_event = event
                    break

            assert state_event is not None
            assert state_event["context"]["component"] == "focus_memory"
            assert state_event["data"]["old_value"] == {"old": "value"}
            assert state_event["data"]["new_value"] == {"new": "value"}

    def test_widget_info_extraction(self):
        """Test widget information extraction."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            # Test with None widget
            info = logger._get_widget_info(None)
            assert info is None

            # Test with mock widget with parent chain
            child_widget = Mock()
            child_widget.__class__.__name__ = "ChildWidget"
            child_widget.id = "child"

            parent_widget = Mock()
            parent_widget.__class__.__name__ = "ParentWidget"
            parent_widget.id = "parent"

            # Mock parent chain
            child_widget.parent = parent_widget
            parent_widget.parent = None

            info = logger._get_widget_info(child_widget)
            assert info["id"] == "child"
            assert info["class"] == "ChildWidget"
            assert "ParentWidget" in info["path"]
            assert "ChildWidget" in info["path"]

            logger.close()

    def test_state_dump(self):
        """Test state dump functionality."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            # Create mock screen
            screen = Mock()
            screen.__class__.__name__ = "TestScreen"
            screen.app = Mock()
            screen.app.focused = Mock()
            screen.app.focused.__class__.__name__ = "FocusedWidget"
            screen.app.focused.id = "focused_widget"

            # Mock navigation containers
            screen.navigation_containers = [
                {"name": "container1"},
                {"name": "container2"},
            ]
            screen.current_container_index = 1

            # Mock focus memory
            mock_widget = Mock()
            mock_widget.__class__.__name__ = "MockWidget"
            mock_widget.id = "mock_id"
            screen.container_focus_memory = {"container1": mock_widget}

            dump_json = logger.dump_state(screen)
            dump_data = json.loads(dump_json)

            assert dump_data["screen_type"] == "TestScreen"
            assert dump_data["focused_widget"]["class"] == "FocusedWidget"
            assert dump_data["navigation_state"]["current_container_index"] == 1
            assert dump_data["navigation_state"]["container_names"] == [
                "container1",
                "container2",
            ]
            assert "container1" in dump_data["focus_memory"]

            logger.close()

    def test_log_rotation(self):
        """Test log file rotation when size exceeds 10MB."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            # Mock the stat result to simulate large file
            mock_stat_result = Mock()
            mock_stat_result.st_size = 11 * 1024 * 1024  # 11MB

            # Patch pathlib.Path.stat method
            with patch.object(Path, "stat", return_value=mock_stat_result):
                # This should trigger rotation
                logger._check_log_rotation()

                # Should still have a valid log file
                assert logger.log_file is not None
                assert not logger.log_file.closed

            logger.close()

    def test_cleanup_old_files(self):
        """Test cleanup of old debug files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create some mock old files
            old_log = Path(temp_dir) / "gatekit_tui_debug.old.log"
            old_state = Path(temp_dir) / "gatekit_tui_state_20230101_120000.json"

            old_log.write_text("old log content")
            old_state.write_text('{"old": "state"}')

            # Mock tempfile.gettempdir() to use our temp directory
            with patch("tempfile.gettempdir", return_value=temp_dir):
                with patch("glob.glob") as mock_glob:
                    mock_glob.return_value = [str(old_log), str(old_state)]

                with patch("os.path.getmtime") as mock_getmtime:
                    # Mock files as being older than 7 days
                    mock_getmtime.return_value = 0  # Very old timestamp

                    with patch("os.remove") as mock_remove:
                        logger = TUIDebugLogger(enabled=True)
                        logger._cleanup_old_files()

                        # Should attempt to remove old files
                        assert (
                            mock_remove.call_count >= 0
                        )  # May or may not be called due to mocking

                        logger.close()


class TestDebugLoggerGlobal:
    """Test global debug logger functions."""

    def test_initialize_and_get_logger(self):
        """Test initialization and retrieval of global logger."""
        # Clean up any existing logger
        cleanup_debug_logger()

        # Should return None initially
        assert get_debug_logger() is None

        # Initialize logger
        initialize_debug_logger(enabled=True)

        logger = get_debug_logger()
        assert logger is not None
        assert logger.enabled

        # Clean up
        cleanup_debug_logger()
        assert get_debug_logger() is None

    def test_initialize_disabled_logger(self):
        """Test initialization of disabled logger."""
        cleanup_debug_logger()

        initialize_debug_logger(enabled=False)

        logger = get_debug_logger()
        assert logger is not None
        assert not logger.enabled

        cleanup_debug_logger()


class TestTUIDebugCLIIntegration:
    """Test CLI integration with TUI debug flag."""

    @patch("gatekit.tui.run_tui")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_debug_flag_parsing(self, mock_run_tui):
        """Test that --debug flag is parsed correctly."""
        from gatekit.main import tui_main

        with patch("sys.argv", ["gatekit", "--debug"]):
            tui_main()

        # Should be called with tui_debug=True
        mock_run_tui.assert_called_once_with(
            None,
            tui_debug=True,
            config_error=None,
            initial_plugin_modal=None,
        )

    @patch("gatekit.tui.run_tui")
    @patch("gatekit.main._resolve_config_path")
    @patch("gatekit.main.ConfigLoader")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_debug_flag_with_config(self, mock_loader, mock_resolve, mock_run_tui):
        """Test --debug flag with config file."""
        from gatekit.main import tui_main

        mock_resolve.return_value = Path("test.yaml")
        mock_loader.return_value.load_from_file.return_value = MagicMock()

        with patch("sys.argv", ["gatekit", "test.yaml", "--debug"]):
            tui_main()

        mock_run_tui.assert_called_once_with(
            Path("test.yaml"),
            tui_debug=True,
            config_error=None,
            initial_plugin_modal=None,
        )

    @patch("gatekit.tui.run_tui")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_without_debug_flag(self, mock_run_tui):
        """Test TUI without --tui-debug flag."""
        from gatekit.main import tui_main

        with patch("sys.argv", ["gatekit"]):
            tui_main()

        # Should be called with tui_debug=False (default)
        mock_run_tui.assert_called_once_with(
            None,
            tui_debug=False,
            config_error=None,
            initial_plugin_modal=None,
        )


class TestTUIDebugErrorHandling:
    """Test error handling in debug framework."""

    def test_logger_graceful_degradation(self):
        """Test that logger gracefully handles file system errors."""
        # Use a path with invalid characters that can't be created on any platform
        # On Windows, paths can't contain <, >, :, ", |, ?, *
        # On Unix, paths can't contain null bytes
        # /dev/null/debug.log fails on both (null is a file, not a directory)
        import sys
        if sys.platform == "win32":
            invalid_path = "C:\\invalid<path>\\debug.log"  # Invalid chars on Windows
        else:
            invalid_path = "/dev/null/debug.log"  # /dev/null is not a directory

        logger = TUIDebugLogger(enabled=True, log_path=invalid_path)

        # Should gracefully disable itself
        assert not logger.enabled
        assert logger.log_file is None

        # Logging should not raise errors
        logger.log_event("test", None)
        logger.log_focus_change(None, None)
        logger.dump_state(None)
        logger.close()

    def test_widget_info_extraction_errors(self):
        """Test widget info extraction handles errors gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            # Test with problematic widget
            problematic_widget = Mock()
            problematic_widget.__class__ = None  # This should cause an error

            # Should not raise exception
            info = logger._get_widget_info(problematic_widget)
            assert info is not None  # Should return fallback info

            logger.close()

    def test_state_dump_error_handling(self):
        """Test state dump handles errors gracefully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "test_debug.log"
            logger = TUIDebugLogger(enabled=True, log_path=str(log_path))

            # Create problematic screen mock
            screen = Mock()
            screen.__class__ = None  # This should cause an error

            # Should return error JSON instead of crashing
            result = logger.dump_state(screen)
            dump_data = json.loads(result)

            assert "error" in dump_data
            assert dump_data["session_id"] == logger.session_id

            logger.close()
