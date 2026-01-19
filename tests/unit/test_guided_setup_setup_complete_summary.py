"""Tests for SetupCompleteScreen - final configuration summary."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from gatekit.tui.screens.setup_complete import SetupCompleteScreen
from gatekit.tui.guided_setup.models import (
    GuidedSetupState,
    NavigationAction,
    ClientType,
    DeduplicatedServer,
)


@pytest.fixture
def sample_state_with_selections():
    """Create sample state with server and client selections."""
    from gatekit.tui.guided_setup.models import DetectedServer, TransportType

    state = GuidedSetupState()
    state.config_path = Path("/tmp/gatekit.yaml")
    state.restore_dir = Path("/tmp/restore")
    state.generate_restore = True

    # Add selected servers
    server_a = DetectedServer(
        name="server-a",
        transport=TransportType.STDIO,
        command=["node", "server-a.js"],
        url=None,
        env={},
        scope=None,
        project_path=None,
        raw_config={}
    )
    server_b = DetectedServer(
        name="server-b",
        transport=TransportType.STDIO,
        command=["python", "server_b.py"],
        url=None,
        env={},
        scope=None,
        project_path=None,
        raw_config={}
    )
    state.deduplicated_servers = [
        DeduplicatedServer(server=server_a, client_names=["Claude Desktop"], is_shared=False, was_renamed=False),
        DeduplicatedServer(server=server_b, client_names=["Claude Code"], is_shared=False, was_renamed=False),
    ]
    state.selected_server_names = {"server-a", "server-b"}

    # Add detected and selected clients
    from gatekit.tui.guided_setup.models import DetectedClient
    desktop_client = DetectedClient(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=Path("/fake/.config/Claude/claude_desktop_config.json"),
        servers=[server_a],
        parse_errors=[]
    )
    code_client = DetectedClient(
        client_type=ClientType.CLAUDE_CODE,
        config_path=Path("/fake/.claude-code/mcp_settings.json"),
        servers=[server_b],
        parse_errors=[]
    )
    state.detected_clients = [desktop_client, code_client]
    state.selected_client_types = {ClientType.CLAUDE_DESKTOP, ClientType.CLAUDE_CODE}

    return state


class TestSetupCompleteScreenInitialization:
    """Test SetupCompleteScreen initialization."""

    def test_initializes_with_state(self, sample_state_with_selections):
        """Screen initializes with GuidedSetupState."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        assert screen.state is sample_state_with_selections

    def test_initializes_with_legacy_parameters(self):
        """Screen initializes with legacy parameters (no state)."""
        config_path = Path("/tmp/gatekit.yaml")
        restore_dir = Path("/tmp/restore")

        screen = SetupCompleteScreen(
            gatekit_config_path=config_path,
            restore_script_dir=restore_dir,
        )

        assert screen.state is None


class TestSetupCompleteScreenNavigation:
    """Test SetupCompleteScreen navigation actions."""

    def test_finish_button_returns_continue_action(self, sample_state_with_selections):
        """Finish button returns ScreenResult with CONTINUE action."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result

        # Simulate Finish button press
        button = Mock()
        button.id = "finish_button"
        event = Mock()
        event.button = button

        screen.on_button_pressed(event)

        assert result is not None
        assert result.action == NavigationAction.CONTINUE
        assert result.state is sample_state_with_selections

    def test_back_button_returns_back_action(self, sample_state_with_selections):
        """Back button should dismiss with BACK action."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result

        # Simulate Back button press
        button = Mock()
        button.id = "back_button"
        event = Mock()
        event.button = button

        screen.on_button_pressed(event)

        assert result is not None
        assert result.action == NavigationAction.BACK
        assert result.state is sample_state_with_selections

    def test_cancel_button_returns_cancel_action(self, sample_state_with_selections):
        """Cancel button should dismiss with CANCEL action."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result

        # Simulate Cancel button press
        button = Mock()
        button.id = "cancel_button"
        event = Mock()
        event.button = button

        screen.on_button_pressed(event)

        assert result is not None
        assert result.action == NavigationAction.CANCEL
        assert result.state is None

    def test_escape_key_returns_cancel_action(self, sample_state_with_selections):
        """Escape key returns ScreenResult with CANCEL action."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result
        screen.action_cancel()

        assert result is not None
        assert result.action == NavigationAction.CANCEL
        assert result.state is None


class TestSetupCompleteScreenSummaryBuilder:
    """Test configuration summary building."""

    def test_builds_summary_with_servers_and_clients(self, sample_state_with_selections):
        """Should build summary text with servers and clients."""
        from rich.text import Text

        screen = SetupCompleteScreen(state=sample_state_with_selections)

        summary = screen._build_summary_text()

        # Should return a Text object with server and client info
        assert isinstance(summary, Text)

        # Convert to string for inspection
        summary_str = str(summary)

        # Should include server names or "Servers Configured:"
        assert "server-a" in summary_str or "Servers Configured:" in summary_str

        # Should include client names or "Clients Configured:"
        assert "Claude Desktop" in summary_str or "Clients Configured:" in summary_str

    def test_builds_summary_with_no_state(self):
        """Should handle missing state gracefully."""
        from rich.text import Text

        screen = SetupCompleteScreen(
            gatekit_config_path=Path("/tmp/config.yaml")
        )

        summary = screen._build_summary_text()

        # Should return a Text object (may be empty in legacy flow)
        assert isinstance(summary, Text)

    def test_builds_summary_with_empty_selections(self):
        """Should handle empty server/client selections."""
        from rich.text import Text

        state = GuidedSetupState()
        state.config_path = Path("/tmp/config.yaml")
        state.deduplicated_servers = []
        state.selected_server_names = []
        state.selected_client_types = []

        screen = SetupCompleteScreen(state=state)

        summary = screen._build_summary_text()

        # Should not crash and return a Text object
        assert isinstance(summary, Text)


class TestSetupCompleteScreenFileLocationButtons:
    """Test FileLocationsSummary button handlers in SetupCompleteScreen."""

    def test_open_restore_folder_button_handler_state_flow(self, sample_state_with_selections):
        """open_restore_folder handler should use state.restore_dir."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        # Mock _open_folder
        screen._open_folder = Mock()

        # Simulate button press
        button = Mock()
        button.id = "open_restore_folder"
        event = Mock()
        event.button = button

        screen.on_button_pressed(event)

        # Should call _open_folder with state.restore_dir
        screen._open_folder.assert_called_once_with(sample_state_with_selections.restore_dir)

    def test_open_restore_folder_button_handler_legacy_flow(self):
        """open_restore_folder handler should use direct attribute in legacy flow."""
        restore_dir = Path("/tmp/restore")
        screen = SetupCompleteScreen(
            gatekit_config_path=Path("/tmp/config.yaml"),
            restore_script_dir=restore_dir
        )

        # Mock _open_folder
        screen._open_folder = Mock()

        # Simulate button press
        button = Mock()
        button.id = "open_restore_folder"
        event = Mock()
        event.button = button

        screen.on_button_pressed(event)

        # Should call _open_folder with direct attribute
        screen._open_folder.assert_called_once_with(restore_dir)


class TestSetupCompleteScreenButtonHandling:
    """Test button press handling."""

    def test_ignores_unknown_button_ids(self, sample_state_with_selections):
        """Unknown button IDs are ignored gracefully."""
        screen = SetupCompleteScreen(state=sample_state_with_selections)

        button = Mock()
        button.id = "unknown_button"
        event = Mock()
        event.button = button

        # Should not crash
        screen.on_button_pressed(event)
