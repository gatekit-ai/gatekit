"""TUI screens for Gatekit configuration interface."""

from .config_editor import ConfigEditorScreen, PluginActionContext
from .welcome import WelcomeScreen
from .setup_complete import SetupCompleteScreen

# This module will contain various screens for the TUI as they are developed:
# - MainScreen: Primary configuration interface
# - ServerManagementScreen: MCP server configuration
# - PluginConfigScreen: Security and audit plugin configuration
# - LogViewerScreen: Real-time log viewing
# - HelpScreen: Help and documentation

__all__ = [
    "ConfigEditorScreen",
    "PluginActionContext",
    "WelcomeScreen",
    "SetupCompleteScreen",
]
