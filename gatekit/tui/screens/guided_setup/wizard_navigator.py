"""Wizard navigation controller for guided setup.

This module provides the WizardNavigator class that manages screen flow
through the guided setup wizard with support for back navigation.
"""

from pathlib import Path
from typing import Optional, Type

from textual.app import App
from textual.screen import Screen

from gatekit.tui.guided_setup.models import GuidedSetupState, NavigationAction


class WizardNavigator:
    """Helper class to manage wizard screen navigation with back support.

    Provides clean index-based navigation through a sequence of screens,
    handling BACK/CONTINUE/CANCEL actions automatically.

    Attributes:
        app: The Textual app instance
        state: Current wizard state (flows through all screens)
    """

    def __init__(self, app: App):
        """Initialize the wizard navigator.

        Args:
            app: The Textual app instance
        """
        self.app = app
        self.state = GuidedSetupState()

    async def navigate_to(self, screen_class: Type[Screen]) -> NavigationAction:
        """Navigate to a screen and return the user's action.

        Args:
            screen_class: Screen class to instantiate and show

        Returns:
            The navigation action chosen by the user (CONTINUE/BACK/CANCEL)
        """
        # Push screen and wait for result
        result = await self.app.push_screen_wait(screen_class(self.state))

        # Update state regardless of action (preserves selections on BACK)
        if result.state is not None:
            self.state = result.state

        return result.action

    async def launch(self) -> Optional[Path]:
        """Launch wizard with automatic back navigation.

        Navigation Flow:
        1. ServerSelectionScreen: Select servers, detect clients, set config path
        2. ClientSelectionScreen: Select clients, set restore location, generate files
        3. ClientSetupScreen: Show interactive client setup instructions
        4. SetupCompleteScreen: Final configuration summary

        All screens support BACK/CONTINUE/CANCEL actions for flexible navigation.

        Returns:
            Path to created config file, or None if cancelled
        """
        # Import screens here to avoid circular imports
        from gatekit.tui.screens.guided_setup.server_selection import (
            ServerSelectionScreen,
        )
        from gatekit.tui.screens.guided_setup.client_selection import (
            ClientSelectionScreen,
        )
        from gatekit.tui.screens.guided_setup.client_setup import ClientSetupScreen
        from gatekit.tui.screens.setup_complete import SetupCompleteScreen

        # Define the navigable screens (support BACK/CONTINUE/CANCEL)
        screens = [
            ServerSelectionScreen,
            ClientSelectionScreen,
            ClientSetupScreen,
            SetupCompleteScreen,
        ]

        current_index = 0
        while current_index < len(screens):
            action = await self.navigate_to(screens[current_index])

            if action == NavigationAction.CANCEL:
                return None
            elif action == NavigationAction.BACK:
                current_index -= 1  # Go back one screen
                if current_index < 0:
                    return None  # Can't go back from first screen, treat as cancel
            elif action == NavigationAction.CONTINUE:
                current_index += 1  # Advance to next screen
                # If we've completed the final screen, we're done
                if current_index >= len(screens):
                    break

        return self.state.config_path
