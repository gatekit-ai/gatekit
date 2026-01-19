"""Textual Pilot harness helpers for TUI integration testing."""

from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import yaml

from gatekit.tui.app import GatekitConfigApp


@dataclass
class TUITestContext:
    """Context object for TUI test operations."""

    app: GatekitConfigApp
    pilot: Any  # textual.pilot.Pilot
    config_path: Path
    original_config: Dict[str, Any]

    async def pause(self, delay: float = 0) -> None:
        """Pause to allow pending messages to be processed."""
        await self.pilot.pause(delay=delay)

    async def press(self, *keys: str) -> None:
        """Simulate key presses."""
        await self.pilot.press(*keys)

    async def click(self, selector: str, **kwargs) -> None:
        """Click a widget by CSS selector."""
        await self.pilot.click(selector, **kwargs)

    def read_config(self) -> Dict[str, Any]:
        """Read the current config file from disk."""
        return yaml.safe_load(self.config_path.read_text())

    def get_screen_name(self) -> str:
        """Get the current screen class name."""
        return type(self.app.screen).__name__


@asynccontextmanager
async def launch_tui(
    config_path: Optional[Path] = None,
    config_content: Optional[Dict[str, Any]] = None,
    size: tuple[int, int] = (120, 40),
) -> AsyncIterator[TUITestContext]:
    """Launch the Gatekit TUI in test mode.

    Args:
        config_path: Path to an existing config file to load.
        config_content: Dictionary to write as a temporary config file.
                       Mutually exclusive with config_path.
        size: Terminal size (width, height) for the test.

    Yields:
        TUITestContext with app, pilot, and helper methods.

    Example:
        async with launch_tui(config_path=Path("configs/test.yaml")) as ctx:
            await ctx.press("tab", "enter")
            await ctx.pause()
            config = ctx.read_config()
    """
    if config_path and config_content:
        raise ValueError("Cannot specify both config_path and config_content")

    # Handle temporary config file creation
    temp_dir = None
    if config_content:
        temp_dir = tempfile.TemporaryDirectory()
        config_path = Path(temp_dir.name) / "test_config.yaml"
        config_path.write_text(yaml.dump(config_content, default_flow_style=False))

    if not config_path or not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    original_config = yaml.safe_load(config_path.read_text())

    app = GatekitConfigApp(config_path=config_path)

    try:
        async with app.run_test(size=size) as pilot:
            # Wait for initial mount and screen transitions
            await pilot.pause(delay=0.1)

            ctx = TUITestContext(
                app=app,
                pilot=pilot,
                config_path=config_path,
                original_config=original_config,
            )
            yield ctx
    finally:
        if temp_dir:
            temp_dir.cleanup()


async def navigate_to_plugin_modal(
    ctx: TUITestContext,
    plugin_handler: str,
    plugin_type: str = "security",
    scope: str = "_global",
) -> bool:
    """Navigate to and open a plugin configuration modal.

    Args:
        ctx: TUI test context.
        plugin_handler: Handler name (e.g., "basic_pii_filter").
        plugin_type: Plugin type ("security", "middleware", "auditing").
        scope: Scope name ("_global" or server name).

    Returns:
        True if modal was successfully opened, False otherwise.
    """
    # Wait for screen to stabilize
    await ctx.pause(delay=0.1)

    # The plugin tables use ASCIICheckbox widgets with IDs like:
    # "checkbox_{scope}_{plugin_type}_{handler}"
    # And configure buttons with IDs like:
    # "configure_{scope}_{plugin_type}_{handler}"

    # Sanitize handler name for widget ID (replace special chars with underscores)
    safe_handler = plugin_handler.replace("-", "_").replace(".", "_")
    configure_button_id = f"#configure_{scope}_{plugin_type}_{safe_handler}"

    try:
        # Click the configure button to open the modal
        await ctx.click(configure_button_id)
        await ctx.pause(delay=0.1)

        # Check if we're now on a modal screen
        screen_name = ctx.get_screen_name()
        return "Modal" in screen_name or "PluginConfigModal" in screen_name
    except Exception:
        return False


async def toggle_checkbox_in_modal(ctx: TUITestContext, checkbox_id: str) -> bool:
    """Toggle a checkbox in the currently open modal.

    Args:
        ctx: TUI test context.
        checkbox_id: The checkbox widget ID (e.g., "#enabled").

    Returns:
        True if toggle was successful, False otherwise.
    """
    try:
        await ctx.click(checkbox_id)
        await ctx.pause()
        return True
    except Exception:
        return False


async def save_and_close_modal(ctx: TUITestContext) -> bool:
    """Save changes and close the current modal.

    Args:
        ctx: TUI test context.

    Returns:
        True if save was successful, False otherwise.
    """
    try:
        # Try clicking the save button first
        await ctx.click("#save_btn")
        await ctx.pause(delay=0.1)
        return True
    except Exception:
        try:
            # Fallback to Ctrl+S shortcut
            await ctx.press("ctrl+s")
            await ctx.pause(delay=0.1)
            return True
        except Exception:
            return False


async def cancel_modal(ctx: TUITestContext) -> bool:
    """Cancel and close the current modal without saving.

    Args:
        ctx: TUI test context.

    Returns:
        True if cancel was successful, False otherwise.
    """
    try:
        await ctx.press("escape")
        await ctx.pause()
        return True
    except Exception:
        return False


async def type_in_input(ctx: TUITestContext, text: str) -> None:
    """Type text into the currently focused input widget.

    Args:
        ctx: TUI test context.
        text: Text to type.
    """
    # Type each character
    for char in text:
        await ctx.press(char)
    await ctx.pause()


async def clear_input(ctx: TUITestContext) -> None:
    """Clear the currently focused input widget.

    Args:
        ctx: TUI test context.
    """
    # Select all and delete
    await ctx.press("ctrl+a", "backspace")
    await ctx.pause()


__all__ = [
    "TUITestContext",
    "launch_tui",
    "navigate_to_plugin_modal",
    "toggle_checkbox_in_modal",
    "save_and_close_modal",
    "cancel_modal",
    "type_in_input",
    "clear_input",
]
