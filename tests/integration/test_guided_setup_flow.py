"""Integration tests for guided setup multi-screen wizard flow.

Tests the complete wizard experience with real data and multi-screen navigation.
These tests use mocked client detection but exercise the full wizard navigation,
state management, and file generation.
"""

import json
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gatekit.tui.guided_setup.models import (
    ClientType,
    DetectedClient,
    DetectedServer,
    GuidedSetupState,
    NavigationAction,
    ScreenResult,
    ServerScope,
    TransportType,
)
from gatekit.tui.screens.guided_setup.wizard_navigator import WizardNavigator



def create_fake_claude_desktop_config(tmp_path: Path, server_names: List[str]) -> Path:
    """Create a fake Claude Desktop config file for testing.

    Args:
        tmp_path: Temporary directory path
        server_names: List of server names to create

    Returns:
        Path to the created config file
    """
    config_dir = tmp_path / ".claude"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "claude_desktop_config.json"

    servers = {}
    for name in server_names:
        servers[name] = {
            "command": "npx",
            "args": ["-y", f"@modelcontextprotocol/server-{name}"]
        }

    config = {"mcpServers": servers}
    config_file.write_text(json.dumps(config, indent=2))

    return config_file


def create_fake_claude_code_config(tmp_path: Path, server_names: List[str]) -> Path:
    """Create a fake Claude Code config file for testing.

    Args:
        tmp_path: Temporary directory path
        server_names: List of server names to create

    Returns:
        Path to the created config file
    """
    config_dir = tmp_path / ".claude-code"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "mcp_settings.json"

    servers = {}
    for name in server_names:
        servers[name] = {
            "command": "npx",
            "args": ["-y", f"@modelcontextprotocol/server-{name}"],
            "scope": "user"
        }

    config = {"mcpServers": servers}
    config_file.write_text(json.dumps(config, indent=2))

    return config_file


@pytest.fixture
def mock_app():
    """Create a mock Textual app for wizard testing."""
    app = MagicMock()
    app.push_screen_wait = AsyncMock()
    return app


@pytest.fixture
def mock_detected_servers():
    """Create mock detected servers for testing."""
    return [
        DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            scope=ServerScope.USER,
        ),
        DetectedServer(
            name="brave-search",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-brave-search"],
            scope=ServerScope.USER,
        ),
    ]


@pytest.fixture
def mock_detected_client(mock_detected_servers):
    """Create a mock detected client for testing."""
    return DetectedClient(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=Path("/fake/.config/claude/claude_desktop_config.json"),
        servers=mock_detected_servers,
        parse_errors=[],
    )


@pytest.mark.asyncio
async def test_complete_happy_path_forward_navigation(tmp_path, mock_app, mock_detected_client):
    """Test complete forward navigation through all screens.

    Scenario:
    1. User selects servers on ServerSelectionScreen (sets config_path)
    2. User selects clients and generates files on ClientSelectionScreen
    3. SetupCompleteScreen shows completion
    """
    navigator = WizardNavigator(mock_app)

    # Mock the wizard flow with CONTINUE actions
    state_after_server_selection = GuidedSetupState()
    state_after_server_selection.selected_server_names = {"filesystem", "brave-search"}
    state_after_server_selection.detected_clients = [mock_detected_client]
    state_after_server_selection.config_path = tmp_path / "gatekit.yaml"

    state_after_summary = GuidedSetupState(
        selected_server_names={"filesystem", "brave-search"},
        detected_clients=[mock_detected_client],
        config_path=tmp_path / "gatekit.yaml",
        selected_client_types={ClientType.CLAUDE_DESKTOP},
    )

    results = [
        ScreenResult(action=NavigationAction.CONTINUE, state=state_after_server_selection),  # ServerSelectionScreen
        ScreenResult(action=NavigationAction.CONTINUE, state=state_after_summary),           # ClientSelectionScreen
        ScreenResult(action=NavigationAction.CONTINUE, state=state_after_summary),           # ClientSetupScreen
        ScreenResult(action=NavigationAction.CONTINUE, state=state_after_summary),           # SetupCompleteScreen
    ]

    mock_app.push_screen_wait.side_effect = results

    # Execute
    result = await navigator.launch()

    # Assert
    assert result == tmp_path / "gatekit.yaml"
    assert navigator.state.selected_server_names == {"filesystem", "brave-search"}
    assert navigator.state.selected_client_types == {ClientType.CLAUDE_DESKTOP}
    assert mock_app.push_screen_wait.call_count == 4


