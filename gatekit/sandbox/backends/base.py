"""Abstract sandbox backend interface and shared data types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class SandboxProfile:
    """Describes filesystem and network constraints for a sandboxed process.

    Security model: home-directory-denied default with explicit allowlist.

    Attributes:
        read_write_paths: Directories the process may read and write
            (cache dirs + user-configured paths).
        read_only_paths: Directories the process may read but not write
            (auto-detected command runtime paths).
        deny_paths: Sensitive paths to always hide from the process
            (credential directories).
        allow_network: Whether outbound network access is permitted.
    """

    read_write_paths: List[Path] = field(default_factory=list)
    read_only_paths: List[Path] = field(default_factory=list)
    deny_paths: List[Path] = field(default_factory=list)
    allow_network: bool = True


class SandboxBackend(ABC):
    """Interface every sandbox backend must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name (e.g. 'bubblewrap', 'seatbelt')."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend can be used on the current system."""

    @abstractmethod
    def wrap_command(
        self, command: List[str], profile: SandboxProfile
    ) -> List[str]:
        """Prefix *command* with sandbox invocation arguments.

        Returns a new argv list suitable for ``asyncio.create_subprocess_exec``.
        """

    @abstractmethod
    def availability_diagnostic(self) -> str:
        """Return a human-readable explanation of why the backend is unavailable.

        Only called when ``is_available()`` returns False.
        """

    def cleanup(self) -> None:  # noqa: B027
        """Clean up any temporary resources (e.g. profile files).

        Called during transport disconnect.  Default implementation is a no-op.
        """
