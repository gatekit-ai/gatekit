"""OS-native process sandboxing for MCP servers.

Provides sandbox wrapping for stdio-transport MCP server processes using
OS-native mechanisms: Seatbelt (sandbox-exec) on macOS, bubblewrap (bwrap)
on Linux.

Security model: home directory denied by default with explicit allowlist.
- Home directory is denied; system paths outside home remain readable
- /tmp and cache directories (~/.npm, ~/.cache, ~/.local) are read-write
- User-configured ``paths`` grant read-write access to specific directories
- Sensitive credential directories are always denied (on Linux; see macOS caveat below)
- On macOS, Seatbelt's allow-wins semantics mean sensitive subdirectories
  cannot be individually protected if a parent directory is explicitly allowed
"""

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from .backends.base import SandboxBackend, SandboxProfile
from .detection import get_sandbox_backend, is_sandbox_available, get_sandbox_backend_or_raise
from .errors import SandboxUnavailableError, SandboxConfigError

logger = logging.getLogger(__name__)

# Sensitive paths hidden from sandboxed processes.
# These are common credential and secret stores that MCP servers should
# never need access to.  The list is intentionally broad — a false positive
# (denying a path a server legitimately needs) is far less costly than
# leaking credentials.
_DENY_PATHS = [
    # SSH keys and configuration
    Path("~/.ssh"),
    # GPG keys
    Path("~/.gnupg"),
    # Cloud provider credentials
    Path("~/.aws"),
    Path("~/.azure"),
    Path("~/.config/gcloud"),
    # Container and orchestration credentials
    Path("~/.kube"),
    Path("~/.docker"),
    # Git credentials
    Path("~/.git-credentials"),
    # Infrastructure and secrets management
    Path("~/.vault-token"),
    Path("~/.terraform.d"),
]

# Paths that need read-write access for package managers (npx, pip, uv, etc.)
# Without these, most npm/pip-based MCP servers won't start.
_CACHE_RW_PATHS = [
    Path("~/.npm"),
    Path("~/.cache"),
    Path("~/.local"),
]


def _is_under(child: Path, parent: Path) -> bool:
    """Check if child is a descendant of parent."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _infer_command_read_paths(command: List[str]) -> List[Path]:
    """Auto-detect paths the command needs readable to start.

    This ensures the sandbox can actually execute the given command.
    Without it, any server whose runtime lives under ~ (Python venvs,
    nvm installs, pyenv, etc.) would fail immediately because the
    home-directory deny blocks reading the binary and script.

    This is NOT workspace inference — it only grants read access to
    the command's own executable tree and script files.
    """
    read_paths: List[Path] = []
    home = Path.home()

    # Resolve the command binary
    binary = shutil.which(command[0])
    if binary:
        binary_path = Path(binary)
        if _is_under(binary_path, home):
            # If binary is in a bin/ directory, the runtime root is one
            # level up (covers Python venvs, nvm installs, etc.)
            binary_dir = binary_path.parent
            if binary_dir.name == "bin":
                read_paths.append(binary_dir.parent)
            else:
                read_paths.append(binary_dir)

    # Script/file arguments need to be readable
    for arg in command[1:]:
        p = Path(os.path.expanduser(arg))
        if p.is_file() and _is_under(p, home):
            read_paths.append(p.parent)

    return read_paths


def resolve_and_wrap(
    command: List[str],
    *,
    enabled: bool = False,
    paths: Optional[List[str]] = None,
    network: bool = True,
) -> Tuple[List[str], Optional[SandboxBackend]]:
    """Wrap a command with sandbox if enabled.  Main integration point.

    Args:
        command: The MCP server command to (optionally) wrap.
        enabled: Whether sandboxing is enabled.
        paths: Read-write paths from config (user workspace directories).
        network: Whether to allow outbound network access.

    Returns:
        (wrapped_command, backend) — backend is non-None when sandboxing is
        active and must have its ``cleanup()`` called on disconnect.

    Raises:
        SandboxUnavailableError: If sandbox is enabled but no backend available.
    """
    if not enabled:
        return command, None

    backend = get_sandbox_backend_or_raise()

    # Build the profile
    rw_paths: List[Path] = []
    ro_paths: List[Path] = []
    deny_paths: List[Path] = []

    # Auto-detect command runtime paths (read-only)
    ro_paths.extend(_infer_command_read_paths(command))

    # The process needs to read its cwd (many libraries call os.getcwd() at
    # import time).  Grant read-only access if cwd is under home.
    try:
        cwd = Path.cwd()
        if _is_under(cwd, Path.home()):
            ro_paths.append(cwd)
    except OSError:
        pass

    # Cache dirs (package manager caches — only include if they exist)
    for p in _CACHE_RW_PATHS:
        expanded = p.expanduser()
        if expanded.exists():
            rw_paths.append(expanded)

    # Sensitive credential dirs (always denied, even if they don't exist yet)
    for p in _DENY_PATHS:
        expanded = p.expanduser()
        deny_paths.append(expanded)

    # User-configured paths
    if paths:
        for p_str in paths:
            rw_paths.append(Path(os.path.expanduser(p_str)).resolve())

    profile = SandboxProfile(
        read_write_paths=rw_paths,
        read_only_paths=ro_paths,
        deny_paths=deny_paths,
        allow_network=network,
    )

    wrapped = backend.wrap_command(command, profile)

    logger.info(
        "Sandbox wrapping applied",
        extra={
            "backend": backend.name,
            "ro_paths": [str(p) for p in ro_paths],
            "rw_paths": [str(p) for p in rw_paths],
            "deny_paths": [str(p) for p in deny_paths],
            "allow_network": network,
        },
    )

    return wrapped, backend


__all__ = [
    "SandboxBackend",
    "SandboxProfile",
    "get_sandbox_backend",
    "is_sandbox_available",
    "resolve_and_wrap",
    "SandboxUnavailableError",
    "SandboxConfigError",
]
