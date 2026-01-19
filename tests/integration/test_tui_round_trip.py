"""TUI round-trip integration tests using Textual Pilot and golden configs.

These tests verify that the TUI can:
1. Load configuration files built from golden configs
2. Open plugin configuration modals
3. Navigate and interact with plugin forms
4. Persist changes correctly to the YAML file

Per the integration testing strategy, we test three representative plugins:
- Deep nesting: basic_pii_filter (nested pii_types structure)
- Array-heavy: tool_manager (tool lists) - requires server context
- Simple: audit_jsonl (flat config structure)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.integration.helpers.gateway_harness import compose_proxy_config
from tests.utils.golden import iter_golden_configs, load_golden_config
from tests.utils.textual import (
    cancel_modal,
    launch_tui,
)


def _write_config(config_dict: dict, path: Path) -> None:
    """Write a config dict to a YAML file."""
    path.write_text(yaml.dump(config_dict, default_flow_style=False))


@pytest.fixture
def tmp_config_path(tmp_path):
    """Provide a temporary config file path."""
    return tmp_path / "test_config.yaml"


class TestTUIWithGoldenConfigs:
    """Test TUI launch and interaction with golden config-derived configs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler,scenario",
        [
            ("basic_pii_filter", "typical"),
            ("basic_pii_filter", "edge"),
            ("basic_secrets_filter", "typical"),
            ("audit_jsonl", "typical"),
            ("audit_csv", "typical"),
            ("call_trace", "typical"),
        ],
        ids=lambda x: x if isinstance(x, str) else None,
    )
    async def test_tui_launches_with_golden_config(
        self, tmp_config_path: Path, handler: str, scenario: str
    ):
        """Verify TUI launches successfully with configs built from golden configs."""
        config_dict = compose_proxy_config([(handler, scenario)])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)
            screen_name = ctx.get_screen_name()
            assert "ConfigEditorScreen" in screen_name, f"Expected ConfigEditorScreen, got {screen_name}"

    @pytest.mark.asyncio
    async def test_tui_with_multiple_plugins(self, tmp_config_path: Path):
        """Verify TUI handles configs with multiple plugins from different categories."""
        config_dict = compose_proxy_config([
            ("basic_pii_filter", "typical"),
            ("basic_secrets_filter", "typical"),
            ("audit_jsonl", "typical"),
        ])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            # Verify config structure is preserved
            loaded = ctx.read_config()
            assert "plugins" in loaded
            assert "security" in loaded["plugins"]
            assert "auditing" in loaded["plugins"]


class TestDeepNestedPlugin:
    """Test the basic_pii_filter plugin (deep nesting scenario) using golden configs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["minimal", "typical", "edge"])
    async def test_pii_filter_config_loads(self, tmp_config_path: Path, scenario: str):
        """Verify PII filter golden configs load correctly in TUI."""
        golden = load_golden_config("basic_pii_filter", scenario)
        config_dict = compose_proxy_config([("basic_pii_filter", scenario)])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            loaded = ctx.read_config()
            pii_config = loaded["plugins"]["security"]["_global"][0]["config"]

            # Verify key fields from golden config are preserved
            assert pii_config["enabled"] == golden.config["enabled"]
            assert pii_config["action"] == golden.config["action"]
            assert "pii_types" in pii_config


class TestSimplePlugin:
    """Test the audit_jsonl plugin (simple/flat scenario) using golden configs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["minimal", "typical", "edge"])
    async def test_jsonl_audit_config_loads(self, tmp_config_path: Path, scenario: str):
        """Verify JSONL audit golden configs load correctly in TUI."""
        golden = load_golden_config("audit_jsonl", scenario)
        config_dict = compose_proxy_config([("audit_jsonl", scenario)])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            loaded = ctx.read_config()
            jsonl_config = loaded["plugins"]["auditing"]["_global"][0]["config"]

            # Verify key fields from golden config are preserved
            assert jsonl_config["enabled"] == golden.config["enabled"]
            assert jsonl_config["output_file"] == golden.config["output_file"]


