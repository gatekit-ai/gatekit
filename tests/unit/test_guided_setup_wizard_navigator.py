"""Tests for WizardNavigator class.

Tests wizard navigation logic with support for BACK/CONTINUE/CANCEL actions.
Comprehensive end-to-end wizard flow tests are in tests/integration/test_guided_setup_flow.py.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from gatekit.tui.guided_setup.models import (
    GuidedSetupState,
    NavigationAction,
    ScreenResult,
)
from gatekit.tui.screens.guided_setup.wizard_navigator import WizardNavigator


@pytest.fixture
def mock_app():
    """Create a mock Textual app."""
    app = MagicMock()
    app.push_screen_wait = AsyncMock()
    return app


@pytest.fixture
def navigator(mock_app):
    """Create a WizardNavigator instance."""
    return WizardNavigator(mock_app)


@pytest.mark.asyncio
async def test_navigate_to_updates_state_on_continue(navigator, mock_app):
    """Test that navigate_to updates state when user continues."""
    # Setup
    mock_screen_class = MagicMock()
    initial_state = GuidedSetupState()
    navigator.state = initial_state

    # Mock screen returns CONTINUE with updated state
    updated_state = GuidedSetupState()
    updated_state.config_path = Path("/test/path")

    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.CONTINUE,
        state=updated_state
    )

    # Execute
    action = await navigator.navigate_to(mock_screen_class)

    # Assert
    assert action == NavigationAction.CONTINUE
    assert navigator.state.config_path == Path("/test/path")
    mock_screen_class.assert_called_once_with(initial_state)


@pytest.mark.asyncio
async def test_navigate_to_preserves_state_on_back(navigator, mock_app):
    """Test that navigate_to preserves state when user goes back."""
    # Setup
    mock_screen_class = MagicMock()
    initial_state = GuidedSetupState()
    initial_state.selected_server_names = {"server-a"}
    navigator.state = initial_state

    # Mock screen returns BACK with preserved state
    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.BACK,
        state=initial_state
    )

    # Execute
    action = await navigator.navigate_to(mock_screen_class)

    # Assert
    assert action == NavigationAction.BACK
    assert navigator.state.selected_server_names == {"server-a"}


@pytest.mark.asyncio
async def test_navigate_to_handles_cancel(navigator, mock_app):
    """Test that navigate_to handles cancel action."""
    # Setup
    mock_screen_class = MagicMock()

    # Mock screen returns CANCEL with no state
    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.CANCEL,
        state=None
    )

    # Execute
    action = await navigator.navigate_to(mock_screen_class)

    # Assert
    assert action == NavigationAction.CANCEL




@pytest.mark.asyncio
async def test_launch_back_navigation_preserves_selections(navigator, mock_app):
    """Test that selections are preserved when going back and forth through 4-screen flow."""
    # Setup
    state_with_selections = GuidedSetupState()
    state_with_selections.selected_server_names = {"server-a"}
    state_with_selections.config_path = Path("/test/config.yaml")

    results = [
        # 1. ServerSelectionScreen: User makes selections, CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_selections),
        # 2. ClientSelectionScreen: Goes BACK
        ScreenResult(action=NavigationAction.BACK, state=state_with_selections),
        # 1. ServerSelectionScreen: CONTINUE (selections preserved)
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_selections),
        # 2. ClientSelectionScreen: CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_selections),
        # 3. ClientSetupScreen: CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_selections),
        # 4. SetupCompleteScreen (summary): CONTINUE
        ScreenResult(action=NavigationAction.CONTINUE, state=state_with_selections),
    ]

    mock_app.push_screen_wait.side_effect = results

    # Execute
    result = await navigator.launch()

    # Assert
    assert result == Path("/test/config.yaml")
    # Verify state was updated at each step
    assert navigator.state.selected_server_names == {"server-a"}
    assert navigator.state.config_path == Path("/test/config.yaml")


@pytest.mark.asyncio
async def test_launch_cancel_from_first_screen(navigator, mock_app):
    """Test cancelling from the first screen."""
    # Setup
    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.CANCEL,
        state=None
    )

    # Execute
    result = await navigator.launch()

    # Assert
    assert result is None
    assert mock_app.push_screen_wait.call_count == 1


@pytest.mark.asyncio
async def test_launch_cancel_from_middle_screen(navigator, mock_app):
    """Test cancelling from a middle screen."""
    # Setup
    results = [
        ScreenResult(action=NavigationAction.CONTINUE, state=GuidedSetupState()),  # ServerSelectionScreen
        ScreenResult(action=NavigationAction.CANCEL, state=None),  # Cancel from ClientSelectionScreen
    ]

    mock_app.push_screen_wait.side_effect = results

    # Execute
    result = await navigator.launch()

    # Assert
    assert result is None
    assert mock_app.push_screen_wait.call_count == 2


@pytest.mark.asyncio
async def test_launch_back_from_first_screen_cancels(navigator, mock_app):
    """Test that going back from first screen is treated as cancel."""
    # Setup
    mock_app.push_screen_wait.return_value = ScreenResult(
        action=NavigationAction.BACK,
        state=GuidedSetupState()
    )

    # Execute
    result = await navigator.launch()

    # Assert
    assert result is None
    assert mock_app.push_screen_wait.call_count == 1