@pytest.mark.asyncio
async def test_back_navigation_preserves_state(tmp_path, mock_app, mock_detected_client):
    """Test that BACK navigation preserves user selections and state.

    Scenario:
    1. User selects servers on ServerSelectionScreen
    2. User continues to ClientSelectionScreen and selects clients
    3. User goes BACK to ServerSelectionScreen
    4. User navigates forward again
    5. Verify all selections are preserved
    """
    navigator = WizardNavigator(mock_app)

    # Build state that accumulates through screens
    state_with_servers = GuidedSetupState(
        selected_server_names={"filesystem", "brave-search"},
        detected_clients=[mock_detected_client],
        config_path=tmp_path / "gatekit.yaml",
    )

    state_with_clients = GuidedSetupState(
        selected_server_names={"filesystem", "brave-search"},
        detected_clients=[mock_detected_client],
        config_path=tmp_path / "gatekit.yaml",
        selected_client_types={ClientType.CLAUDE_DESKTOP},
        restore_dir=tmp_path / "restore",
        generate_restore=True,
    )

    results = [
        # Forward: ServerSelectionScreen → CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_servers),
        # Forward: ClientSelectionScreen → BACK (user goes back)
        ScreenResult(action=NavigationAction.BACK, state=state_with_clients),
        # Back: ServerSelectionScreen → CONTINUE (user continues forward)
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_clients),
        # Forward: ClientSelectionScreen → CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_clients),
        # Forward: ClientSetupScreen → CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_clients),
        # Forward: SetupCompleteScreen → CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_clients),
    ]

    mock_app.push_screen_wait.side_effect = results

    # Execute
    result = await navigator.launch()

    # Assert - state is fully preserved
    assert result == tmp_path / "gatekit.yaml"
    assert navigator.state.selected_server_names == {"filesystem", "brave-search"}
    assert navigator.state.selected_client_types == {ClientType.CLAUDE_DESKTOP}
    assert navigator.state.restore_dir == tmp_path / "restore"
    assert navigator.state.generate_restore is True
    # Verify we visited screens multiple times due to BACK navigation (4 screens with back navigation = 6 calls)
    assert mock_app.push_screen_wait.call_count == 6


@pytest.mark.asyncio
async def test_cancel_from_first_screen(mock_app):
    """Test cancelling from ServerSelectionScreen.

    Scenario:
    1. User cancels from first screen
    2. Wizard returns None
    3. No state preserved
    """
    navigator = WizardNavigator(mock_app)

    # Mock cancel from first screen
    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.CANCEL,
        state=None,
    )

    # Execute
    result = await navigator.launch()

    # Assert
    assert result is None
    assert mock_app.push_screen_wait.call_count == 1


@pytest.mark.asyncio
async def test_cancel_from_middle_screen(tmp_path, mock_app, mock_detected_client):
    """Test cancelling from ClientSelectionScreen.

    Scenario:
    1. User progresses through first two screens
    2. User cancels from ClientSelectionScreen
    3. Wizard returns None
    4. No files created
    """
    navigator = WizardNavigator(mock_app)

    state_with_servers = GuidedSetupState(
        selected_server_names={"filesystem"},
        detected_clients=[mock_detected_client],
    )

    state_with_config = GuidedSetupState(
        selected_server_names={"filesystem"},
        detected_clients=[mock_detected_client],
        config_path=tmp_path / "gatekit.yaml",
    )

    results = [
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_servers),
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_config),
        ScreenResult(action=NavigationAction.CANCEL, state=None),
    ]

    mock_app.push_screen_wait.side_effect = results

    # Execute
    result = await navigator.launch()

    # Assert
    assert result is None
    assert mock_app.push_screen_wait.call_count == 3
    # Verify no config file was created
    assert not (tmp_path / "gatekit.yaml").exists()


@pytest.mark.asyncio
async def test_back_from_first_screen_acts_as_cancel(mock_app):
    """Test that BACK from first screen is treated as cancel.

    Scenario:
    1. User presses BACK on ServerSelectionScreen
    2. Wizard returns None (can't go back further)
    """
    navigator = WizardNavigator(mock_app)

    # Mock BACK from first screen
    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.BACK,
        state=GuidedSetupState(),
    )

    # Execute
    result = await navigator.launch()

    # Assert
    assert result is None
    assert mock_app.push_screen_wait.call_count == 1


