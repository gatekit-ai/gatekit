"""Filesystem utilities for safe file operations."""

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write text to a file atomically using temp file + rename.

    This prevents corruption if the process crashes during write. The file is
    written to a temporary file in the same directory, fsynced to ensure data
    is on disk, then atomically renamed to the target path.

    On POSIX systems, rename is atomic. On Windows, this may not be fully atomic
    if the target file exists, but it's still safer than direct writes.

    Args:
        path: Target file path (will be created or overwritten)
        content: Text content to write (UTF-8 encoding)

    Raises:
        OSError: If write or rename fails
        PermissionError: If lacking permissions for directory or file
    """
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory as target (ensures same filesystem)
    temp_fd = None
    temp_path = None

    try:
        temp_fd, temp_path_str = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_path_str)

        # Write content through file descriptor for proper fsync
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # Mark fd as closed (handled by os.fdopen context manager)
        temp_fd = None

        # Atomic rename (on POSIX systems)
        temp_path.replace(path)

        # Success - clear temp_path so finally block doesn't delete it
        temp_path = None

    finally:
        # Clean up on failure
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass

        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
