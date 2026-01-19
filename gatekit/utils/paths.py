"""Path resolution utilities for Gatekit configuration.

This module provides utilities for resolving paths in configuration files
relative to the configuration file's location, supporting home directory
expansion and cross-platform path handling.
"""

import os
from pathlib import Path
from typing import Union


def expand_user_path(path: str) -> Path:
    """Expand ~ to user home directory.

    Args:
        path: Path string that may contain ~ for home directory

    Returns:
        Path: Path object with ~ expanded to user home directory

    Examples:
        >>> expand_user_path("~/Documents/config.yaml")
        PosixPath('/Users/username/Documents/config.yaml')

        >>> expand_user_path("~other/config.yaml")
        PosixPath('/Users/other/config.yaml')

        >>> expand_user_path("/absolute/path")
        PosixPath('/absolute/path')
    """
    if not path:
        return Path(path)

    # Use os.path.expanduser to handle ~ and ~user patterns
    expanded = os.path.expanduser(path)
    return Path(expanded)


def ensure_absolute_path(path: str, base_dir: Union[str, Path]) -> Path:
    """Ensure a path is absolute, resolving relative to base_dir if needed.

    Args:
        path: Path string to make absolute
        base_dir: Base directory to resolve relative paths against

    Returns:
        Path: Absolute path object

    Examples:
        >>> ensure_absolute_path("/absolute/path", "/base")
        PosixPath('/absolute/path')

        >>> ensure_absolute_path("relative/path", "/base")
        PosixPath('/base/relative/path')

        >>> ensure_absolute_path("~/user/path", "/base")
        PosixPath('/Users/username/user/path')
    """
    # First expand any ~ in the path
    expanded_path = expand_user_path(path)

    # If already absolute, return as-is
    if expanded_path.is_absolute():
        return expanded_path

    # Convert base_dir to Path if it's a string
    base_path = Path(base_dir) if isinstance(base_dir, str) else base_dir

    # Resolve relative path against base directory
    resolved_path = base_path / expanded_path

    # Resolve any .. and . components
    return resolved_path.resolve()


def resolve_config_path(path: str, config_dir: Union[str, Path]) -> Path:
    """Resolve a path from configuration, handling various path formats.

    This is the main path resolution function for Gatekit configuration files.
    It handles:
    - Absolute paths (returned as-is)
    - Home directory expansion (~)
    - Relative paths (resolved relative to config_dir)

    Args:
        path: Path string from configuration file
        config_dir: Directory containing the configuration file

    Returns:
        Path: Resolved absolute path object

    Raises:
        TypeError: If path is not a string
        ValueError: If path is empty or whitespace-only

    Examples:
        >>> resolve_config_path("/absolute/path", "/config/dir")
        PosixPath('/absolute/path')

        >>> resolve_config_path("logs/audit.log", "/config/dir")
        PosixPath('/config/dir/logs/audit.log')

        >>> resolve_config_path("~/logs/audit.log", "/config/dir")
        PosixPath('/Users/username/logs/audit.log')
    """
    # Validate input types
    if not isinstance(path, str):
        raise TypeError("Path must be a string")

    # Check for empty or whitespace-only paths
    if not path or not path.strip():
        raise ValueError("Path cannot be empty")

    # Convert config_dir to Path if it's a string
    config_path = Path(config_dir) if isinstance(config_dir, str) else config_dir

    # Use ensure_absolute_path for the actual resolution
    return ensure_absolute_path(path.strip(), config_path)
