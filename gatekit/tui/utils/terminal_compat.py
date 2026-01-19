"""Terminal compatibility detection utilities.

Detects terminal capabilities to enable fallback rendering for terminals
with limited Unicode support (e.g., Windows cmd.exe and PowerShell with
default fonts that can't render Unicode block elements).

Also detects macOS Terminal.app which has rendering issues with fractional
block characters (▊▎▔▁) used in 'tall' borders - they show gaps or don't
connect properly. Box-drawing characters (│) in 'solid' borders render correctly.

When running over SSH, we can't detect the client terminal's capabilities
(TERM_PROGRAM isn't forwarded, and we can't query the remote terminal), so
we use conservative defaults (solid borders) to ensure compatibility with
any client terminal.
"""

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.scrollbar import ScrollBarRender


def is_ssh_session() -> bool:
    """Detect if running in an SSH session.

    SSH sets these environment variables on the remote server, making this
    a reliable way to detect SSH sessions. When over SSH, we can't detect
    the client terminal's capabilities, so we use conservative defaults.

    Note: tmux/screen sessions started under SSH will retain these variables
    even if later attached locally, but this is acceptable for our use case.

    Returns:
        True if running in an SSH session, False otherwise.
    """
    return bool(
        os.environ.get("SSH_CLIENT")
        or os.environ.get("SSH_TTY")
        or os.environ.get("SSH_CONNECTION")
    )


def lacks_enhanced_keyboard_protocol() -> bool:
    """Detect if the terminal lacks support for enhanced keyboard protocols.

    Traditional VT100/ANSI terminals cannot distinguish Ctrl+S from Ctrl+Shift+S
    because both generate the same control character (0x13). Modern terminals
    support enhanced protocols (like Kitty keyboard protocol) that encode
    modifier keys properly.

    Returns True when the terminal cannot distinguish Ctrl+letter from
    Ctrl+Shift+letter combinations:
    - macOS Terminal.app (no Kitty/xterm modifyOtherKeys support)
    - SSH sessions (can't detect client terminal capabilities)
    - Windows legacy terminals (cmd.exe, PowerShell without VT)

    Modern terminals that DO support enhanced keyboard protocols:
    - iTerm2 (TERM_PROGRAM=iTerm.app)
    - Ghostty (TERM_PROGRAM=ghostty)
    - Kitty (TERM_PROGRAM=kitty)
    - WezTerm (TERM_PROGRAM=WezTerm)
    - VS Code terminal (TERM_PROGRAM=vscode)
    - Alacritty (partial support)

    Returns:
        True if terminal lacks enhanced keyboard protocol support.
    """
    # SSH sessions: can't detect client terminal capabilities
    if is_ssh_session():
        return True

    # Windows legacy terminals
    if sys.platform == "win32":
        from rich.console import Console
        console = Console()
        if console.legacy_windows:
            return True

    # Check TERM_PROGRAM for known terminals
    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    # Terminals known to LACK enhanced keyboard protocol
    if term_program == "apple_terminal":
        return True

    # Default: assume modern terminal with protocol support
    # This covers iTerm2, Ghostty, Kitty, WezTerm, VS Code, etc.
    return False


def has_mac_terminal_block_gap_issue() -> bool:
    """Detect if we should use safe borders due to potential block character issues.

    Returns True when:
    1. Running in macOS Terminal.app (which renders fractional block characters
       with visible gaps)
    2. Running over SSH (we can't detect the client terminal's capabilities)

    macOS Terminal.app renders fractional block characters (▊▎▔▁) with visible
    gaps or misalignment because the font glyphs don't fill cells correctly.
    This affects 'tall' borders which use these characters.

    Box-drawing characters used in 'solid' (│┌┐└┘─) borders render correctly
    because font designers specifically design these to connect.

    Modern terminals like iTerm2, Kitty, and WezTerm render block characters
    programmatically to fill cells completely, avoiding this issue.

    Returns:
        True if we should use safe (solid) borders, False otherwise.
    """
    # Over SSH, we can't detect the client terminal - use safe defaults
    if is_ssh_session():
        return True

    from ..terminal_info import terminal_info

    return terminal_info.is_mac_terminal


