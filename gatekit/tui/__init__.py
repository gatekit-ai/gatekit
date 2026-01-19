"""Gatekit Terminal User Interface (TUI) module.

This module provides a terminal-based user interface for configuring and
managing Gatekit security policies and server connections.
"""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .screens.config_editor.base import PluginModalTarget


# Store the original unraisable hook
_original_unraisablehook = sys.unraisablehook

# Track if we've installed the hook (to avoid double-install)
_hook_installed = False


def _suppress_subprocess_cleanup_errors(unraisable):
    """Suppress harmless subprocess cleanup errors during app shutdown.

    When the TUI exits, background workers that spawned async subprocesses
    (for server discovery) may not complete before the event loop closes.
    During garbage collection, these subprocess transports try to close
    themselves but find the event loop already closed, raising RuntimeError.

    This is a known Python asyncio bug (https://github.com/python/cpython/issues/114177)
    that is only fixed in Python 3.13+. The errors are harmless - the subprocesses
    have already been terminated, this is just cleanup that can't complete properly.

    On Windows, npx-spawned processes (Node.js MCP servers) can also trigger a
    ValueError "I/O operation on closed pipe" during cleanup due to the additional
    process wrapper layers that npx creates.
    """
    # When __del__ raises an exception, unraisable.object is the __del__ METHOD,
    # not the instance. So str(unraisable.object) looks like:
    # "<function BaseSubprocessTransport.__del__ at 0x...>"
    # We check for subprocess/pipe/transport-related class names in the string.
    obj_str = str(unraisable.object) if unraisable.object is not None else ""

    # Check for Unix/general "Event loop is closed" error
    if unraisable.exc_type is RuntimeError and "Event loop is closed" in str(
        unraisable.exc_value
    ):
        # Check for asyncio subprocess/transport-related cleanup errors
        subprocess_indicators = (
            "SubprocessTransport",
            "PipeTransport",
            "WritePipe",
            "ReadPipe",
            "unix_events",  # Module name for Unix pipe transports
            "base_subprocess",  # Module name for subprocess transports
        )

        if any(indicator in obj_str for indicator in subprocess_indicators):
            # Silently ignore this specific harmless error
            return

    # Check for Windows-specific "I/O operation on closed pipe" error
    # This occurs during subprocess transport cleanup when __del__ tries to warn
    # about unclosed transport but the pipes are already closed.
    # The error chain is: BaseSubprocessTransport.__del__ -> __repr__ -> pipe.fileno() -> ValueError
    if unraisable.exc_type is ValueError and "I/O operation on closed pipe" in str(
        unraisable.exc_value
    ):
        windows_transport_indicators = (
            "SubprocessTransport",  # Matches BaseSubprocessTransport.__del__
            "ProactorBasePipeTransport",
            "_ProactorBasePipeTransport",
            "proactor_events",
        )

        if any(indicator in obj_str for indicator in windows_transport_indicators):
            # Silently ignore this specific harmless error
            return

    # For all other unraisable exceptions, call the original hook
    _original_unraisablehook(unraisable)


def _install_subprocess_cleanup_hook():
    """Install the unraisable hook to suppress subprocess cleanup errors.

    This hook must remain installed until the Python interpreter exits,
    because garbage collection of subprocess transports can happen at any
    time after the event loop closes, including during interpreter shutdown.
    """
    global _hook_installed
    if not _hook_installed:
        sys.unraisablehook = _suppress_subprocess_cleanup_errors
        _hook_installed = True


def run_tui(
    config_path: Optional[Path] = None,
    tui_debug: bool = False,
    config_error: Optional[Exception] = None,
    initial_plugin_modal: Optional["PluginModalTarget"] = None,
) -> None:
    """Run the Gatekit TUI application.

    Args:
        config_path: Optional path to configuration file to load
        tui_debug: Whether to enable TUI debug logging
        config_error: Optional config error to show immediately
        initial_plugin_modal: Optional plugin modal target to open on startup
    """
    from .app import GatekitConfigApp
    from .debug import initialize_debug_logger, cleanup_debug_logger

    # Initialize debug logging if requested
    initialize_debug_logger(enabled=tui_debug)

    # Install custom unraisable hook to suppress harmless subprocess cleanup errors.
    # IMPORTANT: This hook must NOT be restored in a finally block, because garbage
    # collection of subprocess transports happens AFTER run_tui() returns. The hook
    # will remain in place until Python exits, which is the correct behavior.
    # See: https://github.com/python/cpython/issues/114177
    _install_subprocess_cleanup_hook()

    try:
        # Detect if we're running in Claude Code environment and disable mouse to prevent terminal corruption
        # when the process is killed (Claude can't properly cleanup mouse tracking on SIGKILL)
        is_claude_environment = os.getenv("CLAUDECODE") == "1"
        mouse_enabled = not is_claude_environment

        app = GatekitConfigApp(
            config_path,
            tui_debug=tui_debug,
            config_error=config_error,
            initial_plugin_modal=initial_plugin_modal,
        )
        app.run(mouse=mouse_enabled)
    finally:
        # Clean up debug logging
        # Note: We intentionally do NOT restore sys.unraisablehook here because
        # garbage collection of subprocess transports happens after this function
        # returns, and we need the hook to still be in place to suppress those errors.
        cleanup_debug_logger()


__all__ = ["run_tui"]
