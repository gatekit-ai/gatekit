"""Cross-platform path resolution for user directories.

This module provides platform-appropriate directory resolution without external
dependencies, following XDG Base Directory Specification on Linux.
"""

import os
import sys
from pathlib import Path
from typing import Optional


def get_user_state_dir(appname: str, appauthor: Optional[str] = None) -> Path:
    """Get platform-appropriate user state directory.

    Returns:
        - Linux: $XDG_STATE_HOME/appname or ~/.local/state/appname
        - macOS: ~/Library/Application Support/appname
        - Windows: %LOCALAPPDATA%/appname

    The directory is created with secure permissions (0700 on Unix).

    Args:
        appname: Name of the application
        appauthor: Optional application author (unused, kept for compatibility)

    Returns:
        Path to the user state directory
    """
    if sys.platform == "win32":
        appdata = os.getenv("LOCALAPPDATA")
        if not appdata:
            appdata = os.path.expanduser("~\\AppData\\Local")
        path = Path(appdata) / appname
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / appname
    else:  # Linux/Unix - follow XDG Base Directory Specification
        state_home = os.getenv("XDG_STATE_HOME")
        if state_home:
            path = Path(state_home) / appname
        else:
            path = Path.home() / ".local" / "state" / appname

    # Create directory if it doesn't exist
    path.mkdir(parents=True, exist_ok=True, mode=0o700)

    # CRITICAL: Enforce permissions even if directory already existed
    # mkdir's mode only applies to newly-created dirs
    try:
        path.chmod(0o700)
    except (OSError, NotImplementedError):
        # chmod not supported on Windows, that's OK
        pass

    return path


def get_user_config_dir(appname: str, appauthor: Optional[str] = None) -> Path:
    """Get platform-appropriate user config directory.

    Returns:
        - Linux: $XDG_CONFIG_HOME/appname or ~/.config/appname
        - macOS: ~/Library/Application Support/appname
        - Windows: %LOCALAPPDATA%/appname

    The directory is created with secure permissions (0700 on Unix).

    Args:
        appname: Name of the application
        appauthor: Optional application author (unused, kept for compatibility)

    Returns:
        Path to the user config directory
    """
    if sys.platform == "win32":
        appdata = os.getenv("LOCALAPPDATA")
        if not appdata:
            appdata = os.path.expanduser("~\\AppData\\Local")
        path = Path(appdata) / appname
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / appname
    else:  # Linux/Unix - follow XDG Base Directory Specification
        config_home = os.getenv("XDG_CONFIG_HOME")
        if config_home:
            path = Path(config_home) / appname
        else:
            path = Path.home() / ".config" / appname

    path.mkdir(parents=True, exist_ok=True, mode=0o700)

    try:
        path.chmod(0o700)
    except (OSError, NotImplementedError):
        pass

    return path


def get_user_log_dir(appname: str, appauthor: Optional[str] = None) -> Path:
    """Get platform-appropriate user log directory.

    Returns:
        - Linux: $XDG_STATE_HOME/appname or ~/.local/state/appname
        - macOS: ~/Library/Logs/appname
        - Windows: %LOCALAPPDATA%/appname/logs

    The directory is created with secure permissions (0700 on Unix).

    Args:
        appname: Name of the application
        appauthor: Optional application author (unused, kept for compatibility)

    Returns:
        Path to the user log directory
    """
    if sys.platform == "win32":
        appdata = os.getenv("LOCALAPPDATA")
        if not appdata:
            appdata = os.path.expanduser("~\\AppData\\Local")
        path = Path(appdata) / appname / "logs"
    elif sys.platform == "darwin":
        # macOS uses ~/Library/Logs for application logs
        path = Path.home() / "Library" / "Logs" / appname
    else:  # Linux/Unix - XDG spec uses state dir for logs
        state_home = os.getenv("XDG_STATE_HOME")
        if state_home:
            path = Path(state_home) / appname
        else:
            path = Path.home() / ".local" / "state" / appname

    path.mkdir(parents=True, exist_ok=True, mode=0o700)

    try:
        path.chmod(0o700)
    except (OSError, NotImplementedError):
        pass

    return path
