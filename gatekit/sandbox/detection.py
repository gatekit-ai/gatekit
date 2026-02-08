"""Platform detection and sandbox backend selection."""

import sys
import logging
from typing import Optional

from .backends.base import SandboxBackend
from .errors import SandboxUnavailableError

logger = logging.getLogger(__name__)


def get_sandbox_backend() -> Optional[SandboxBackend]:
    """Return the appropriate sandbox backend for the current platform.

    Returns:
        A SandboxBackend instance if one is available, None otherwise.
    """
    backend = _detect_backend()
    if backend is not None and backend.is_available():
        return backend
    return None


def is_sandbox_available() -> bool:
    """Check whether sandboxing is available on this platform."""
    return get_sandbox_backend() is not None


def get_sandbox_backend_or_raise() -> SandboxBackend:
    """Return the sandbox backend or raise if unavailable.

    Raises:
        SandboxUnavailableError: With platform-specific installation instructions.
    """
    backend = _detect_backend()
    if backend is None:
        raise SandboxUnavailableError(
            f"Sandboxing is not supported on {sys.platform}.",
            diagnostic=f"Platform '{sys.platform}' has no supported sandbox engine. "
            "Sandboxing is available on macOS (sandbox-exec) and Linux (bubblewrap).",
        )
    if not backend.is_available():
        raise SandboxUnavailableError(
            f"Sandbox engine '{backend.name}' is not available: "
            f"{backend.availability_diagnostic()}",
            diagnostic=backend.availability_diagnostic(),
        )
    return backend


def _detect_backend() -> Optional[SandboxBackend]:
    """Detect the correct backend for the current OS without checking availability."""
    if sys.platform == "darwin":
        from .backends.seatbelt import SeatbeltBackend

        return SeatbeltBackend()
    elif sys.platform == "linux":
        from .backends.bubblewrap import BubblewrapBackend

        return BubblewrapBackend()
    return None
