"""Tests for ClientSetupScreen - client setup instructions display."""

import pytest
from pathlib import Path
from unittest.mock import Mock

from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
from gatekit.tui.guided_setup.models import (
    GuidedSetupState,
    NavigationAction,
    ClientType,
)
from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions


@pytest.fixture
def sample_state():
    """Create sample state with completed setup."""
    state = GuidedSetupState()
    state.config_path = Path("/tmp/gatekit.yaml")
    state.restore_dir = Path("/tmp/restore")
    state.generate_restore = True
    state.created_files = [
        Path("/tmp/gatekit.yaml"),
        Path("/tmp/restore/restore-claude-desktop.txt"),
    ]
    return state


@pytest.fixture
def sample_migration_instructions():
    """Create sample migration instructions."""
    return [
        MigrationInstructions(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/Claude/config.json"),
            servers_to_migrate=["server-a", "server-b"],
            migration_snippet='{"gatekit": {...}}',
            instruction_text="Update your Claude Desktop config...",
        )
    ]


class TestClientSetupScreenInitialization:
    """Test ClientSetupScreen initialization."""

    def test_initializes_with_state(self, sample_state, sample_migration_instructions):
        """Screen initializes with GuidedSetupState."""
        screen = ClientSetupScreen(
            state=sample_state, migration_instructions=sample_migration_instructions
        )

        assert screen.state is sample_state
        assert len(screen.migration_instructions) == 1

    def test_initializes_with_legacy_parameters(self, sample_migration_instructions):
        """Screen initializes with legacy parameters (no state)."""
        config_path = Path("/tmp/gatekit.yaml")
        restore_dir = Path("/tmp/restore")

        screen = ClientSetupScreen(
            gatekit_config_path=config_path,
            restore_script_dir=restore_dir,
            migration_instructions=sample_migration_instructions,
        )

        assert screen.state is None
        assert len(screen.migration_instructions) == 1


class TestClientSetupScreenNavigation:
    """Test ClientSetupScreen navigation actions."""

    def test_next_button_returns_continue_action(
        self, sample_state, sample_migration_instructions
    ):
        """Next button returns ScreenResult with CONTINUE action."""
        screen = ClientSetupScreen(
            state=sample_state, migration_instructions=sample_migration_instructions
        )

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result

        # Simulate Next button press
        button = Mock()
        button.id = "next_button"
        event = Mock()
        event.button = button

        screen.on_button_pressed(event)

        assert result is not None
        assert result.action == NavigationAction.CONTINUE
        assert result.state is sample_state

    def test_back_button_returns_back_action(self, sample_state, sample_migration_instructions):
        """Back button should dismiss with BACK action."""
        screen = ClientSetupScreen(
            state=sample_state, migration_instructions=sample_migration_instructions
        )

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
        assert result.state is sample_state

    def test_cancel_button_returns_cancel_action(self, sample_state, sample_migration_instructions):
        """Cancel button should dismiss with CANCEL action."""
        screen = ClientSetupScreen(
            state=sample_state, migration_instructions=sample_migration_instructions
        )

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
        assert result.state is None  # Cancel doesn't preserve state

    def test_escape_key_returns_cancel_action(
        self, sample_state, sample_migration_instructions
    ):
        """Escape key returns ScreenResult with CANCEL action."""
        screen = ClientSetupScreen(
            state=sample_state, migration_instructions=sample_migration_instructions
        )

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result
        screen.action_cancel()

        assert result is not None
        assert result.action == NavigationAction.CANCEL
        assert result.state is None


class TestClientSetupScreenClientDetection:
    """Test client selection and already-configured detection."""

    def test_is_client_already_configured_returns_match(self):
        """Should find client in already_configured_clients list."""
        from gatekit.tui.guided_setup.models import DetectedClient

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/Claude/claude_desktop_config.json"),
            servers=[],
        )
        state = GuidedSetupState(already_configured_clients=[client])

        # Create migration instructions for the client
        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/Claude/claude_desktop_config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            )
        ]

        screen = ClientSetupScreen(state=state, migration_instructions=instructions)

        result = screen._is_client_already_configured(ClientType.CLAUDE_DESKTOP)

        assert result is not None
        assert result.client_type == ClientType.CLAUDE_DESKTOP
        assert result.config_path == client.config_path

    def test_is_client_already_configured_returns_none_when_not_found(self):
        """Should return None when client not in already_configured_clients."""
        state = GuidedSetupState(already_configured_clients=[])
        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/test/.claude.json"),
                servers_to_migrate=["server-a"],
                migration_snippet="claude mcp ...",
                instruction_text="Update...",
            )
        ]

        screen = ClientSetupScreen(state=state, migration_instructions=instructions)

        result = screen._is_client_already_configured(ClientType.CLAUDE_CODE)

        assert result is None


class TestClientSetupScreenButtonHandling:
    """Test button press handling."""

    def test_ignores_unknown_button_ids(self, sample_state, sample_migration_instructions):
        """Unknown button IDs are ignored gracefully."""
        screen = ClientSetupScreen(
            state=sample_state, migration_instructions=sample_migration_instructions
        )

        button = Mock()
        button.id = "unknown_button"
        event = Mock()
        event.button = button

        # Should not crash
        screen.on_button_pressed(event)