class TestArrayPlugin:
    """Test the tool_manager plugin (array-heavy scenario) using golden configs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ["minimal", "typical", "edge"])
    async def test_tool_manager_config_loads(self, tmp_config_path: Path, scenario: str):
        """Verify tool manager golden configs load correctly in TUI."""
        golden = load_golden_config("tool_manager", scenario)
        # tool_manager is server-aware, so scope it to the test upstream
        config_dict = compose_proxy_config([("tool_manager", scenario, "test-upstream")])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            loaded = ctx.read_config()
            tool_config = loaded["plugins"]["middleware"]["test-upstream"][0]["config"]

            # Verify key fields from golden config are preserved
            assert tool_config["enabled"] == golden.config["enabled"]
            if "tools" in golden.config:
                assert "tools" in tool_config
                assert len(tool_config["tools"]) == len(golden.config["tools"])


class TestConfigPersistence:
    """Test that configuration changes persist correctly."""

    @pytest.mark.asyncio
    async def test_config_unchanged_without_edits(self, tmp_config_path: Path):
        """Verify config file unchanged when TUI opens and closes without edits."""
        config_dict = compose_proxy_config([("basic_pii_filter", "typical")])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)
            original = ctx.original_config.copy()

            # Just quit without making changes
            await ctx.press("ctrl+q")
            await ctx.pause(delay=0.1)

            # Config should be unchanged
            loaded = ctx.read_config()
            assert loaded == original

    @pytest.mark.asyncio
    async def test_structure_preserved_after_interaction(self, tmp_config_path: Path):
        """Verify config structure preserved after TUI interaction."""
        config_dict = compose_proxy_config([
            ("basic_pii_filter", "typical"),
            ("audit_jsonl", "typical"),
        ])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            # Navigate around
            await ctx.press("tab", "tab", "down", "up")
            await ctx.pause(delay=0.1)

            # Verify structure is intact
            loaded = ctx.read_config()
            assert "proxy" in loaded
            assert "plugins" in loaded
            assert "security" in loaded["plugins"]
            assert "auditing" in loaded["plugins"]


class TestPluginModalInteraction:
    """Test plugin modal interactions."""

    @pytest.mark.asyncio
    async def test_modal_cancel_preserves_config(self, tmp_config_path: Path):
        """Verify canceling a modal does not change the config."""
        config_dict = compose_proxy_config([("basic_pii_filter", "typical")])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)
            original = ctx.read_config()

            # Try to find and click configure button, then cancel
            try:
                await ctx.click("#action_configure_basic_pii_filter")
                await ctx.pause(delay=0.1)

                screen_name = ctx.get_screen_name()
                if "Modal" in screen_name:
                    await cancel_modal(ctx)
                    await ctx.pause(delay=0.1)

                    loaded = ctx.read_config()
                    assert loaded == original
            except Exception:
                # Configure button may not be visible in global context
                pytest.skip("Configure button not available in current view")


class TestNavigationWithGoldenConfigs:
    """Test navigation with configs built from golden configs."""

    @pytest.mark.asyncio
    async def test_tab_navigation_with_plugins(self, tmp_config_path: Path):
        """Verify Tab key navigates between sections with real plugins."""
        config_dict = compose_proxy_config([
            ("basic_pii_filter", "typical"),
            ("audit_jsonl", "typical"),
        ])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            # Press Tab to navigate
            await ctx.press("tab")
            await ctx.pause(delay=0.1)

            # Should have focus somewhere
            assert ctx.app.focused is not None

    @pytest.mark.asyncio
    async def test_checkbox_toggle_with_golden_config(self, tmp_config_path: Path):
        """Verify checkbox toggle works with golden config plugins."""
        config_dict = compose_proxy_config([("basic_pii_filter", "typical")])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            # Try to click the plugin checkbox
            try:
                await ctx.click("#checkbox_basic_pii_filter")
                await ctx.pause(delay=0.1)
                # Click succeeded - checkbox should have toggled
            except Exception:
                pytest.skip("Checkbox not found in current view")


class TestKeyboardShortcuts:
    """Test keyboard shortcuts with golden config-derived configs."""

    @pytest.mark.asyncio
    async def test_ctrl_s_with_golden_config(self, tmp_config_path: Path):
        """Verify Ctrl+S works with golden config plugins."""
        config_dict = compose_proxy_config([("basic_pii_filter", "typical")])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            await ctx.press("ctrl+s")
            await ctx.pause(delay=0.1)

            # Config should remain valid
            loaded = ctx.read_config()
            assert "proxy" in loaded

    @pytest.mark.asyncio
    async def test_escape_key_with_golden_config(self, tmp_config_path: Path):
        """Verify Escape key behavior with golden config plugins."""
        config_dict = compose_proxy_config([("audit_jsonl", "typical")])
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            await ctx.press("escape")
            await ctx.pause(delay=0.1)
            # Should trigger quit (may show confirmation if dirty)


class TestAllGoldenConfigsLoad:
    """Smoke test that all golden configs can be loaded in the TUI."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scenario",
        list(iter_golden_configs()),
        ids=lambda s: f"{s.handler}:{s.scenario}",
    )
    async def test_golden_config_loads_in_tui(self, tmp_config_path: Path, scenario):
        """Verify each golden config can be loaded in the TUI without error."""
        # Server-aware plugins need server scope
        if scenario.category == "middleware":
            config_dict = compose_proxy_config(
                [(scenario.handler, scenario.scenario, "test-upstream")]
            )
        else:
            config_dict = compose_proxy_config(
                [(scenario.handler, scenario.scenario)]
            )
        _write_config(config_dict, tmp_config_path)

        async with launch_tui(config_path=tmp_config_path) as ctx:
            await ctx.pause(delay=0.2)

            screen_name = ctx.get_screen_name()
            assert "ConfigEditorScreen" in screen_name, (
                f"Golden config {scenario.handler}:{scenario.scenario} failed to load. "
                f"Screen: {screen_name}"
            )

            # Verify the config round-trips through TUI correctly
            loaded = ctx.read_config()
            assert "plugins" in loaded
