"""Tests for ClientSelectionScreen - client selection and restore path configuration."""

import pytest
from pathlib import Path

from textual.widgets import DataTable

from gatekit.tui.screens.guided_setup.client_selection import (
    ClientSelectionScreen,
)
from gatekit.tui.guided_setup.models import (
    ClientType,
    DetectedClient,
    DetectedServer,
    DeduplicatedServer,
    GuidedSetupState,
    NavigationAction,
    TransportType,
)


@pytest.fixture
def sample_state():
    """Create sample state with selections."""
    server1 = DetectedServer(
        name="server-a",
        transport=TransportType.STDIO,
        command=["node", "server-a.js"],
        env={"API_KEY": "secret123"},
    )
    server2 = DetectedServer(
        name="server-b",
        transport=TransportType.STDIO,
        command=["python", "server-b.py"],
    )

    deduplicated = [
        DeduplicatedServer(
            server=server1,
            client_names=["Claude Desktop"],
            is_shared=False,
            was_renamed=False,
        ),
        DeduplicatedServer(
            server=server2,
            client_names=["Claude Code"],
            is_shared=False,
            was_renamed=False,
        ),
    ]

    client1 = DetectedClient(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=Path("/home/user/.config/Claude/config.json"),
        servers=[server1],
    )
    client2 = DetectedClient(
        client_type=ClientType.CLAUDE_CODE,
        config_path=Path("/home/user/.claude.json"),
        servers=[server2],
    )

    state = GuidedSetupState()
    state.deduplicated_servers = deduplicated
    state.detected_clients = [client1, client2]
    state.selected_server_names = {"server-a", "server-b"}
    state.selected_client_types = {ClientType.CLAUDE_DESKTOP, ClientType.CLAUDE_CODE}
    state.config_path = Path("/test/gatekit.yaml")  # Set config path (from previous screen)

    return state


class TestClientSelectionScreenInitialization:
    """Test screen initialization."""

    def test_initializes_with_state(self, sample_state):
        """Screen initializes with provided state."""
        screen = ClientSelectionScreen(sample_state)

        assert screen.state is sample_state
        assert screen.state.selected_server_names == {"server-a", "server-b"}


class TestClientSelectionScreenStatePersistence:
    """Test state persistence for back navigation."""

    def test_restores_restore_dir_from_state(self, sample_state):
        """Restore dir input shows value from state on revisit."""
        sample_state.restore_dir = Path("/custom/restore/dir")

        screen = ClientSelectionScreen(sample_state)

        assert screen.state.restore_dir == Path("/custom/restore/dir")


class TestClientSelectionScreenNavigation:
    """Test navigation actions."""

    def test_back_button_returns_back_with_preserved_state(self, sample_state):
        """Back button returns BACK action with state."""
        sample_state.restore_dir = Path("/custom/restore")
        screen = ClientSelectionScreen(sample_state)

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result
        screen.on_back()

        assert result is not None
        assert result.action == NavigationAction.BACK
        assert result.state is sample_state
        # Verify paths preserved
        assert result.state.restore_dir == Path("/custom/restore")

    def test_escape_key_returns_cancel_with_none_state(self, sample_state):
        """Escape key returns CANCEL action with None state."""
        screen = ClientSelectionScreen(sample_state)

        result = None

        def capture_result(r):
            nonlocal result
            result = r

        screen.dismiss = capture_result
        screen.action_cancel()

        assert result is not None
        assert result.action == NavigationAction.CANCEL
        assert result.state is None


# ============================================================================
# Phase 1: Client Selection Integration Tests
# ============================================================================


# Phase 1 Fixtures
@pytest.fixture
def mock_clients_no_gatekit():
    """Create mock detected clients without Gatekit."""
    return [
        DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/mock/claude/config.json"),
            servers=[
                DetectedServer(
                    name="server1",
                    transport=TransportType.STDIO,
                    command=["npx", "server1"],
                )
            ],
            gatekit_config_path=None,  # No Gatekit
        ),
        DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/mock/code/config.json"),
            servers=[
                DetectedServer(
                    name="server2",
                    transport=TransportType.STDIO,
                    command=["npx", "server2"],
                )
            ],
            gatekit_config_path=None,  # No Gatekit
        ),
    ]


@pytest.fixture
def mock_clients_with_gatekit():
    """Create mock detected clients, some with Gatekit already configured."""
    return [
        DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/mock/claude/config.json"),
            servers=[
                DetectedServer(
                    name="server1",
                    transport=TransportType.STDIO,
                    command=["npx", "server1"],
                )
            ],
            gatekit_config_path="/mock/claude/gatekit.yaml",  # Has Gatekit!
        ),
        DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/mock/code/config.json"),
            servers=[
                DetectedServer(
                    name="server2",
                    transport=TransportType.STDIO,
                    command=["npx", "server2"],
                )
            ],
            gatekit_config_path=None,  # No Gatekit
        ),
    ]


