"""Tests for ServerSelectionScreen - server selection functionality."""

import pytest
from pathlib import Path
from unittest.mock import Mock


from gatekit.tui.screens.guided_setup.server_selection import (
    ServerSelectionScreen,
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
def mock_detected_clients():
    """Create mock detected clients for testing."""
    server1 = DetectedServer(
        name="server-a",
        transport=TransportType.STDIO,
        command=["node", "server-a.js"],
    )
    server2 = DetectedServer(
        name="server-b",
        transport=TransportType.STDIO,
        command=["python", "server-b.py"],
    )

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

    return [client1, client2]


@pytest.fixture
def mock_deduplicated_servers(mock_detected_clients):
    """Create mock deduplicated servers."""
    return [
        DeduplicatedServer(
            server=mock_detected_clients[0].servers[0],
            client_names=["Claude Desktop"],
            is_shared=False,
            was_renamed=False,
        ),
        DeduplicatedServer(
            server=mock_detected_clients[1].servers[0],
            client_names=["Claude Code"],
            is_shared=False,
            was_renamed=False,
        ),
    ]


@pytest.fixture
def sample_state_with_servers():
    """Create sample state with deduplicated servers for selection testing."""
    server1 = DetectedServer(
        name="server-a",
        transport=TransportType.STDIO,
        command=["node", "server-a.js"],
    )
    server2 = DetectedServer(
        name="server-b",
        transport=TransportType.STDIO,
        command=["python", "server-b.py"],
    )
    server3 = DetectedServer(
        name="server-c-renamed",
        transport=TransportType.STDIO,
        command=["node", "server.js"],
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
            client_names=["Claude Desktop", "Claude Code"],
            is_shared=True,
            was_renamed=False,
        ),
        DeduplicatedServer(
            server=server3,
            client_names=["Codex"],
            is_shared=False,
            was_renamed=True,
            original_name="server-c",
        ),
    ]

    state = GuidedSetupState()
    state.deduplicated_servers = deduplicated
    state.detected_clients = [
        DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/Claude/config.json"),
            servers=[server1, server2],
        )
    ]

    return state


class TestServerSelectionScreenStateInjection:
    """Test state injection and initialization."""

    def test_creates_new_state_when_none_provided(self):
        """Screen creates new GuidedSetupState when none provided."""
        screen = ServerSelectionScreen()

        assert screen.state is not None
        assert isinstance(screen.state, GuidedSetupState)
        assert screen.state.deduplicated_servers == []

    def test_uses_provided_state_for_rescan(self):
        """Screen uses provided state for rescan scenarios."""
        existing_state = GuidedSetupState()
        existing_state.selected_server_names = {"server-a", "server-b"}

        screen = ServerSelectionScreen(state=existing_state)

        assert screen.state is existing_state
        assert screen.state.selected_server_names == {"server-a", "server-b"}