@pytest.mark.asyncio
async def test_file_generation_success_with_temp_directory():
    """Test successful file generation to a temporary directory.

    This test verifies that the wizard correctly passes config_path
    through state and returns it on completion.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        config_path = tmp_path / "gatekit.yaml"

        mock_app = MagicMock()
        mock_app.push_screen_wait = AsyncMock()
        navigator = WizardNavigator(mock_app)

        # Mock successful completion with file path
        final_state = GuidedSetupState(config_path=config_path)

        results = [
            ScreenResult(action=NavigationAction.CONTINUE, state=GuidedSetupState()),
            ScreenResult(action=NavigationAction.CONTINUE, state=GuidedSetupState(config_path=config_path)),
            ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
            ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
            ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
        ]

        mock_app.push_screen_wait.side_effect = results

        # Execute
        result = await navigator.launch()

        # Assert
        assert result == config_path
        assert navigator.state.config_path == config_path


@pytest.mark.asyncio
async def test_multiple_clients_selection(tmp_path, mock_app):
    """Test wizard with multiple clients detected and selected.

    Scenario:
    1. Detection finds Claude Desktop and Claude Code
    2. User selects servers from both clients
    3. User selects both clients for configuration
    4. State preserves both client selections
    """
    # Create mock clients
    desktop_servers = [
        DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem"],
            scope=ServerScope.USER,
        ),
    ]

    code_servers = [
        DetectedServer(
            name="github",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-github"],
            scope=ServerScope.USER,
        ),
    ]

    desktop_client = DetectedClient(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=Path("/fake/.config/claude/claude_desktop_config.json"),
        servers=desktop_servers,
        parse_errors=[],
    )

    code_client = DetectedClient(
        client_type=ClientType.CLAUDE_CODE,
        config_path=Path("/fake/.claude-code/mcp_settings.json"),
        servers=code_servers,
        parse_errors=[],
    )

    navigator = WizardNavigator(mock_app)

    final_state = GuidedSetupState(
        selected_server_names={"filesystem", "github"},
        detected_clients=[desktop_client, code_client],
        selected_client_types={ClientType.CLAUDE_DESKTOP, ClientType.CLAUDE_CODE},
        config_path=tmp_path / "gatekit.yaml",
    )

    results = [
        ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
        ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
        ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
        ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
        ScreenResult(action=NavigationAction.CONTINUE, state=final_state),
    ]

    mock_app.push_screen_wait.side_effect = results

    # Execute
    result = await navigator.launch()

    # Assert
    assert result == tmp_path / "gatekit.yaml"
    assert navigator.state.selected_client_types == {ClientType.CLAUDE_DESKTOP, ClientType.CLAUDE_CODE}
    assert navigator.state.selected_server_names == {"filesystem", "github"}


@pytest.mark.asyncio
async def test_claude_code_project_servers_detection(tmp_path):
    """Test end-to-end detection of Claude Code project servers.

    Scenario:
    1. .claude.json has root-level mcpServers
    2. .claude.json also has projects section with per-project servers
    3. Detection finds both root and project servers
    4. Servers are correctly tagged with scope and project_path
    5. Both types appear in the detected servers list
    """
    from gatekit.tui.guided_setup.detection import detect_claude_code
    from gatekit.tui.guided_setup.models import ServerScope

    # Create .claude.json with both root and project servers
    config_file = tmp_path / ".claude.json"
    config = {
        "mcpServers": {
            "global-filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
            }
        },
        "projects": {
            "/Users/test/gatekit": {
                "mcpServers": {
                    "context7": {
                        "command": "npx",
                        "args": ["-y", "@upstash/context7-mcp"]
                    }
                }
            },
            "/Users/test/other-project": {
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-github"]
                    }
                }
            }
        }
    }
    config_file.write_text(json.dumps(config, indent=2))

    # Mock home dir to use our temp path
    with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            client = detect_claude_code()

    # Verify detection succeeded
    assert client is not None
    assert client.has_servers()
    assert len(client.servers) == 3

    # Verify servers by name
    servers_by_name = {s.name: s for s in client.servers}

    # Root-level server should have USER scope and no project_path
    assert "global-filesystem" in servers_by_name
    global_server = servers_by_name["global-filesystem"]
    assert global_server.scope == ServerScope.USER
    assert global_server.project_path is None
    assert global_server.command == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    # Project-specific servers in ~/.claude.json use LOCAL scope (private, per-project)
    assert "context7" in servers_by_name
    context7_server = servers_by_name["context7"]
    assert context7_server.scope == ServerScope.LOCAL
    assert context7_server.project_path == "/Users/test/gatekit"
    assert context7_server.command == ["npx", "-y", "@upstash/context7-mcp"]

    assert "github" in servers_by_name
    github_server = servers_by_name["github"]
    assert github_server.scope == ServerScope.LOCAL
    assert github_server.project_path == "/Users/test/other-project"
    assert github_server.command == ["npx", "-y", "@modelcontextprotocol/server-github"]

    # No parse errors
    assert len(client.parse_errors) == 0
