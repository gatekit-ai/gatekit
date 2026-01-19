import base64

import pytest

from gatekit.tui.clipboard import _build_osc52_sequence


def _expected_payload(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_build_plain_osc52_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure we emit the raw OSC 52 sequence when no multiplexer is detected.

    Uses ST (String Terminator) instead of BEL for better terminal compatibility.
    """
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("STY", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")

    text = "copy me"
    payload = _expected_payload(text)

    # Uses ST (\x1b\\) instead of BEL (\a) for better terminal compatibility
    assert _build_osc52_sequence(text) == f"\x1b]52;c;{payload}\x1b\\"


def test_build_tmux_wrapped_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    """tmux requires a DCS wrapper so the OSC 52 escape reaches the host terminal."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-123")
    monkeypatch.setenv("TERM", "screen-256color")
    monkeypatch.delenv("STY", raising=False)

    text = "tmux text"
    payload = _expected_payload(text)
    # Inner sequence uses ST, outer wrapper also ends with ST
    expected_inner = f"\x1b]52;c;{payload}\x1b\\"

    assert _build_osc52_sequence(text) == f"\x1bPtmux;\x1b{expected_inner}\x1b\\"


def test_build_screen_wrapped_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    """GNU screen sets STY/TERM, so ensure we emit the generic wrapper."""
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("STY", "1234.pts-0.host")
    monkeypatch.setenv("TERM", "screen-256color")

    text = "screen text"
    payload = _expected_payload(text)
    # Inner sequence uses ST, outer wrapper also ends with ST
    expected_inner = f"\x1b]52;c;{payload}\x1b\\"

    assert _build_osc52_sequence(text) == f"\x1bP\x1b{expected_inner}\x1b\\"
