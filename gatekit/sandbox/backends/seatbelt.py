"""macOS Seatbelt (sandbox-exec) backend.

Security model: home-directory-denied default with explicit allowlist.

Seatbelt semantics: when both allow and deny rules match a path, allow wins.
This means we cannot use "allow parent + deny child" to carve out exceptions.
Instead, we deny the entire home directory and then selectively allow only
the specific subdirectories the server needs.

Sensitive paths (e.g. ~/.ssh) are protected by simply not being allowed —
the home-directory deny covers them. If a user explicitly allows a parent
path that contains sensitive directories (e.g., paths: ["~"]), the sensitive
directories become accessible because Seatbelt's allow-wins semantics make
it impossible to carve out exceptions. A warning is logged in this case.
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from .base import SandboxBackend, SandboxProfile

logger = logging.getLogger(__name__)

# macOS system paths that are always readable.
# Processes need these to locate binaries, libraries, certificates, etc.
_MACOS_SYSTEM_READ_PATHS = [
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/etc",
    "/opt",
    "/Library",
    "/System",
    "/Applications",
    "/private/etc",
    "/private/var/select",
    "/private/var/folders",  # macOS temp file creation (per-user temp dirs)
    "/dev",
]

# Paths that are always read+write (temp directories)
_MACOS_TEMP_RW_PATHS = [
    "/tmp",
    "/private/tmp",
    "/private/var/folders",  # macOS per-user temp dirs
]


def _escape_seatbelt_string(value: str) -> str:
    """Escape a string for use in a Seatbelt (.sb) profile literal.

    Seatbelt profile strings are double-quoted.  Backslashes and double
    quotes must be escaped to prevent syntax errors or injection.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _path_is_child_of(child: Path, parent: Path) -> bool:
    """Check if child is equal to or a subdirectory of parent."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class SeatbeltBackend(SandboxBackend):
    """Sandbox backend using macOS sandbox-exec with Seatbelt profiles.

    Profile strategy (deny-all with allowlist):
      1. (allow default) — non-filesystem operations
      2. (deny file-write*) — block all writes
      3. (deny file-read* (subpath "HOME")) — block all home directory reads
      4. Allow system paths for read (binaries, libraries, certs)
      5. Allow /tmp + macOS temp dirs for read+write
      6. Allow command runtime paths for read (venvs, scripts)
      7. Allow cache dirs (~/.npm, ~/.cache, ~/.local) for read+write
      8. Allow user-configured paths for read+write

    Sensitive paths (e.g. ~/.ssh) are protected by NOT being allowed.
    Since allow-wins in Seatbelt, we cannot use deny to override allows.
    """

    def __init__(self) -> None:
        self._profile_path: Optional[Path] = None

    @property
    def name(self) -> str:
        return "seatbelt"

    def is_available(self) -> bool:
        return shutil.which("sandbox-exec") is not None

    def wrap_command(
        self, command: List[str], profile: SandboxProfile
    ) -> List[str]:
        """Generate a Seatbelt profile and return wrapped command."""
        # Clean up any previously generated profile to prevent temp file leaks
        self.cleanup()

        profile_content = self._generate_profile(profile)

        # Write profile to a temp file that persists for the process lifetime
        fd, path = tempfile.mkstemp(suffix=".sb", prefix="gatekit_sandbox_")
        try:
            os.write(fd, profile_content.encode("utf-8"))
        finally:
            os.close(fd)
        self._profile_path = Path(path)

        return ["sandbox-exec", "-f", str(self._profile_path), "--"] + command

    def availability_diagnostic(self) -> str:
        return (
            "sandbox-exec is not found on this system. "
            "It is included with macOS but may not be available in all environments."
        )

    def cleanup(self) -> None:
        """Remove the temporary Seatbelt profile file."""
        if self._profile_path and self._profile_path.exists():
            try:
                self._profile_path.unlink()
            except OSError:
                pass
            self._profile_path = None

    def _generate_profile(self, profile: SandboxProfile) -> str:
        """Generate a Seatbelt (.sb) profile from a SandboxProfile.

        Strategy: deny-all for home directory, allowlist specific paths.

        In Seatbelt, allow rules always beat deny rules for the same path.
        So instead of "allow parent + deny child", we deny the entire home
        directory and then only allow the specific subdirectories needed.
        Sensitive paths are protected by simply not being allowed.
        """
        home_dir = str(Path.home())
        escaped_home = _escape_seatbelt_string(home_dir)

        lines = [
            "(version 1)",
            "(allow default)",
            # Deny all file writes by default
            "(deny file-write*)",
            # Deny all reads in the home directory — this is the core of the
            # deny-all model. Everything in ~ is blocked unless explicitly allowed.
            f'(deny file-read* (subpath "{escaped_home}"))',
        ]

        # Allow system paths for reading (binaries, libraries, certs, etc.)
        for sys_path in _MACOS_SYSTEM_READ_PATHS:
            escaped = _escape_seatbelt_string(sys_path)
            lines.append(f'(allow file-read* (subpath "{escaped}"))')

        # Allow temp directories for read+write
        for tmp_path in _MACOS_TEMP_RW_PATHS:
            escaped = _escape_seatbelt_string(tmp_path)
            lines.append(f'(allow file-read* (subpath "{escaped}"))')
            lines.append(f'(allow file-write* (subpath "{escaped}"))')

        # Allow read-only paths (command runtime — venvs, scripts, etc.)
        for ro_path in profile.read_only_paths:
            escaped = _escape_seatbelt_string(str(ro_path.expanduser().resolve()))
            lines.append(f'(allow file-read* (subpath "{escaped}"))')

        # Warn about deny paths that overlap with allowed rw/ro paths.
        # In Seatbelt, allow-wins means we can't protect sensitive dirs
        # that are inside an explicitly-allowed parent.
        deny_resolved = [p.expanduser().resolve() for p in profile.deny_paths]
        all_allowed = list(profile.read_write_paths) + list(profile.read_only_paths)
        for allowed_path in all_allowed:
            resolved_allowed = allowed_path.expanduser().resolve()
            for deny_path in deny_resolved:
                if _path_is_child_of(deny_path, resolved_allowed):
                    logger.warning(
                        "Sensitive path %s is inside allowed path %s — "
                        "Seatbelt cannot protect it (allow-wins semantics). "
                        "Consider using a more specific path in sandbox.paths.",
                        deny_path,
                        resolved_allowed,
                    )

        # Allow read-write paths (cache dirs + user-configured paths)
        for rw_path in profile.read_write_paths:
            escaped = _escape_seatbelt_string(str(rw_path.expanduser().resolve()))
            lines.append(f'(allow file-read* (subpath "{escaped}"))')
            lines.append(f'(allow file-write* (subpath "{escaped}"))')

        # Deny network if requested
        if not profile.allow_network:
            lines.append("(deny network-outbound)")
            # Allow Unix domain sockets (needed for system IPC)
            lines.append("(allow network-outbound (local unix))")

        return "\n".join(lines) + "\n"
