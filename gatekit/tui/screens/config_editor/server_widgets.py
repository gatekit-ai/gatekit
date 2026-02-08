"""Reusable widgets for server management UI."""

from typing import Awaitable, Callable, Optional

from textual.widgets import Button


class AsyncCallbackButton(Button):
    """Button that invokes an async callback when pressed.

    Handles both mouse clicks and Enter key presses by listening to Button.Pressed,
    which is the proper Textual pattern for button activation.

    Uses Textual's worker system (not asyncio.create_task) so that callbacks
    can use push_screen_wait and other APIs that require a worker context.
    """

    def __init__(
        self,
        label: str,
        *,
        callback: Optional[Callable[[], Awaitable[None]]] = None,
        **kwargs,
    ) -> None:
        super().__init__(label, **kwargs)
        self._async_callback = callback

    def set_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        self._async_callback = callback

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press from both mouse and keyboard (Enter key)."""
        from ...debug import get_debug_logger

        logger = get_debug_logger()
        if logger:
            logger.log_event(
                "ASYNC_CALLBACK_BUTTON_PRESSED",
                context={
                    "button_id": getattr(self, "id", None),
                    "button_label": str(self.label),
                    "has_callback": self._async_callback is not None,
                },
            )

        if self._async_callback:
            async def _run_callback_with_logging():
                try:
                    if logger:
                        logger.log_event(
                            "ASYNC_CALLBACK_STARTING",
                            context={"button_id": getattr(self, "id", None)},
                        )
                    await self._async_callback()
                    if logger:
                        logger.log_event(
                            "ASYNC_CALLBACK_COMPLETED",
                            context={"button_id": getattr(self, "id", None)},
                        )
                except Exception as exc:
                    if logger:
                        logger.log_event(
                            "ASYNC_CALLBACK_ERROR",
                            context={
                                "button_id": getattr(self, "id", None),
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                            },
                        )
                    raise

            self.run_worker(_run_callback_with_logging(), exit_on_error=False)
