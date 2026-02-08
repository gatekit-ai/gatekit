"""Linux bubblewrap (bwrap) sandbox backend.

Security model: home-directory-denied default with explicit allowlist.

Instead of mounting the entire filesystem read-only (--ro-bind / /),
this backend selectively mounts only what the server needs:
- System paths as read-only (binaries, libraries, runtimes)
- /tmp as fresh tmpfs
- Cache dirs and user paths as read-write
- Sensitive paths overlaid with empty tmpfs (extra safety)
- Everything else is simply not mounted (invisible to the process)
"""

import logging
import shutil
import subprocess
from pathlib import Path
from typing import List

from .base import SandboxBackend, SandboxProfile

logger = logging.getLogger(__name__)

# Linux system paths that are always mounted read-only.
# Processes need these to locate binaries, libraries, certificates, etc.
_LINUX_SYSTEM_RO_PATHS = [
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/etc",
    "/opt",
    "/nix",  # Nix store (if present)
]


class BubblewrapBackend(SandboxBackend):
    """Sandbox backend using bubblewrap (bwrap) on Linux.

    Mount strategy (deny-all with allowlist):
      1. Mount system paths as read-only
      2. Mount /proc, /dev
      3. Fresh tmpfs for /tmp
      4. Bind-mount cache dirs and user paths as read-write
      5. Overlay sensitive paths with empty tmpfs (extra safety)
      6. Everything not mounted is invisible to the process
    """

    @property
    def name(self) -> str:
        return "bubblewrap"

    def is_available(self) -> bool:
        """Check if bwrap is installed AND functional.

        On Ubuntu 23.10+ AppArmor may restrict unprivileged user namespaces,
        so we attempt an actual invocation rather than just checking ``which``.
        """
        if not shutil.which("bwrap"):
            return False
        try:
            result = subprocess.run(
                ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
                 "--ro-bind", "/bin", "/bin", "--symlink", "/usr/lib64", "/lib64",
                 "--proc", "/proc", "--dev", "/dev", "/bin/true"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def wrap_command(
        self, command: List[str], profile: SandboxProfile
    ) -> List[str]:
        """Build bwrap argument list from a SandboxProfile.

        Mount ordering matters: bwrap processes arguments sequentially and
        later mounts on overlapping paths override earlier ones.  We apply
        deny mounts (--tmpfs overlays) last so they cannot be re-exposed
        by a broader --bind of a parent directory.
        """
        args: List[str] = ["bwrap"]

        # Mount system paths as read-only
        for sys_path in _LINUX_SYSTEM_RO_PATHS:
            path = Path(sys_path)
            if path.exists():
                args += ["--ro-bind", sys_path, sys_path]

        # Mount /proc and /dev
        args += ["--proc", "/proc"]
        args += ["--dev", "/dev"]

        # Mount a fresh /tmp (writable tmpfs)
        args += ["--tmpfs", "/tmp"]

        # Read-only bind mounts (command runtime — venvs, scripts, etc.)
        for ro_path in profile.read_only_paths:
            resolved = str(ro_path.expanduser().resolve())
            if Path(resolved).exists():
                args += ["--ro-bind", resolved, resolved]
            else:
                logger.warning(
                    "Sandbox read-only path %s does not exist — skipping mount.",
                    resolved,
                )

        # Read-write bind mounts (cache dirs + user-configured paths)
        for rw_path in profile.read_write_paths:
            resolved = str(rw_path.expanduser().resolve())
            if Path(resolved).exists():
                args += ["--bind", resolved, resolved]
            else:
                logger.warning(
                    "Sandbox path %s does not exist — skipping mount. "
                    "The sandboxed server will not be able to access this path.",
                    resolved,
                )

        # Overlay sensitive paths with empty tmpfs to hide them.
        # Applied AFTER all bind mounts so a parent --bind can't re-expose them.
        # For paths that don't exist on the host, use --dir to create the mount
        # point first — this prevents creation of the real directory when a
        # parent path is writable (e.g., ~ is RW and ~/.ssh doesn't exist yet).
        for deny_path in profile.deny_paths:
            resolved_path = deny_path.expanduser().resolve()
            resolved_str = str(resolved_path)
            if resolved_path.is_dir():
                args += ["--tmpfs", resolved_str]
            elif resolved_path.is_file():
                # Replace the file with /dev/null so reads return empty
                # and the original contents are hidden.
                args += ["--ro-bind", "/dev/null", resolved_str]
            elif not resolved_path.exists():
                # Create an empty dir inside the sandbox, then overlay with
                # tmpfs so the path exists but is empty and not writable to
                # the real filesystem.
                args += ["--dir", resolved_str, "--tmpfs", resolved_str]
            else:
                logger.debug(
                    "Skipping deny path %s (exists but is not a regular file or directory)",
                    resolved_path,
                )

        # Network isolation
        if not profile.allow_network:
            args.append("--unshare-net")

        # Safety: kill sandboxed process when parent dies
        args.append("--die-with-parent")

        # Append the actual command
        args += ["--"] + command

        return args

    def availability_diagnostic(self) -> str:
        if not shutil.which("bwrap"):
            return (
                "bubblewrap (bwrap) is not installed. "
                "Install it with your package manager:\n"
                "  Debian/Ubuntu: sudo apt install bubblewrap\n"
                "  Fedora:        sudo dnf install bubblewrap\n"
                "  Arch Linux:    sudo pacman -S bubblewrap"
            )
        return (
            "bubblewrap is installed but cannot create user namespaces. "
            "This may be due to AppArmor restrictions on Ubuntu 23.10+. "
            "See: https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces"
        )
