"""Guided setup wizard screens and navigation.

This module provides the complete guided setup wizard flow with:
- Individual screen implementations
- WizardNavigator for managing screen flow with back navigation
- launch_guided_setup entry point function

Wizard Flow:
1. ServerSelectionScreen: Select servers, detect clients, set config path
2. ClientSelectionScreen: Select clients, set restore location, generate files
3. ClientSetupScreen: View client setup instructions
4. SetupCompleteScreen: Final configuration summary
"""

from pathlib import Path
from typing import Optional

from textual.app import App

from .server_selection import ServerSelectionScreen
from .client_selection import ClientSelectionScreen
from .client_setup import ClientSetupScreen
from .wizard_navigator import WizardNavigator

__all__ = [
    "ServerSelectionScreen",
    "ClientSelectionScreen",
    "ClientSetupScreen",
    "WizardNavigator",
    "launch_guided_setup",
]


async def launch_guided_setup(app: App) -> Optional[Path]:
    """Launch guided setup wizard.

    Entry point for the guided setup flow. Creates a WizardNavigator
    and delegates to its launch() method.

    Args:
        app: The Textual app instance

    Returns:
        Path to created config file, or None if cancelled

    Example:
        >>> config_path = await launch_guided_setup(self.app)
        >>> if config_path:
        ...     # User completed setup, load the config
        ...     self.dismiss(str(config_path))
    """
    navigator = WizardNavigator(app)
    return await navigator.launch()
