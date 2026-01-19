"""Error handling utilities for guided setup.

Provides error models, error message formatting, and editor opening with graceful error handling.
"""

import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .models import DetectedClient
from . import client_registry


@dataclass
class DetectionResult:
    """Result of client detection with error tracking.

    Attributes:
        clients: List of detected clients
        detection_errors: Errors that occurred during detection (non-fatal)
    """

    clients: List[DetectedClient] = field(default_factory=list)
    detection_errors: List[str] = field(default_factory=list)

    def has_clients(self) -> bool:
        """Check if any clients were detected."""
        return len(self.clients) > 0

    def is_empty(self) -> bool:
        """Check if no clients were detected."""
        return len(self.clients) == 0

    @property
    def client_count(self) -> int:
        """Get number of detected clients."""
        return len(self.clients)

    def has_errors(self) -> bool:
        """Check if any detection errors occurred."""
        return len(self.detection_errors) > 0

    def get_clients_with_servers(self) -> List[DetectedClient]:
        """Get only clients that have at least one server configured."""
        return [c for c in self.clients if c.has_servers()]


def get_no_clients_message() -> str:
    """Get message to display when no MCP clients are detected.

    Returns:
        User-friendly message explaining that no clients were found
    """
    return (
        "No MCP clients detected on your system.\n\n"
        "Guided Setup can detect and migrate configurations from:\n"
        f"  • {', '.join(client_registry.get_supported_client_names())}\n\n"
        "You can create a blank configuration instead."
    )


def format_parse_error_message(client: DetectedClient) -> str:
    """Format parse errors for a client into user-friendly message.

    Args:
        client: DetectedClient with parse errors

    Returns:
        Formatted error message
    """
    client_name = client.display_name()
    error_count = len(client.parse_errors)

    if error_count == 0:
        return f"{client_name}: No errors"

    if error_count == 1:
        return f"{client_name}: {client.parse_errors[0]}"

    # Multiple errors
    message = f"{client_name}: {error_count} errors encountered:\n"
    for i, error in enumerate(client.parse_errors, 1):
        message += f"  {i}. {error}\n"

    return message.rstrip()


class EditorOpener:
    """Handles opening files in the system's default editor with error handling."""

    def open_file(self, file_path: Path) -> Tuple[bool, Optional[str]]:
        """Open file in default text editor.

        For shell scripts and other executable files, forces text mode to prevent execution.
        For other files (JSON, YAML), respects file associations.

        Args:
            file_path: Path to file to open

        Returns:
            Tuple of (success, error_message):
                - success: True if file was opened successfully
                - error_message: Error description if failed, None if successful
        """
        system = platform.system()

        # Check if file exists first to give a clear error message
        if not file_path.exists():
            return False, f"File not found: {file_path}"

        try:
            if system == "Darwin":  # macOS
                # Use -t (text mode) for executable extensions to prevent execution
                # This forces opening in default text editor instead of running the script
                executable_extensions = {".sh", ".bash", ".zsh", ".command"}
                if file_path.suffix.lower() in executable_extensions:
                    subprocess.run(["open", "-t", str(file_path)], check=True)
                else:
                    subprocess.run(["open", str(file_path)], check=True)
            elif system == "Linux":
                subprocess.run(["xdg-open", str(file_path)], check=True)
            elif system == "Windows":
                os.startfile(str(file_path))  # type: ignore[attr-defined]
            else:
                return False, f"Unsupported platform: {system}"

            return True, None

        except FileNotFoundError:
            return False, f"Editor not found. Please open the file manually: {file_path}"

        except PermissionError:
            return False, f"Permission denied. File may be locked: {file_path}"

        except subprocess.CalledProcessError as e:
            return False, f"Failed to open editor: {e}"

        except Exception as e:
            return False, f"Unexpected error opening file: {e}"
