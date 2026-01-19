"""Startup error handler for communicating failures to MCP clients.

This module provides the integration between Gatekit's main entry point
and the minimal server for error communication.
"""

import asyncio
import logging
import sys

from gatekit.cli.startup_error_notifier import StartupErrorNotifier
from gatekit.config.errors import ConfigError
from gatekit.protocol.errors import StartupError

logger = logging.getLogger(__name__)


def _log_config_error(startup_error: StartupError) -> None:
    """Log a ConfigError in a clean, user-friendly format without traceback.

    Args:
        startup_error: The categorized startup error to log
    """
    logger.error(f"Startup failed: {startup_error.message}")
    if startup_error.details:
        # Indent each line of details for readability
        indented_details = startup_error.details.replace("\n", "\n    ")
        logger.error(f"    {indented_details}")
    if startup_error.fix_instructions:
        # Indent each line of suggestions for readability
        indented_instructions = startup_error.fix_instructions.replace("\n", "\n    ")
        logger.error(f"  Suggestions:\n    {indented_instructions}")


class StartupErrorHandler:
    """Handles startup errors by communicating them to MCP clients."""

    @staticmethod
    async def handle_startup_error(error: Exception, context: str = "") -> None:
        """Handle a startup error by communicating it to the MCP client.

        This method creates a minimal server that can respond to MCP
        requests with error information before exiting.

        Args:
            error: The exception that occurred during startup
            context: Additional context about what was happening
        """
        # Create error notifier
        error_notifier = StartupErrorNotifier()

        # Categorize the error into user-friendly format
        startup_error = error_notifier.categorize_error(error, context)
        error_notifier.startup_error = startup_error

        # Log the error details
        # For ConfigError and FileNotFoundError, don't show traceback - they're user-facing errors
        if isinstance(error, (ConfigError, FileNotFoundError)):
            _log_config_error(startup_error)
        else:
            logger.error(
                f"Startup failed: {startup_error.message} - {startup_error.details}",
                exc_info=error,
            )

        # If we're in a terminal, we're definitely not in an MCP client context
        if sys.stdin.isatty():
            logger.error("Not in MCP client context (running in terminal), exiting")
            sys.exit(1)

        # Try to communicate with MCP client
        # The error notifier will send the error and exit immediately
        try:
            await error_notifier.run_until_shutdown()
        except Exception:
            logger.exception("Error running error notifier")

        # Always exit with error code
        sys.exit(1)

    @staticmethod
    def handle_startup_error_sync(error: Exception, context: str = "") -> None:
        """Synchronous wrapper for handle_startup_error.

        This is used when the error occurs before the async event loop
        is running.

        Args:
            error: The exception that occurred during startup
            context: Additional context about what was happening
        """
        # If we're in a terminal, we're definitely not in an MCP client context
        if sys.stdin.isatty():
            error_notifier = StartupErrorNotifier()
            startup_error = error_notifier.categorize_error(error, context)

            # For ConfigError and FileNotFoundError, don't show traceback - they're user-facing errors
            if isinstance(error, (ConfigError, FileNotFoundError)):
                _log_config_error(startup_error)
            else:
                logger.error(
                    f"Startup failed: {startup_error.message} - {startup_error.details}",
                    exc_info=error,
                )
            sys.exit(1)

        try:
            # Create new event loop to avoid issues with existing loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    StartupErrorHandler.handle_startup_error(error, context)
                )
            finally:
                loop.close()
        except Exception:
            # If even the error handler fails, log and exit
            logger.exception("Failed to communicate error to client")
            sys.exit(1)
