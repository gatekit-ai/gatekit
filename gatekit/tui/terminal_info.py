"""Terminal detection utilities for Gatekit TUI."""

import os
from typing import Optional


class TerminalInfo:
    """Information about the current terminal environment."""

    def __init__(self):
        """Initialize terminal information."""
        self._term_program = os.environ.get("TERM_PROGRAM")
        self._term_program_version = os.environ.get("TERM_PROGRAM_VERSION")
        self._term = os.environ.get("TERM")
        self._term_session_id = os.environ.get("TERM_SESSION_ID")

    @property
    def is_mac_terminal(self) -> bool:
        """Check if running in standard Mac Terminal.app."""
        return self._term_program == "Apple_Terminal"

    @property
    def is_iterm2(self) -> bool:
        """Check if running in iTerm2."""
        return self._term_program == "iTerm.app"

    @property
    def is_kitty(self) -> bool:
        """Check if running in Kitty terminal."""
        return self._term_program == "kitty"

    @property
    def is_wezterm(self) -> bool:
        """Check if running in WezTerm."""
        return self._term_program == "WezTerm"

    @property
    def is_alacritty(self) -> bool:
        """Check if running in Alacritty terminal."""
        return self._term_program == "alacritty"

    @property
    def is_hyper(self) -> bool:
        """Check if running in Hyper terminal."""
        return self._term_program == "Hyper"

    @property
    def terminal_name(self) -> Optional[str]:
        """Get the terminal program name."""
        return self._term_program

    @property
    def terminal_version(self) -> Optional[str]:
        """Get the terminal program version."""
        return self._term_program_version

    @property
    def session_id(self) -> Optional[str]:
        """Get the terminal session ID (if available)."""
        return self._term_session_id

    def get_terminal_display_name(self) -> str:
        """Get a user-friendly display name for the terminal."""
        if self.is_mac_terminal:
            version = f" {self.terminal_version}" if self.terminal_version else ""
            return f"Terminal.app{version}"
        elif self.is_iterm2:
            return "iTerm2"
        elif self.is_kitty:
            return "Kitty"
        elif self.is_wezterm:
            return "WezTerm"
        elif self.is_alacritty:
            return "Alacritty"
        elif self.is_hyper:
            return "Hyper"
        elif self.terminal_name:
            version = f" {self.terminal_version}" if self.terminal_version else ""
            return f"{self.terminal_name}{version}"
        elif self._term:
            return f"Terminal ({self._term})"
        else:
            return "Unknown Terminal"

    def supports_enhanced_features(self) -> bool:
        """Check if the terminal supports enhanced TUI features.

        Based on Textual documentation, some terminals have better support
        for advanced features like pixel-precise mouse coordinates.
        """
        # Terminals known to support advanced features
        return self.is_kitty or self.is_wezterm or self.is_iterm2

    def get_compatibility_notes(self) -> Optional[str]:
        """Get compatibility notes for the current terminal."""
        if self.is_mac_terminal:
            return "Standard Mac Terminal - basic feature set, reliable for most operations"
        elif self.is_iterm2:
            return "iTerm2 - enhanced features supported, excellent compatibility"
        elif self.is_kitty:
            return "Kitty - advanced features supported, excellent performance"
        elif self.is_wezterm:
            return "WezTerm - modern terminal with good feature support"
        elif self.is_alacritty:
            return "Alacritty - GPU-accelerated, good performance"
        elif self.is_hyper:
            return "Hyper - web-based terminal, may have some limitations"
        else:
            return None


# Global instance for easy access
terminal_info = TerminalInfo()
