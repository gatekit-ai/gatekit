"""Locate gatekit-gateway executable using robust fallback strategy."""

import sys
import shutil
from pathlib import Path
from typing import Optional


def locate_gatekit_gateway() -> Path:
    """Find gatekit-gateway executable using multiple strategies.

    Tries multiple strategies to handle different installation methods:
    1. Sibling to sys.executable (works for venvs, pipx)
    2. PATH search via shutil.which (works for --user, system installs)

    Prefers sibling location when both exist to ensure we use the same
    environment as the running TUI.

    Returns:
        Path: Absolute path to gatekit-gateway executable

    Raises:
        FileNotFoundError: If gatekit-gateway cannot be found by any strategy
    """
    bin_dir = Path(sys.executable).parent

    # Strategy 1: Try sibling to sys.executable
    # Works for: venv, pipx, some system installs
    # Check both bare name (POSIX) and .exe (Windows)
    for candidate in ["gatekit-gateway", "gatekit-gateway.exe"]:
        sibling_path = bin_dir / candidate
        if sibling_path.exists():
            return sibling_path.resolve()

    # Strategy 2: Search PATH
    # Works for: pip install --user, system installs where scripts
    # are in a different bin directory than python
    # shutil.which automatically handles .exe on Windows
    which_result = shutil.which("gatekit-gateway")
    if which_result:
        return Path(which_result).resolve()

    # Strategy 3: Not found - show clear error
    raise FileNotFoundError(
        "gatekit-gateway not found. "
        f"Tried:\n"
        f"  1. Sibling to Python: {bin_dir / 'gatekit-gateway'} (and .exe variant)\n"
        f"  2. PATH search: shutil.which('gatekit-gateway')\n"
        f"\n"
        f"Please ensure Gatekit is properly installed."
    )


def validate_gateway_path(gateway_path: Optional[Path]) -> bool:
    """Validate that a gateway path exists and is executable.

    Args:
        gateway_path: Path to validate (or None)

    Returns:
        True if path exists and is executable, False otherwise
    """
    if gateway_path is None:
        return False

    if not gateway_path.exists():
        return False

    # On Unix-like systems, check if executable bit is set
    # On Windows, checking exists() is sufficient as .exe files are executable
    if sys.platform != "win32":
        import os

        return os.access(gateway_path, os.X_OK)

    return True
