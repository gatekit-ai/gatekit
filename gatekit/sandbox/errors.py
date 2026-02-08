"""Sandbox-specific error types."""


class SandboxError(Exception):
    """Base class for sandbox errors."""


class SandboxUnavailableError(SandboxError):
    """Raised when sandboxing is enabled but no engine is available.

    Includes diagnostic information about why sandboxing isn't available
    and platform-specific installation instructions.
    """

    def __init__(self, message: str, diagnostic: str = ""):
        super().__init__(message)
        self.diagnostic = diagnostic


class SandboxConfigError(SandboxError):
    """Raised when sandbox configuration is invalid."""
