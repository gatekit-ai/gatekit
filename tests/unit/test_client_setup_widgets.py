"""Tests for ClientSetupScreen widgets.

Tests widgets used by ClientSetupScreen:
- ClientListItem: Selectable client items in master panel
- AlreadyConfiguredAlert: Warning for already-configured clients
"""

from pathlib import Path
from unittest.mock import Mock
from textual.widgets import Button, Static

from gatekit.tui.screens.guided_setup.client_setup import (
    ClientListItem,
    AlreadyConfiguredAlert,
)
from gatekit.tui.guided_setup.models import ClientType


class TestClientListItem:
    """Test ClientListItem widget."""

    def test_initializes_without_warning_icon(self):
        """Item should display client name without warning icon."""
        item = ClientListItem(
            client_type=ClientType.CLAUDE_DESKTOP,
            is_already_configured=False
        )

        # Should display just the name
        assert "Claude Desktop" in str(item.content)
        assert "\u26a0" not in str(item.content)  # No warning icon (any variant)
        assert item.client_type == ClientType.CLAUDE_DESKTOP
        assert not item.is_already_configured

    def test_initializes_with_warning_icon_when_already_configured(self):
        """Item should display warning icon when already configured."""
        item = ClientListItem(
            client_type=ClientType.CLAUDE_CODE,
            is_already_configured=True
        )

        # Should display warning icon + name
        content = str(item.content)
        assert "\u26a0" in content  # Warning icon (works with or without variation selector)
        assert "Claude Code" in content
        assert item.is_already_configured

    def test_is_focusable(self):
        """Item should be focusable for keyboard navigation."""
        item = ClientListItem(
            client_type=ClientType.CLAUDE_DESKTOP,
            is_already_configured=False
        )

        # Should have can_focus = True for keyboard navigation
        assert item.can_focus is True

    def test_click_posts_client_selected_message(self):
        """Clicking item should post ClientSelected message."""
        item = ClientListItem(
            client_type=ClientType.CODEX,
            is_already_configured=False
        )

        # Mock post_message
        posted_messages = []
        item.post_message = lambda msg: posted_messages.append(msg)

        # Create mock click event
        event = Mock()
        event.stop = Mock()

        # Trigger click
        item.on_click(event)

        # Should post message
        assert len(posted_messages) == 1
        msg = posted_messages[0]
        assert isinstance(msg, ClientListItem.ClientSelected)
        assert msg.client_type == ClientType.CODEX

        # Should stop event propagation
        event.stop.assert_called_once()


class TestAlreadyConfiguredAlert:
    """Test AlreadyConfiguredAlert widget."""

    def test_displays_warning_title(self):
        """Alert should display warning title."""
        client_config_path = Path("/home/user/.config/Claude/claude_desktop_config.json")
        gatekit_config_path = "/home/user/gatekit/gatekit.yaml"
        alert = AlreadyConfiguredAlert(
            client_config_path=client_config_path,
            gatekit_config_path=gatekit_config_path
        )

        # Compose and check children
        children = list(alert.compose())

        # Find title
        titles = [c for c in children if isinstance(c, Static) and "alert-title" in c.classes]
        assert len(titles) == 1
        assert "Already Using Gatekit" in str(titles[0].content)
        assert "\u26a0" in str(titles[0].content)  # Warning icon (any variant)

    def test_displays_config_path(self):
        """Alert should display the client config file path."""
        client_config_path = Path("/home/user/.config/Claude/claude_desktop_config.json")
        gatekit_config_path = "/home/user/gatekit/gatekit.yaml"
        alert = AlreadyConfiguredAlert(
            client_config_path=client_config_path,
            gatekit_config_path=gatekit_config_path
        )

        children = list(alert.compose())

        # Find path display
        path_statics = [
            c for c in children
            if isinstance(c, Static) and "config-path" in c.classes
        ]
        assert len(path_statics) == 1
        assert str(client_config_path) in str(path_statics[0].content)

    def test_includes_gatekit_edit_command(self):
        """Alert should include TextArea with command to edit Gatekit config."""
        from gatekit.tui.screens.guided_setup.client_setup import ClipboardShortcutTextArea

        client_config_path = Path("/home/user/.config/Claude/config.json")
        gatekit_config_path = "/home/user/gatekit/gatekit.yaml"
        alert = AlreadyConfiguredAlert(
            client_config_path=client_config_path,
            gatekit_config_path=gatekit_config_path
        )

        children = list(alert.compose())

        # Find TextArea
        textareas = [c for c in children if isinstance(c, ClipboardShortcutTextArea)]
        assert len(textareas) == 1
        assert textareas[0].id == "gatekit_edit_command"
        # Check command includes the gatekit config path
        assert f"gatekit {gatekit_config_path}" in textareas[0].text

    def test_stores_config_paths(self):
        """Alert should store both config paths."""
        client_config_path = Path("/tmp/claude_config.json")
        gatekit_config_path = "/tmp/gatekit.yaml"
        alert = AlreadyConfiguredAlert(
            client_config_path=client_config_path,
            gatekit_config_path=gatekit_config_path
        )

        assert alert.client_config_path == client_config_path
        assert alert.gatekit_config_path == gatekit_config_path


