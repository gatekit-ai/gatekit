"""Configuration error classes for user-friendly error reporting."""

from typing import List, Optional
from pathlib import Path


class ConfigError(Exception):
    """Minimal structured configuration error for user-friendly display."""

    def __init__(
        self,
        message: str,
        error_type: str,
        file_path: Optional[Path] = None,
        line_number: Optional[int] = None,
        field_path: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        line_snippet: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_type = (
            error_type  # 'yaml_syntax', 'missing_plugin', 'validation_error'
        )
        self.error_code = f"CFG_{error_type.upper()}"  # Future CLI/analytics support
        self.file_path = file_path
        self.line_number = line_number  # 1-based line numbers (editor standard)
        self.field_path = field_path  # "plugins.auditing._global[2].handler"
        self.line_snippet = (
            line_snippet  # Actual line content for YAML errors, None otherwise
        )

        # Filter out empty suggestions to prevent blank bullets
        self.suggestions = [s for s in (suggestions or []) if s][
            :3
        ]  # Max 3, no empties

        # V1: Hardcode recovery actions - only missing_plugin can be safely ignored
        self.can_edit = True
        self.can_ignore = (
            error_type == "missing_plugin"
        )  # Only plugins, not validation errors

    def to_dict(self) -> dict:
        """Convert ConfigError to dictionary for serialization/logging.

        Returns:
            Dictionary containing all non-None error fields
        """
        result = {
            "message": self.message,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "can_edit": self.can_edit,
            "can_ignore": self.can_ignore,
        }

        # Include optional fields only if they have values
        if self.file_path is not None:
            result["file_path"] = str(self.file_path)
        if self.line_number is not None:
            result["line_number"] = self.line_number
        if self.field_path is not None:
            result["field_path"] = self.field_path
        if self.line_snippet is not None:
            result["line_snippet"] = self.line_snippet
        if self.suggestions:
            result["suggestions"] = self.suggestions.copy()

        return result

    def __repr__(self) -> str:
        """Debug-friendly representation."""
        return f"ConfigError(type={self.error_type}, message='{self.message}', field_path={self.field_path})"


class ConfigWriteError(ConfigError):
    """Raised when configuration cannot be written to disk."""

    def __init__(self, path: Path, reason: str, cause: Optional[Exception] = None):
        """Initialize ConfigWriteError.

        Args:
            path: Path where config write was attempted
            reason: Human-readable reason for failure
            cause: Original exception that caused the failure (preserved as __cause__)
        """
        self.path = path
        self.cause = cause
        super().__init__(
            f"Failed to write config to {path}: {reason}",
            error_type="write_error",
        )