def has_limited_unicode_support() -> bool:
    """Detect if the terminal has limited Unicode block character rendering.

    Returns True when:
    1. Running over SSH (we can't detect the client terminal's capabilities)
    2. Running on Windows with a legacy terminal (cmd.exe, PowerShell with
       default fonts that lack Unicode block characters)

    Detection logic:
    - Over SSH: Returns True (can't detect client terminal)
    - On non-Windows platforms (local): Returns False (macOS/Linux terminals
      generally support Unicode well)
    - On Windows: Uses Rich's legacy_windows detection which checks for VT support

    Rich's approach checks ENABLE_VIRTUAL_TERMINAL_PROCESSING via Windows API.
    Terminals with VT support (Windows Terminal, VS Code) also have font fallback
    for Unicode glyphs. Legacy cmd.exe and PowerShell don't have VT support and
    use fonts (Consolas, Lucida Console) that lack box-drawing characters.

    Note: UTF-8 encoding does NOT indicate glyph rendering capability. A terminal
    can support UTF-8 bytes but use fonts without the required characters.

    Returns:
        True if terminal likely has limited Unicode support, False otherwise.
    """
    # Over SSH, we can't detect the client terminal - use safe defaults
    if is_ssh_session():
        return True

    if sys.platform != "win32":
        # macOS and Linux terminals generally support Unicode well (when local)
        return False

    # Use Rich's VT detection - checks ENABLE_VIRTUAL_TERMINAL_PROCESSING
    # This is the industry-standard approach used by Rich/Textual
    # See: https://github.com/Textualize/rich/blob/master/rich/_windows.py
    from rich.console import Console

    console = Console()
    return console.legacy_windows


def get_warning_icon() -> str:
    """Get platform-appropriate warning icon.

    Returns U+26A0 alone for Windows (all terminals have emoji width issues),
    or U+26A0 + U+FE0F (variation selector) for macOS/Linux.

    The variation selector (U+FE0F) requests emoji presentation, which renders as a
    colorful yellow warning triangle on macOS/Linux. Without it, the icon renders as
    a small monochrome glyph.

    On Windows, ALL terminals (including Windows Terminal) have emoji width calculation
    mismatches: Rich calculates emoji+VS16 as 1 cell, but terminals render as 2 cells.
    Using the plain character avoids layout corruption.

    Returns:
        Warning icon string appropriate for the current terminal.
    """
    if sys.platform == "win32":
        return "\u26a0"  # Plain warning sign (consistent 1-cell width)
    return "\u26a0\ufe0f"  # Warning sign + emoji variation selector


def get_info_icon() -> str:
    """Get platform-appropriate info icon.

    Returns U+2139 alone for Windows (all terminals have emoji width issues),
    or U+2139 + U+FE0F (variation selector) for macOS/Linux.

    The variation selector (U+FE0F) requests emoji presentation, which renders as a
    colorful blue info icon on macOS/Linux. Without it, the icon renders as a small
    monochrome glyph.

    On Windows, ALL terminals (including Windows Terminal) have emoji width calculation
    mismatches: Rich calculates emoji+VS16 as 1 cell, but terminals render as 2 cells.
    Using the plain character avoids layout corruption.

    Returns:
        Info icon string appropriate for the current terminal.
    """
    if sys.platform == "win32":
        return "\u2139"  # Plain information source (consistent 1-cell width)
    return "\u2139\ufe0f"  # Information source + emoji variation selector


def get_selection_indicator() -> str:
    """Get platform-appropriate selection indicator for list items.

    Returns '>' for terminals with limited Unicode support (cmd.exe, PowerShell
    with default fonts, SSH sessions), or '▶' (U+25B6 Black Right-Pointing Triangle)
    for modern terminals.

    The triangle character doesn't render in Windows legacy terminals because
    their default fonts (Consolas, Lucida Console) lack the glyph, showing a
    replacement character (▢) instead.

    Returns:
        Selection indicator string appropriate for the current terminal.
    """
    if has_limited_unicode_support():
        return ">"
    return "\u25b6"  # Black right-pointing triangle


def get_ascii_scrollbar_renderer() -> "type[ScrollBarRender]":
    """Get a scrollbar renderer that uses ASCII-compatible characters.

    Returns a ScrollBarRender subclass that uses spaces instead of
    Unicode block elements for the scrollbar ends, making it compatible
    with Windows terminals that don't support those characters.

    Returns:
        A ScrollBarRender subclass with ASCII-compatible characters.
    """
    from textual.scrollbar import ScrollBarRender

    class AsciiScrollBarRender(ScrollBarRender):
        """Scrollbar renderer using ASCII-compatible characters.

        Uses spaces instead of fractional block characters (▁▂▃▄▅▆▇ and ▉▊▋▌▍▎▏)
        which don't render in Windows cmd.exe/PowerShell with default fonts.
        """

        # Use spaces for all bar positions - this gives a solid block appearance
        # that works in all terminals. The scrollbar will still be visible via
        # its background/foreground colors.
        VERTICAL_BARS: list[str] = [" ", " ", " ", " ", " ", " ", " ", " "]
        HORIZONTAL_BARS: list[str] = [" ", " ", " ", " ", " ", " ", " ", " "]

    return AsciiScrollBarRender


def configure_terminal_compatibility() -> None:
    """Configure Textual for terminals with limited Unicode support.

    Call this before running the app to set up ASCII-compatible rendering
    when the terminal doesn't support Unicode block elements.
    """
    if has_limited_unicode_support():
        from textual.scrollbar import ScrollBar

        ScrollBar.renderer = get_ascii_scrollbar_renderer()