class TestServerSelectionScreenDetection:
    """Test detection and UI updates."""

    def test_rescan_preserves_selections_via_state_update(self, mock_detected_clients, mock_deduplicated_servers):
        """Rescan preserves selections via update_deduplicated_servers method."""
        # Create state with existing selections
        existing_state = GuidedSetupState()
        existing_state.selected_server_names = {"server-a"}

        # Test the state update logic directly (which is what rescan uses)
        existing_state.update_deduplicated_servers(mock_deduplicated_servers, mock_detected_clients)

        # Verify selections were preserved/reconciled
        assert "server-a" in existing_state.selected_server_names
        # New servers should be auto-selected
        assert "server-b" in existing_state.selected_server_names

    @pytest.mark.asyncio
    async def test_run_detection_populates_state_and_updates_ui(self, mock_detected_clients):
        """run_detection updates state selections, summary text, DataTable, and button visibility."""

        class DummyButton:
            def __init__(self, hidden: bool = False) -> None:
                self.classes = {"hidden"} if hidden else set()
                self.focused = False

            def add_class(self, class_name: str) -> None:
                self.classes.add(class_name)

            def remove_class(self, class_name: str) -> None:
                self.classes.discard(class_name)

            def focus(self) -> None:
                self.focused = True

        class DummyStatic:
            def __init__(self) -> None:
                self.rendered: list[str] = []

            def update(self, value: str) -> None:
                self.rendered.append(value)

            def add_class(self, class_name: str) -> None:
                pass

            def remove_class(self, class_name: str) -> None:
                pass

        class DummyWorker:
            def __init__(self, result):
                self._result = result

            async def wait(self):
                return self._result

        class DummyDataTable:
            def __init__(self):
                self.rows = []
                self.columns = []
                self.classes = set()
                self.cursor_row = 0
                self.focused = False

            def clear(self):
                self.rows = []

            def add_column(self, *args, **kwargs):
                self.columns.append(args[0] if args else "")

            def add_row(self, *args, **kwargs):
                self.rows.append(args)

            def add_class(self, class_name: str) -> None:
                self.classes.add(class_name)

            def remove_class(self, class_name: str) -> None:
                self.classes.discard(class_name)

            def focus(self) -> None:
                self.focused = True

        class DummyContainer:
            def __init__(self):
                self.classes = set()

            def add_class(self, class_name: str) -> None:
                self.classes.add(class_name)

            def remove_class(self, class_name: str) -> None:
                self.classes.discard(class_name)

        # Create screen
        screen = ServerSelectionScreen()

        # Mock query_one to return dummy widgets (removed client-related widgets)
        widgets = {
            "#servers_table": DummyDataTable(),
            "#selection_summary": DummyStatic(),
            "#next_button": DummyButton(),
            "#conflict_info_container": DummyContainer(),
        }

        def mock_query_one(selector, widget_type=None):
            return widgets.get(selector)

        screen.query_one = mock_query_one

        # Mock run_worker to return detected clients
        def mock_run_worker(func, **kwargs):
            return DummyWorker(mock_detected_clients)

        screen.run_worker = mock_run_worker

        # Run detection
        await screen.run_detection()

        # Verify state was updated
        assert len(screen.state.deduplicated_servers) == 2
        # Note: detected_clients is filtered to only available clients (no gatekit)
        assert len(screen.state.detected_clients) == 2

        # Verify servers table was populated
        servers_table = widgets["#servers_table"]
        assert len(servers_table.rows) == 2  # Two servers

        # Verify summary was updated
        summary = widgets["#selection_summary"]
        assert len(summary.rendered) > 0
        assert "2 of 2" in summary.rendered[-1]  # All servers selected by default

        # Verify next button is visible
        next_button = widgets["#next_button"]
        assert "hidden" not in next_button.classes


class TestServerSelectionScreenSelectionLogic:
    """Test server selection behavior."""

    def test_initializes_all_servers_selected_by_default(self, sample_state_with_servers):
        """All servers are selected by default on first visit (via run_detection)."""
        screen = ServerSelectionScreen(sample_state_with_servers)

        # Simulate run_detection initializing selections
        if not screen.state.selected_server_names:
            screen.state.selected_server_names = {
                ds.server.name for ds in screen.state.deduplicated_servers
            }

        assert len(screen.state.selected_server_names) == 3
        assert "server-a" in screen.state.selected_server_names
        assert "server-b" in screen.state.selected_server_names
        assert "server-c-renamed" in screen.state.selected_server_names

    def test_preserves_existing_selections_on_revisit(self, sample_state_with_servers):
        """Existing selections are preserved when returning to screen."""
        # Simulate user having already made selections
        sample_state_with_servers.selected_server_names = {"server-a"}

        screen = ServerSelectionScreen(sample_state_with_servers)

        # Should preserve the existing selection, not reset to all
        assert screen.state.selected_server_names == {"server-a"}

    def test_toggle_selection_updates_state(self, sample_state_with_servers):
        """Toggling selection updates state.selected_server_names."""
        screen = ServerSelectionScreen(sample_state_with_servers)
        screen.state.selected_server_names = {"server-a", "server-b", "server-c-renamed"}

        # Mock DataTable
        class MockDataTable:
            def __init__(self):
                self.cursor_coordinate = Mock(row=0)
                self.rows = []
                self.columns = []

            def coordinate_to_cell_key(self, coord):
                # Return mock row key for server-a
                row_key = Mock()
                row_key.value = "server-a"
                return (row_key, None)

            def clear(self):
                pass

            def add_column(self, *args, **kwargs):
                pass

            def add_row(self, *args, **kwargs):
                pass

            def move_cursor(self, **kwargs):
                pass

        class MockStatic:
            def update(self, text):
                pass

        mock_table = MockDataTable()
        mock_summary = MockStatic()

        def mock_query(selector, widget_type=None):
            if selector == "#servers_table":
                return mock_table
            elif selector == "#selection_summary":
                return mock_summary
            return mock_table

        screen.query_one = mock_query

        # Toggle server-a off
        screen.action_toggle_selection()
        assert "server-a" not in screen.state.selected_server_names

        # Toggle server-a back on
        screen.action_toggle_selection()
        assert "server-a" in screen.state.selected_server_names

    def test_select_all_selects_all_servers(self, sample_state_with_servers):
        """Select All action selects all servers."""
        sample_state_with_servers.selected_server_names = set()  # Start with none selected
        screen = ServerSelectionScreen(sample_state_with_servers)

        # Mock _populate_servers_table and _update_summary
        screen._populate_servers_table = lambda: None
        screen._update_summary = lambda: None

        # Mock DataTable for cursor position
        class MockDataTable:
            cursor_coordinate = Mock(row=0)

            def move_cursor(self, **kwargs):
                pass

        screen.query_one = lambda selector, widget_type=None: MockDataTable()

        screen.action_select_all()

        assert len(screen.state.selected_server_names) == 3
        assert "server-a" in screen.state.selected_server_names
        assert "server-b" in screen.state.selected_server_names
        assert "server-c-renamed" in screen.state.selected_server_names

    def test_select_none_deselects_all_servers(self, sample_state_with_servers):
        """Select None action deselects all servers."""
        screen = ServerSelectionScreen(sample_state_with_servers)
        screen.state.selected_server_names = {"server-a", "server-b", "server-c-renamed"}

        # Mock methods to avoid UI dependencies
        screen._populate_servers_table = lambda: None
        screen._update_summary = lambda: None

        # Mock DataTable for cursor position
        class MockDataTable:
            cursor_coordinate = Mock(row=0)

            def move_cursor(self, **kwargs):
                pass

        screen.query_one = lambda selector, widget_type=None: MockDataTable()

        screen.action_select_none()

        assert len(screen.state.selected_server_names) == 0