class TestClientSetupScreenNavigation:
    """Test keyboard navigation in ClientSetupScreen."""

    def test_select_client_updates_index(self):
        """_select_client should update selected_client_index."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions

        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/test/config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            ),
            MigrationInstructions(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/test/.claude.json"),
                servers_to_migrate=["server-b"],
                migration_snippet="claude mcp ...",
                instruction_text="Update...",
            ),
        ]

        screen = ClientSetupScreen(migration_instructions=instructions)

        # Mock query_one and call_later
        screen.query_one = Mock()
        screen.call_later = Mock()

        screen._select_client(1)

        assert screen.selected_client_index == 1

    def test_select_client_schedules_rebuild(self):
        """_select_client should schedule _rebuild_detail_panel via call_later."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions

        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/test/config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            ),
        ]

        screen = ClientSetupScreen(migration_instructions=instructions)

        # Mock query_one and call_later
        screen.query_one = Mock()
        screen.call_later = Mock()

        screen._select_client(0)

        screen.call_later.assert_called_once()
        # Verify the callback is _rebuild_detail_panel
        callback = screen.call_later.call_args[0][0]
        assert callback == screen._rebuild_detail_panel

    def test_select_client_ignores_invalid_index(self):
        """_select_client should ignore invalid indices."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions

        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/test/config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            ),
        ]

        screen = ClientSetupScreen(migration_instructions=instructions)

        # Mock query_one and call_later
        screen.query_one = Mock()
        screen.call_later = Mock()

        # Try invalid indices
        screen._select_client(-1)
        screen._select_client(999)

        # Should not schedule rebuild
        assert not screen.call_later.called

    def test_on_mount_selects_first_client(self):
        """on_mount should call _select_client(0) to populate detail panel."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions

        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/test/config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            ),
        ]

        screen = ClientSetupScreen(migration_instructions=instructions)

        # Mock _select_client
        screen._select_client = Mock()

        screen.on_mount()

        # Should select first client
        screen._select_client.assert_called_once_with(0)

    def test_on_mount_does_not_call_select_when_no_instructions(self):
        """on_mount should not call _select_client when no instructions."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen

        screen = ClientSetupScreen(migration_instructions=[])

        # Mock _select_client
        screen._select_client = Mock()

        screen.on_mount()

        # Should not call _select_client
        assert not screen._select_client.called

    def test_handle_client_selected_finds_and_selects_client(self):
        """Handler should find client index and call _select_client."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions

        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/test/config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            ),
            MigrationInstructions(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/test/.claude.json"),
                servers_to_migrate=["server-b"],
                migration_snippet="claude mcp ...",
                instruction_text="Update...",
            ),
        ]

        screen = ClientSetupScreen(migration_instructions=instructions)

        # Mock _select_client
        screen._select_client = Mock()

        # Create ClientSelected event for second client
        event = ClientListItem.ClientSelected(ClientType.CLAUDE_CODE)

        screen.handle_client_selected(event)

        # Should select second client (index 1)
        screen._select_client.assert_called_once_with(1)

    def test_handle_client_selected_does_nothing_for_unknown_client(self):
        """Handler should do nothing if client not found in instructions."""
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.guided_setup.migration_instructions import MigrationInstructions

        instructions = [
            MigrationInstructions(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/test/config.json"),
                servers_to_migrate=["server-a"],
                migration_snippet='{"mcpServers": {...}}',
                instruction_text="Update...",
            ),
        ]

        screen = ClientSetupScreen(migration_instructions=instructions)

        # Mock _select_client
        screen._select_client = Mock()

        # Create ClientSelected event for unknown client
        event = ClientListItem.ClientSelected(ClientType.CODEX)

        screen.handle_client_selected(event)

        # Should not call _select_client
        assert not screen._select_client.called
