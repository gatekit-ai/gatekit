"""Recent files management for Gatekit TUI.

Tracks recently opened configuration files with timestamps and provides
secure, cross-platform storage.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from .platform_paths import get_user_state_dir


def humanize_timestamp(iso_timestamp: str) -> str:
    """Convert ISO timestamp to human-readable relative time.

    Returns "unknown" if timestamp is malformed (defensive against corrupted state).

    Args:
        iso_timestamp: ISO 8601 timestamp string (e.g., "2025-10-11T14:30:22Z")

    Returns:
        Human-readable relative time string
    """
    try:
        then = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        delta = now - then

        seconds = delta.total_seconds()
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 172800:  # < 2 days
            return "yesterday"
        elif seconds < 604800:  # < 7 days
            days = int(seconds / 86400)
            return f"{days} days ago"
        elif seconds < 2419200:  # < 28 days
            weeks = int(seconds / 604800)
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            return then.strftime("%b %d, %Y")
    except (ValueError, OSError):
        # Corrupted timestamp - don't crash the UI
        return "unknown"


class RecentFiles:
    """Manages recently opened configuration files.

    Features:
    - Tracks up to N most recent files
    - Stores in platform-appropriate location
    - Atomic file writes for reliability
    - Secure permissions (0600 on Unix)
    - Graceful handling of corrupted state
    """

    def __init__(self, max_items: int = 10):
        """Initialize RecentFiles manager.

        Args:
            max_items: Maximum number of recent files to track
        """
        self.max_items = max_items
        state_dir = get_user_state_dir('gatekit')
        self.recent_file = state_dir / 'recent.json'

    def add(self, file_path: Path) -> None:
        """Add or update a file in the recent files list.

        If the file already exists, updates its timestamp and moves it to the front.

        Args:
            file_path: Path to the configuration file
        """
        file_path = file_path.resolve()
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Load existing recent files
        recent = self._load()

        # Remove existing entry if present
        recent = [r for r in recent if Path(r['path']) != file_path]

        # Add new entry at the front
        recent.insert(0, {
            'path': str(file_path),
            'last_opened': timestamp,
            'display_name': file_path.name
        })

        # Keep only max_items most recent
        recent = recent[:self.max_items]

        # Save atomically
        self._save(recent)

    def get_all(self) -> List[Dict[str, Any]]:
        """Get all recent files, filtering out files that no longer exist.

        Returns:
            List of recent file dictionaries with 'path', 'last_opened', and 'display_name'
        """
        recent = self._load()

        # Filter out files that no longer exist
        return [r for r in recent if Path(r['path']).exists()]

    def remove(self, file_path: Path) -> None:
        """Remove a file from the recent files list.

        Args:
            file_path: Path to the file to remove
        """
        file_path = file_path.resolve()
        recent = self._load()

        # Remove the file
        recent = [r for r in recent if Path(r['path']) != file_path]

        self._save(recent)

    def clear(self) -> None:
        """Clear all recent files."""
        self._save([])

    def _load(self) -> List[Dict[str, Any]]:
        """Load recent files from disk.

        Returns:
            List of recent file dictionaries, or empty list if file doesn't exist or is corrupted
        """
        if not self.recent_file.exists():
            return []

        try:
            data = json.loads(self.recent_file.read_text())
            recent_files = data.get('recent_files', [])

            # Validate that recent_files is a list
            if not isinstance(recent_files, list):
                return []

            # Validate each entry is a dict with required keys
            validated = []
            for entry in recent_files:
                # Entry must be a dict
                if not isinstance(entry, dict):
                    continue

                # Entry must have 'path' key
                if 'path' not in entry:
                    continue

                # 'path' must be a string
                if not isinstance(entry['path'], str):
                    continue

                # Repair/validate display_name (derive from path if missing or invalid)
                if 'display_name' not in entry or not isinstance(entry['display_name'], str):
                    entry['display_name'] = Path(entry['path']).name

                # Repair/validate last_opened (empty string if missing or invalid)
                # humanize_timestamp() will handle empty string gracefully (returns "unknown")
                if 'last_opened' not in entry or not isinstance(entry['last_opened'], str):
                    entry['last_opened'] = ''

                # Entry is valid and repaired
                validated.append(entry)

            return validated

        except (json.JSONDecodeError, UnicodeDecodeError, OSError, AttributeError, TypeError):
            # Corrupted or unreadable - return empty list
            # - json.JSONDecodeError: invalid JSON syntax
            # - UnicodeDecodeError: invalid UTF-8 encoding
            # - OSError: file read errors
            # - AttributeError: data is not a dict (e.g., list, None)
            # - TypeError: data.get() called on incompatible type
            return []

    def _save(self, recent: List[Dict[str, Any]]) -> None:
        """Save recent files list atomically with secure permissions.

        Args:
            recent: List of recent file dictionaries to save
        """
        data = {
            "version": 1,
            "max_items": self.max_items,
            "recent_files": recent
        }
        json_data = json.dumps(data, indent=2)

        # Write to temp file with secure permissions from the start
        temp_file = self.recent_file.with_suffix('.tmp')

        # Create with 0600 (rw-------) to avoid world-readable window
        # Even with restrictive umask, be explicit about permissions
        try:
            # Unix: open with explicit mode
            fd = os.open(temp_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, json_data.encode('utf-8'))
            finally:
                # Always close the file descriptor, even if write fails
                os.close(fd)
        except (OSError, AttributeError):
            # Windows or permission error: fall back to write_text + chmod
            temp_file.write_text(json_data)
            try:
                temp_file.chmod(0o600)
            except (OSError, NotImplementedError):
                pass

        # Atomic replace (works on POSIX and Windows)
        temp_file.replace(self.recent_file)