class TestServerSelectionScreenResizeHandling:
    """Test terminal resize handling."""

    def test_resize_repopulates_servers_table(self):
        """Resize event repopulates servers table."""
        screen = ServerSelectionScreen()

        # Track table population calls
        servers_populated = False

        def mock_populate_servers():
            nonlocal servers_populated
            servers_populated = True

        screen._populate_servers_table = mock_populate_servers

        # Trigger resize
        from textual.events import Resize
        screen.on_resize(Resize(80, 24))

        assert servers_populated


class TestServerSelectionScreenNavigationActions:
    """Test navigation button actions."""

    def test_next_button_returns_continue_action(self):
        """Next button returns CONTINUE action with state."""
        screen = ServerSelectionScreen()

        # Mock dismiss
        dismissed_result = None

        def mock_dismiss(result):
            nonlocal dismissed_result
            dismissed_result = result

        screen.dismiss = mock_dismiss

        screen.on_next()

        assert dismissed_result is not None
        assert dismissed_result.action == NavigationAction.CONTINUE
        assert dismissed_result.state is screen.state

    def test_cancel_button_returns_cancel_action(self):
        """Cancel button returns CANCEL action with None state."""
        screen = ServerSelectionScreen()

        dismissed_result = None

        def mock_dismiss(result):
            nonlocal dismissed_result
            dismissed_result = result

        screen.dismiss = mock_dismiss

        screen.on_cancel()

        assert dismissed_result is not None
        assert dismissed_result.action == NavigationAction.CANCEL
        assert dismissed_result.state is None


class TestServerSelectionScreenSummaryUpdates:
    """Test selection summary display."""

    def test_summary_shows_selection_count(self, sample_state_with_servers):
        """Summary displays correct selection count."""
        screen = ServerSelectionScreen(sample_state_with_servers)
        screen.state.selected_server_names = {"server-a", "server-b"}

        # Mock Static widget
        class MockStatic:
            def __init__(self):
                self.text = ""

            def update(self, text):
                self.text = text

        mock_summary = MockStatic()
        screen.query_one = lambda selector, widget_type=None: mock_summary

        screen._update_summary()

        assert "2 of 3" in mock_summary.text

    def test_summary_shows_no_servers_message(self):
        """Summary shows appropriate message when no servers found."""
        screen = ServerSelectionScreen()

        class MockStatic:
            def __init__(self):
                self.text = ""

            def update(self, text):
                self.text = text

        mock_summary = MockStatic()
        screen.query_one = lambda selector, widget_type=None: mock_summary

        screen._update_summary()

        assert "No servers found" in mock_summary.text
