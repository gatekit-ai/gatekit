"""Cross-platform clipboard utilities for Gatekit TUI.

Textual's built-in copy_to_clipboard uses OSC 52 escape sequences which
don't work in all terminals (notably macOS Terminal.app). This module
provides a more robust clipboard implementation using system utilities.

For SSH sessions, OSC 52 is used instead since platform commands would
copy to the remote machine's clipboard, not the local one.
"""

import base64
import os
import platform
import subprocess
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from textual.app import App


def is_ssh_session() -> bool:
    """Detect if we're running in an SSH session.

    This is useful for callers who want to show different clipboard
    notifications based on whether OSC 52 was used (which may not work
    in all terminals).
    """
    # Check common SSH environment variables
    return bool(
        os.environ.get("SSH_CLIENT")
        or os.environ.get("SSH_TTY")
        or os.environ.get("SSH_CONNECTION")
    )


# SSH clipboard workaround message for terminals that don't support OSC 52
SSH_CLIPBOARD_HINT = (
    "Mac: Hold Fn (Terminal) or ⌥ (iTerm2) while selecting, then Cmd+C. "
    "Windows/Linux: Shift while selecting, Ctrl+C"
)

# Longer timeout for SSH clipboard toasts (default is ~5s)
SSH_CLIPBOARD_TOAST_TIMEOUT = 10.0


def _is_tmux() -> bool:
    """Return True if running inside tmux."""

    return bool(os.environ.get("TMUX"))


def _is_screen() -> bool:
    """Return True if running inside GNU screen or a derivative."""

    term = os.environ.get("TERM", "")
    return term.startswith("screen") or bool(os.environ.get("STY"))


def _build_osc52_sequence(text: str) -> str:
    """Build an OSC 52 sequence that survives tmux/screen pass-through.

    Uses ST (String Terminator, \\x1b\\\\) instead of BEL (\\a) for better
    terminal compatibility. Some terminals (notably Windows Terminal) have
    issues with BEL-terminated OSC sequences that can drop the last character.
    """
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    # Use ST (\x1b\\) instead of BEL (\a) for better terminal compatibility
    osc_sequence = f"\x1b]52;c;{payload}\x1b\\"

    if _is_tmux():
        # Wrap sequence so tmux forwards it to the outer terminal
        # The inner sequence uses ST, outer wrapper also ends with ST
        return f"\x1bPtmux;\x1b{osc_sequence}\x1b\\"

    if _is_screen():
        # GNU screen requires a DCS wrapper without the tmux prefix
        return f"\x1bP\x1b{osc_sequence}\x1b\\"

    return osc_sequence


def _copy_via_osc52(app: "App", text: str) -> None:
    """Copy using OSC 52, accounting for terminal multiplexers."""
    driver = getattr(app, "_driver", None)
    if driver is None:
        raise RuntimeError("Clipboard driver unavailable")

    sequence = _build_osc52_sequence(text)
    driver.write(sequence)

    # Ensure sequence is fully sent to terminal
    if hasattr(driver, "flush"):
        driver.flush()

    # Mirror Textual's behavior so Input widgets know the clipboard contents
    try:
        app._clipboard = text  # noqa: SLF001
    except Exception:
        pass


def copy_to_clipboard(app: "App", text: str) -> Tuple[bool, Optional[str]]:
    """Copy text to clipboard using system utilities with Textual fallback.

    For SSH sessions, uses OSC 52 escape sequences (via Textual) to copy
    to the local clipboard. For local sessions, uses platform-specific
    commands which are more reliable on some terminals (e.g., macOS Terminal.app).

    Args:
        app: The Textual App instance (used for fallback and notifications)
        text: Text to copy to clipboard

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    # For SSH sessions, use OSC 52 (Textual's method) to copy to LOCAL clipboard
    # Platform commands would copy to the remote machine's clipboard
    if is_ssh_session():
        try:
            _copy_via_osc52(app, text)
            return True, None
        except Exception as e:
            # Try Textual's built-in helper as a best-effort fallback
            try:
                app.copy_to_clipboard(text)
                return True, None
            except Exception as fallback_error:
                return False, f"Clipboard error (OSC 52): {fallback_error or e}"

    # For local sessions, try platform-specific commands first
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            subprocess.run(
                ["pbcopy"],
                input=text.encode(),
                check=True,
                timeout=5,
            )
            return True, None

        elif system == "Linux":
            # Try xclip first, then xsel
            for cmd in [
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]:
                try:
                    subprocess.run(
                        cmd,
                        input=text.encode(),
                        check=True,
                        timeout=5,
                    )
                    return True, None
                except FileNotFoundError:
                    continue
            # No clipboard utility found
            raise FileNotFoundError("No clipboard utility found (tried xclip, xsel)")

        elif system == "Windows":
            # Use clip.exe with UTF-8 encoding
            # Add a trailing newline to prevent the last character from being dropped
            # (clip.exe has a known bug where it can truncate the last char)
            subprocess.run(
                ["clip"],
                input=(text + "\n").encode("utf-8"),
                check=True,
                timeout=5,
            )
            return True, None

        else:
            # Unknown system - try Textual's method
            app.copy_to_clipboard(text)
            return True, None

    except FileNotFoundError as e:
        # Clipboard utility not found - fall back to Textual's built-in method
        try:
            app.copy_to_clipboard(text)
            return True, None
        except Exception as fallback_error:
            return False, f"Clipboard not available: {e}. Fallback failed: {fallback_error}"

    except subprocess.CalledProcessError as e:
        # Clipboard command failed
        try:
            app.copy_to_clipboard(text)
            return True, None
        except Exception as fallback_error:
            return False, f"Clipboard command failed: {e}. Fallback failed: {fallback_error}"

    except subprocess.TimeoutExpired:
        return False, "Clipboard operation timed out"

    except Exception as e:
        return False, f"Clipboard error: {e}"