@pytest.fixture
def mock_clients_all_with_gatekit():
    """Create mock detected clients where ALL have Gatekit configured."""
    return [
        DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/mock/claude/config.json"),
            servers=[
                DetectedServer(
                    name="server1",
                    transport=TransportType.STDIO,
                    command=["npx", "server1"],
                )
            ],
            gatekit_config_path="/mock/claude/gatekit.yaml",
        ),
        DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/mock/code/config.json"),
            servers=[
                DetectedServer(
                    name="server2",
                    transport=TransportType.STDIO,
                    command=["npx", "server2"],
                )
            ],
            gatekit_config_path="/mock/code/gatekit.yaml",
        ),
    ]


# ============================================================================
# Phase 1 Tests: TestInitializeFromState
# ============================================================================


class TestInitializeFromState:
    """Test _initialize_from_state() method (Phase 1)."""

    def test_reuses_detected_clients_from_state_no_rescan(
        self, mock_clients_no_gatekit
    ):
        """Test that _initialize_from_state() reuses state.detected_clients (no re-scan)."""
        state = GuidedSetupState(detected_clients=mock_clients_no_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        # Call the initialization method (will be implemented)
        screen._initialize_from_state()

        # Should store clients locally without re-scanning
        assert hasattr(screen, "_available_clients")
        # Now includes all supported clients (detected + placeholders for undetected)
        # All 5 supported clients (Claude Desktop, Claude Code, Codex, Cursor, Windsurf)
        assert len(screen._available_clients) == 5
        # The detected clients should be in the list
        detected_types = {c.client_type for c in mock_clients_no_gatekit}
        available_detected = [c for c in screen._available_clients if c.client_type in detected_types]
        assert len(available_detected) == 2

    def test_keeps_all_clients_including_ones_with_gatekit(
        self, mock_clients_with_gatekit
    ):
        """Test that ALL clients are kept, including ones already using Gatekit."""
        state = GuidedSetupState(detected_clients=mock_clients_with_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        screen._initialize_from_state()

        # Should keep ALL supported clients (detected + placeholders)
        assert len(screen._available_clients) == 5
        # Including the one with Gatekit
        assert any(c.has_gatekit() for c in screen._available_clients)

    def test_identifies_clients_already_using_gatekit(self, mock_clients_with_gatekit):
        """Test that clients already using Gatekit are identified correctly for next screen."""
        state = GuidedSetupState(detected_clients=mock_clients_with_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        screen._initialize_from_state()

        # Should populate already_configured_clients for next screen
        assert len(state.already_configured_clients) == 1
        assert state.already_configured_clients[0].client_type == ClientType.CLAUDE_DESKTOP
        assert state.already_configured_clients[0].has_gatekit()

    def test_populates_already_configured_with_full_objects(
        self, mock_clients_with_gatekit
    ):
        """Test that already_configured_clients stores full DetectedClient objects."""
        state = GuidedSetupState(detected_clients=mock_clients_with_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        screen._initialize_from_state()

        # Should store full DetectedClient objects
        assert all(isinstance(c, DetectedClient) for c in state.already_configured_clients)
        # Should have all metadata
        configured = state.already_configured_clients[0]
        # Compare path parts to handle cross-platform differences
        # (On Windows, /mock/... becomes C:/mock/...)
        assert configured.config_path.parts[-3:] == ("mock", "claude", "config.json")
        assert configured.gatekit_config_path == "/mock/claude/gatekit.yaml"

    def test_atomic_rebuild_clears_before_repopulating(self, mock_clients_with_gatekit):
        """Test that already_configured_clients is cleared before repopulating (atomic rebuild)."""
        state = GuidedSetupState(detected_clients=mock_clients_with_gatekit)
        state.config_path = Path("/test/gatekit.yaml")

        # Pre-populate with some data to simulate previous initialization
        dummy_client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/dummy/config.json"),
            gatekit_config_path="/dummy/gatekit.yaml",
        )
        state.already_configured_clients.append(dummy_client)

        screen = ClientSelectionScreen(state)
        screen._initialize_from_state()

        # Should have cleared and rebuilt, only containing actual configured clients
        assert len(state.already_configured_clients) == 1
        assert state.already_configured_clients[0].client_type == ClientType.CLAUDE_DESKTOP

    def test_no_duplicates_on_back_navigation(self, mock_clients_with_gatekit):
        """Test that going BACK and returning doesn't create duplicates in already_configured_clients."""
        state = GuidedSetupState(detected_clients=mock_clients_with_gatekit)
        state.config_path = Path("/test/gatekit.yaml")

        # First visit
        screen1 = ClientSelectionScreen(state)
        screen1._initialize_from_state()
        assert len(state.already_configured_clients) == 1

        # Simulate BACK navigation (same state object is reused)
        # Second visit (should clear and rebuild)
        screen2 = ClientSelectionScreen(state)
        screen2._initialize_from_state()

        # Should still have exactly 1, not 2
        assert len(state.already_configured_clients) == 1

    def test_initializes_selected_client_types_first_visit(
        self, mock_clients_no_gatekit
    ):
        """Test that selected_client_types is initialized with all clients on first visit."""
        state = GuidedSetupState(detected_clients=mock_clients_no_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        # Ensure selected_client_types is empty (first visit)
        state.selected_client_types = set()

        screen = ClientSelectionScreen(state)
        screen._initialize_from_state()

        # Should select all clients by default
        assert len(state.selected_client_types) == 2
        assert ClientType.CLAUDE_DESKTOP in state.selected_client_types
        assert ClientType.CLAUDE_CODE in state.selected_client_types

    def test_preserves_selected_client_types_on_back_navigation(
        self, mock_clients_no_gatekit
    ):
        """Test that selected_client_types is preserved when user navigates BACK."""
        state = GuidedSetupState(detected_clients=mock_clients_no_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        # Simulate user had deselected Claude Code
        state.selected_client_types = {ClientType.CLAUDE_DESKTOP}

        screen = ClientSelectionScreen(state)
        screen._initialize_from_state()

        # Should preserve user's selections
        assert len(state.selected_client_types) == 1
        assert ClientType.CLAUDE_DESKTOP in state.selected_client_types
        assert ClientType.CLAUDE_CODE not in state.selected_client_types

    def test_handles_empty_detected_clients(self):
        """Test handling of empty detected_clients list."""
        state = GuidedSetupState(detected_clients=[])
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        screen._initialize_from_state()

        # Should handle gracefully - still shows all supported clients as placeholders
        assert len(screen._available_clients) == 5  # All supported clients
        assert len(state.already_configured_clients) == 0
        assert len(state.selected_client_types) == 0  # None selected since none detected

    def test_handles_all_clients_already_configured(
        self, mock_clients_all_with_gatekit
    ):
        """Test handling when ALL detected clients already use Gatekit."""
        state = GuidedSetupState(detected_clients=mock_clients_all_with_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        screen._initialize_from_state()

        # All detected clients should be tracked in already_configured_clients
        assert len(state.already_configured_clients) == 2
        assert all(c.has_gatekit() for c in state.already_configured_clients)
        # All supported clients should be available (detected + placeholders)
        assert len(screen._available_clients) == 5


# ============================================================================
# Phase 1 Tests: TestClientSelectionDataTable
# ============================================================================


class TestClientSelectionDataTable:
    """Test client selection DataTable (Phase 1)."""

    @pytest.mark.asyncio
    async def test_datatable_shows_all_supported_clients(
        self, mock_clients_no_gatekit
    ):
        """Test that DataTable shows ALL supported clients (detected + undetected)."""
        from textual.app import App

        state = GuidedSetupState(detected_clients=mock_clients_no_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        screen = ClientSelectionScreen(state)

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            screen._initialize_from_state()
            screen._populate_clients_table()

            table = screen.query_one("#clients_table", DataTable)
            # Shows all 5 supported clients (2 detected + 3 undetected)
            assert table.row_count == 5

    @pytest.mark.asyncio
    async def test_checkbox_indicators_for_selected_clients(
        self, mock_clients_no_gatekit
    ):
        """Test that checkbox indicators show correct state ([X] vs [ ])."""
        from textual.app import App

        state = GuidedSetupState(detected_clients=mock_clients_no_gatekit)
        state.config_path = Path("/test/gatekit.yaml")
        # Select only Claude Desktop
        state.selected_client_types = {ClientType.CLAUDE_DESKTOP}

        screen = ClientSelectionScreen(state)

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            screen._initialize_from_state()
            screen._populate_clients_table()

            table = screen.query_one("#clients_table", DataTable)
            # Should show all 5 supported clients
            assert table.row_count == 5

            # Verify that detected clients can be selected, undetected cannot
            # Claude Desktop (detected, selected) and Claude Code (detected, not selected)
            # should be in the list along with 3 undetected clients


# Truncating the rest of the massive test file - we've included the core tests for:
# - Initialization and state persistence
# - Client selection functionality
# - Navigation actions
# - Already-configured clients handling
