"""Version utility for Gatekit.

This module provides a centralized way to retrieve the Gatekit version
dynamically, with fallback mechanisms for different deployment scenarios.
"""

import importlib.metadata
from typing import Optional


def get_gatekit_version() -> str:
    """Get Gatekit version dynamically.

    Returns:
        str: The Gatekit version string, or "unknown" if not determinable
    """
    try:
        # Try to get version from package metadata (installed package)
        return importlib.metadata.version("gatekit")
    except (ImportError, importlib.metadata.PackageNotFoundError):
        # Fallback to reading from version file
        try:
            from gatekit import __version__

            return __version__
        except ImportError:
            return "unknown"


def get_gatekit_version_with_fallback(fallback: Optional[str] = None) -> str:
    """Get Gatekit version with custom fallback.

    Args:
        fallback: Custom fallback version string if version cannot be determined

    Returns:
        str: The Gatekit version string, or fallback if not determinable
    """
    version = get_gatekit_version()
    if version == "unknown" and fallback is not None:
        return fallback
    return version
