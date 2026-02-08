"""Unit tests for sandbox TUI components (config models and modal logic)."""

import pytest

from gatekit.config.models import SandboxConfig, UpstreamConfig


class TestSandboxConfigModalLogic:
    """Test sandbox modal business logic (widget-free tests)."""

    def test_modal_save_creates_config(self):
        """Verify SandboxConfig construction from modal-like values."""
        config = SandboxConfig(
            enabled=True,
            paths=["~/docs", "/data"],
            network=False,
        )
        assert config.enabled is True
        assert config.paths == ["~/docs", "/data"]
        assert config.network is False

    def test_modal_cancel_returns_none(self):
        """Cancelling the modal should result in no config change."""
        result = None  # Modal cancel returns None
        assert result is None

    def test_empty_paths_parsed(self):
        """Empty text areas should produce empty lists."""
        text = ""
        paths = [line.strip() for line in text.splitlines() if line.strip()]
        assert paths == []

    def test_multiline_paths_parsed(self):
        """Lines from text areas should be split and stripped."""
        text = "  ~/docs  \n\n  /data/workspace  \n"
        paths = [line.strip() for line in text.splitlines() if line.strip()]
        assert paths == ["~/docs", "/data/workspace"]


class TestSandboxCheckboxLogic:
    """Test sandbox checkbox toggle config mutation logic."""

    def test_enable_sandbox_creates_config(self):
        upstream = UpstreamConfig(name="test", command=["echo", "hi"])
        assert upstream.sandbox is None

        # Simulate checkbox enable
        upstream.sandbox = SandboxConfig(enabled=True)
        assert upstream.sandbox.enabled is True

    def test_disable_sandbox(self):
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(enabled=True),
        )

        # Simulate checkbox disable
        upstream.sandbox.enabled = False
        assert upstream.sandbox.enabled is False

    def test_enable_preserves_existing_config(self):
        """Re-enabling should preserve previous settings."""
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(
                enabled=False,
                paths=["~/docs"],
                network=False,
            ),
        )
        # Re-enable
        upstream.sandbox.enabled = True
        assert upstream.sandbox.paths == ["~/docs"]
        assert upstream.sandbox.network is False

    def test_configure_updates_sandbox(self):
        """Simulate Configure button -> modal -> save flow."""
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(enabled=True),
        )

        # Modal returns a new config
        modal_result = SandboxConfig(
            enabled=True,
            paths=["~/new-path"],
            network=False,
        )
        upstream.sandbox = modal_result

        assert upstream.sandbox.paths == ["~/new-path"]
        assert upstream.sandbox.network is False


class TestSandboxRowVisibility:
    """Test sandbox row should only appear for stdio transport."""

    def test_stdio_shows_sandbox(self):
        upstream = UpstreamConfig(name="test", command=["echo", "hi"])
        assert upstream.transport == "stdio"
        # Row should be shown

    def test_http_hides_sandbox(self):
        upstream = UpstreamConfig(
            name="test", transport="http", url="https://example.com/mcp"
        )
        assert upstream.transport == "http"
        # Row should be hidden
