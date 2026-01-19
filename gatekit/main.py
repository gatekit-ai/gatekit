"""Gatekit MCP Gateway Server - Main entry point."""

import argparse
import asyncio
import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Optional

from gatekit._version import __version__
from gatekit.cli.startup_error_handler import StartupErrorHandler
from gatekit.config.loader import ConfigLoader
from gatekit.config.errors import ConfigError
from gatekit.config.models import LoggingConfig
from gatekit.proxy.server import MCPProxy
from gatekit.plugins.manager import PluginManager


class UTCFormatter(logging.Formatter):
    """Custom formatter that uses UTC time with microsecond support."""

    converter = time.gmtime

    def formatTime(self, record, datefmt=None):
        """Format time using datetime to support %f (microseconds)."""
        from datetime import datetime, timezone

        ct = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            # Use datetime.strftime which supports %f
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%dT%H:%M:%S")
        return s


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Clear any existing handlers (close file handlers first)
    for handler in root_logger.handlers[:]:
        if hasattr(handler, "close"):
            handler.close()
        root_logger.removeHandler(handler)

    # Create UTC formatter and handler
    formatter = UTCFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Reduce noise from some third-party libraries
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def setup_logging_from_config(
    logging_config: Optional[LoggingConfig] = None, verbose: bool = False
) -> None:
    """Configure logging based on configuration file or fallback to default.

    Args:
        logging_config: Optional logging configuration from config file
        verbose: Whether to enable verbose debug logging (overrides config level)
    """
    # Determine log level - verbose flag overrides config
    if verbose:
        log_level = logging.DEBUG
    elif (
        logging_config
        and hasattr(logging_config, "level")
        and isinstance(logging_config.level, str)
    ):
        log_level = getattr(logging, logging_config.level.upper())
    else:
        log_level = logging.INFO

    # If no logging config or logging config is not a proper LoggingConfig object, use simple stderr logging
    if not logging_config or not isinstance(logging_config, LoggingConfig):
        # Use UTC formatter for default logging too
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.handlers.clear()

        formatter = UTCFormatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
        )
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

        # Reduce noise from some third-party libraries
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        return

    # Determine format and date format from config
    format_str = logging_config.format
    date_format_str = logging_config.date_format

    # If only stderr handler, set up manually with UTC formatter
    if logging_config.handlers == ["stderr"]:
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.handlers.clear()

        formatter = UTCFormatter(fmt=format_str, datefmt=date_format_str)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

        # Reduce noise from some third-party libraries
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        return

    # For file-only or combined handlers, set up manually
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers (close file handlers first)
    for handler in root_logger.handlers[:]:
        if hasattr(handler, "close"):
            handler.close()
        root_logger.removeHandler(handler)

    # Create UTC formatter
    formatter = UTCFormatter(fmt=format_str, datefmt=date_format_str)

    # Set up handlers based on configuration
    for handler_type in logging_config.handlers:
        if handler_type == "stderr":
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(formatter)
            root_logger.addHandler(handler)
        elif handler_type == "file":
            if logging_config.file_path:
                # Ensure log directory exists
                logging_config.file_path.parent.mkdir(parents=True, exist_ok=True)

                # Create rotating file handler
                handler = logging.handlers.RotatingFileHandler(
                    logging_config.file_path,
                    maxBytes=logging_config.max_file_size_mb * 1024 * 1024,
                    backupCount=logging_config.backup_count,
                )
                handler.setFormatter(formatter)
                root_logger.addHandler(handler)

    # Reduce noise from some third-party libraries
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def run_gateway(config_path: Path, verbose: bool = False) -> None:
    """Run Gatekit as MCP gateway/proxy."""
    asyncio.run(run_proxy(config_path, verbose))


async def run_proxy(config_path: Path, verbose: bool = False) -> None:
    """Run the Gatekit proxy server."""
    logger = None
    try:
        # Load configuration first to get logging settings
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(config_path)

        # Set up logging using config or fallback
        setup_logging_from_config(config.logging, verbose)
        logger = logging.getLogger(__name__)

        logger.info(f"Loading configuration from {config_path}")

        # Create and start proxy
        logger.info("Starting Gatekit MCP Gateway")
        proxy = MCPProxy(config, config_loader.config_directory)
        logger.info("Gatekit is ready and accepting connections")
        await proxy.run()

    except FileNotFoundError as e:
        # Use error handler to communicate to MCP client
        await StartupErrorHandler.handle_startup_error(
            e, f"Loading configuration from {config_path}"
        )
    except ValueError as e:
        # Use error handler to communicate to MCP client
        await StartupErrorHandler.handle_startup_error(e, "Parsing configuration file")
    except KeyboardInterrupt:
        if logger:
            logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        # Use error handler to communicate to MCP client
        await StartupErrorHandler.handle_startup_error(e, "Starting Gatekit proxy")


async def debug_show_plugin_order(config_path: Path) -> None:
    """Show the current plugin execution order with priorities.

    Loads the configured plugins and displays their execution order
    based on priorities. Shows both security and auditing plugins
    with their respective execution models.
    """
    _print_debug_header("Plugin Execution Order")

    try:
        # Load configuration first to get logging settings
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(config_path)

        # Set up logging using config
        setup_logging_from_config(config.logging)
        logger = logging.getLogger(__name__)

        # Create plugin manager and load plugins
        plugins_config = config.plugins.to_dict() if config.plugins else {}
        plugin_manager = PluginManager(plugins_config, config_loader.config_directory)
        await plugin_manager.load_plugins()

        # Show middleware plugins (both global and server-specific)
        all_middleware_plugins = []

        # Collect global middleware plugins (if they exist in _global key)
        if "_global" in plugin_manager.upstream_middleware_plugins:
            all_middleware_plugins.extend(
                plugin_manager.upstream_middleware_plugins["_global"]
            )

        # Collect server-specific middleware plugins
        for (
            server_name,
            server_plugins,
        ) in plugin_manager.upstream_middleware_plugins.items():
            if server_name != "_global":  # Skip _global since we already added it
                all_middleware_plugins.extend(server_plugins)

        if all_middleware_plugins:
            print("\nMiddleware Plugins (execute in order):")
            for i, plugin in enumerate(all_middleware_plugins, 1):
                priority = getattr(plugin, "priority", 50)
                plugin_id = getattr(plugin, "plugin_id", plugin.__class__.__name__)
                server_context = getattr(plugin, "_server_context", None)
                if server_context:
                    print(
                        f"  {i}. {plugin_id} ({server_context}) (priority: {priority})"
                    )
                else:
                    print(f"  {i}. {plugin_id} (priority: {priority})")
        else:
            print("\nMiddleware Plugins: None configured")

        # Show security plugins (both global and server-specific)
        all_security_plugins = []

        # Collect global security plugins
        all_security_plugins.extend(plugin_manager.security_plugins)

        # Collect server-specific security plugins
        for (
            _server_name,
            server_plugins,
        ) in plugin_manager.upstream_security_plugins.items():
            all_security_plugins.extend(server_plugins)

        if all_security_plugins:
            print("\nSecurity Plugins (execute in order, stop on first denial):")
            for i, plugin in enumerate(all_security_plugins, 1):
                priority = getattr(plugin, "priority", 50)
                plugin_id = getattr(plugin, "plugin_id", plugin.__class__.__name__)
                server_context = getattr(plugin, "_server_context", None)
                if server_context:
                    print(
                        f"  {i}. {plugin_id} ({server_context}) (priority: {priority})"
                    )
                else:
                    print(f"  {i}. {plugin_id} (priority: {priority})")
        else:
            print("\nSecurity Plugins: None configured")

        # Show auditing plugins
        if plugin_manager.auditing_plugins:
            print("\nAuditing Plugins (all execute in definition order):")
            for i, plugin in enumerate(plugin_manager.auditing_plugins, 1):
                plugin_id = getattr(plugin, "plugin_id", plugin.__class__.__name__)
                print(f"  {i}. {plugin_id}")
        else:
            print("\nAuditing Plugins: None configured")

        print(
            f"\nTotal plugins loaded: {len(all_middleware_plugins) + len(all_security_plugins) + len(plugin_manager.auditing_plugins)}"
        )

    except Exception as e:
        setup_logging_from_config(None)
        logger = logging.getLogger(__name__)
        logger.exception(f"Error in debug_show_plugin_order: {e}")
        # Use inline error handling for this case since _handle_config_error is defined later
        if isinstance(e, FileNotFoundError):
            print(f"❌ Configuration file not found: {config_path}")
        else:
            print(f"❌ Error loading plugins: {e}")
        sys.exit(1)


def _print_debug_header(title: str) -> None:
    """Print a consistent debug command header."""
    print(f"{title}:")
    print("=" * 50)


def _resolve_config_path(config_path: Path) -> Optional[Path]:
    """Resolve configuration file path using exact path only.

    Args:
        config_path: The config path provided by the user

    Returns:
        The resolved absolute path if found, None otherwise
    """
    # Use exact path only for predictable behavior
    if config_path.exists():
        return config_path.resolve()

    # File not found
    return None

    # Smart resolution disabled for predictable behavior
    # Uncomment below to enable automatic checking of:
    # - configs/ subdirectory
    # - adding .yaml/.yml extensions
    #
    # # If not found and it's relative, try common locations
    # if not config_path.is_absolute():
    #     # Try in configs/ subdirectory
    #     configs_path = Path.cwd() / "configs" / config_path
    #     if configs_path.exists():
    #         return configs_path.resolve()
    #
    #     # Try with different extensions if no extension provided
    #     if not config_path.suffix:
    #         for ext in ['.yaml', '.yml']:
    #             # Try with extension in current directory
    #             path_with_ext = config_path.with_suffix(ext)
    #             if path_with_ext.exists():
    #                 return path_with_ext.resolve()
    #
    #             # Try with extension in configs/ directory
    #             configs_path_with_ext = Path.cwd() / "configs" / path_with_ext
    #             if configs_path_with_ext.exists():
    #                 return configs_path_with_ext.resolve()


def _handle_config_error(e: Exception, config_path: Path) -> None:
    """Handle configuration loading errors with specific error types."""
    if isinstance(e, FileNotFoundError):
        print(f"❌ Configuration file not found: {config_path}")
    elif isinstance(e, ConfigError):
        if e.error_type == "yaml_syntax":
            print(f"❌ YAML syntax error: {e.message}")
        elif e.error_type == "missing_plugin":
            print(f"❌ Missing plugin: {e.message}")
        elif e.error_type == "validation_error":
            # Check if it's specifically about missing fields
            if "missing" in e.message.lower() or "required" in e.message.lower():
                print(f"❌ Missing required field: {e.message}")
            else:
                print(f"❌ Configuration validation failed: {e.message}")
        else:
            print(f"❌ Configuration error: {e.message}")
    elif isinstance(e, ValueError):
        if "YAML" in str(e) or "syntax" in str(e).lower():
            print(f"❌ YAML syntax error: {e}")
        elif "missing" in str(e).lower() or "required" in str(e).lower():
            print(f"❌ Missing required field: {e}")
        else:
            print(f"❌ Configuration validation failed: {e}")
    elif isinstance(e, TypeError):
        print(f"❌ Type validation error: {e}")
    else:
        print(f"❌ Configuration validation failed: {e}")
    sys.exit(1)


async def debug_validate_config(config_path: Path) -> None:
    """Validate configuration file for syntax and type errors.

    Checks the configuration file for:
    - Valid YAML syntax
    - Required fields presence
    - Correct data types
    - Schema compliance
    """
    _print_debug_header("Configuration Validation")

    try:
        # Try to load the configuration
        config_loader = ConfigLoader()
        config_loader.load_from_file(config_path)

        print("✅ Configuration is valid")
        print("All required fields present")
        print("All types valid")
        print("YAML syntax correct")

    except Exception as e:
        _handle_config_error(e, config_path)


def _get_plugin_description(policy_class) -> str:
    """Extract description from plugin class docstring."""
    if policy_class.__doc__:
        # Get first line of docstring and clean it up
        description = policy_class.__doc__.split("\n")[0].strip()
        return description if description else "No description available"
    return "No description available"


def _print_plugin_category(category_name: str, policies: dict) -> int:
    """Print plugins for a category and return count."""
    print(f"\n{category_name} Plugins:")
    if policies:
        for policy_name, policy_class in policies.items():
            description = _get_plugin_description(policy_class)
            print(f"  - {policy_name}: {description}")
        return len(policies)
    else:
        print("  None found")
        return 0


async def debug_list_available_plugins() -> None:
    """List all available plugins with their descriptions.

    Discovers and displays all middleware, security and auditing plugins
    available in the system, including their descriptions
    extracted from class docstrings.
    """
    _print_debug_header("Available Plugins")

    try:
        # Create a temporary plugin manager to discover available plugins
        plugin_manager = PluginManager({}, None)

        # Discover and display middleware plugins
        middleware_handlers = plugin_manager._discover_handlers("middleware")
        middleware_count = _print_plugin_category("Middleware", middleware_handlers)

        # Discover and display security plugins
        security_handlers = plugin_manager._discover_handlers("security")
        security_count = _print_plugin_category("Security", security_handlers)

        # Discover and display auditing plugins
        auditing_handlers = plugin_manager._discover_handlers("auditing")
        auditing_count = _print_plugin_category("Auditing", auditing_handlers)

        total_plugins = middleware_count + security_count + auditing_count
        print(f"\nTotal available plugins: {total_plugins}")

    except Exception as e:
        print(f"❌ Error discovering plugins: {e}")
        sys.exit(1)


def _print_validated_plugins(plugins_config: dict) -> None:
    """Print the list of successfully validated plugins."""
    for category in ["middleware", "security", "auditing"]:
        if plugins_config.get(category):
            category_config = plugins_config[category]

            # Handle upstream-scoped format (dictionary only)
            if isinstance(category_config, dict):
                # Iterate through upstream configs
                for upstream_name, plugin_list in category_config.items():
                    if isinstance(plugin_list, list):
                        for plugin_config in plugin_list:
                            # Read enabled from nested config dict (consolidated format)
                            if plugin_config.get("config", {}).get("enabled", True):
                                handler_name = plugin_config.get("handler", "unknown")
                                upstream_display = (
                                    f" ({upstream_name})"
                                    if upstream_name != "_global"
                                    else ""
                                )
                                print(f"  {handler_name}{upstream_display}: Valid")


async def debug_validate_plugin_config(config_path: Path) -> None:
    """Validate plugin configurations for correctness.

    Validates all configured plugins by attempting to load them
    and checking for configuration errors. Reports specific
    validation failures and lists successfully validated plugins.
    """
    _print_debug_header("Plugin Configuration Validation")

    try:
        # Load configuration first
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(config_path)

        plugins_config = config.plugins.to_dict() if config.plugins else {}

        if not plugins_config or (
            not plugins_config.get("security")
            and not plugins_config.get("auditing")
            and not plugins_config.get("middleware")
        ):
            print("No plugins configured")
            return

        # Create plugin manager and try to load plugins to validate config
        plugin_manager = PluginManager(plugins_config, config_loader.config_directory)

        try:
            await plugin_manager.load_plugins()

            # Check if any plugins failed to load
            if plugin_manager.has_load_failures():
                failures = plugin_manager.get_load_failures()
                print("❌ Plugin configuration errors found:")
                for failure in failures:
                    print(
                        f"  {failure['type'].title()} plugin '{failure['handler']}': {failure['error']}"
                    )
                sys.exit(1)
            else:
                print("✅ All plugin configurations are valid")
                _print_validated_plugins(plugins_config)

        except Exception as e:
            print("❌ Plugin configuration errors found:")
            print(f"  Configuration validation failed: {e}")
            sys.exit(1)

    except Exception as e:
        _handle_config_error(e, config_path)


async def debug_validate_priorities(config_path: Path) -> None:
    """Validate plugin priority configuration.

    Validates that all plugin priorities are within the valid range
    (0-100) and warns about potential issues such as duplicate
    priorities that may cause unpredictable execution order.
    """
    _print_debug_header("Plugin Priority Validation")

    try:
        # Load configuration first to get logging settings
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(config_path)

        # Set up logging using config
        setup_logging_from_config(config.logging)
        logger = logging.getLogger(__name__)

        # Create plugin manager and validate
        plugins_config = config.plugins.to_dict() if config.plugins else {}
        plugin_manager = PluginManager(plugins_config, config_loader.config_directory)

        validation_passed = True
        issues = []

        try:
            await plugin_manager.load_plugins()

            # Check if any plugins failed to load
            if plugin_manager.has_load_failures():
                validation_passed = False
                failures = plugin_manager.get_load_failures()
                print("❌ Priority validation failed:")
                for failure in failures:
                    print(
                        f"  {failure['type'].title()} plugin '{failure['handler']}': {failure['error']}"
                    )
            else:
                print("✅ All plugin priorities are valid (0-100 range)")

            # Only check for potential issues if no load failures
            if not plugin_manager.has_load_failures():
                # Check for potential issues
                all_security_plugins = []
                all_security_plugins.extend(plugin_manager.security_plugins)
                for (
                    _server_name,
                    server_plugins,
                ) in plugin_manager.upstream_security_plugins.items():
                    all_security_plugins.extend(server_plugins)

                # Only check security plugins for priority issues
                # Auditing plugins don't have priority and execute in definition order

                # Check for same priorities in security plugins
                priorities = {}
                for plugin in all_security_plugins:
                    priority = getattr(plugin, "priority", 50)
                    plugin_id = getattr(plugin, "plugin_id", plugin.__class__.__name__)

                    if priority not in priorities:
                        priorities[priority] = []
                    priorities[priority].append(plugin_id)

                same_priority = {
                    p: plugins for p, plugins in priorities.items() if len(plugins) > 1
                }
                if same_priority:
                    print(
                        "\n⚠️  Plugins with same priority (execution order may be unpredictable):"
                    )
                    for priority, plugins in same_priority.items():
                        print(f"  Priority {priority}: {', '.join(plugins)}")
                    issues.append("Multiple plugins with same priority")

                # Summary
                if issues:
                    print(
                        f"\n⚠️  {len(issues)} potential issue(s) found, but priorities are valid"
                    )
                    print(
                        "Consider reviewing plugin priority assignments for optimal ordering"
                    )
                else:
                    print("\n✅ Plugin priority configuration looks good!")

        except ValueError as e:
            validation_passed = False
            print(f"❌ Priority validation failed: {e}")
        except Exception as e:
            validation_passed = False
            print(f"❌ Error validating priorities: {e}")

        if not validation_passed:
            sys.exit(1)

    except Exception as e:
        setup_logging_from_config(None)
        logger = logging.getLogger(__name__)
        logger.exception(f"Error in debug_validate_priorities: {e}")
        _handle_config_error(e, config_path)


def tui_main():
    """Entry point for TUI (gatekit command)."""
    parser = argparse.ArgumentParser(
        description="Gatekit Security Gateway Configuration Interface"
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        type=Path,
        metavar="CONFIG_FILE",
        help="Configuration file to open (optional)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument("--debug", action="store_true", help="Enable TUI debug logging")
    parser.add_argument(
        "--remote-debug",
        action="store_true",
        help="Enable debugpy for remote debugging",
    )
    parser.add_argument(
        "--show-debug-files",
        action="store_true",
        help="Show TUI diagnostic files and exit",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Run TUI diagnostics (same as --show-debug-files)",
    )
    parser.add_argument(
        "--open-plugin",
        metavar="TYPE:HANDLER[:SCOPE]",
        help="Open the specified plugin configuration modal on startup",
    )
    parser.add_argument(
        "--version", action="version", version=f"Gatekit v{__version__}"
    )

    args = parser.parse_args()

    # Handle diagnostics/debug file listing
    if args.show_debug_files or args.diagnostics:
        from gatekit.diagnostics import show_debug_files

        show_debug_files()
        sys.exit(0)

    # Set up debugpy if requested
    if args.remote_debug:
        try:
            import debugpy

            debugpy.listen(5678)
            print("🔧 Debugpy listening on port 5678")
            print("💡 In VSCode, use 'Attach to Gatekit TUI' debug configuration")
            print("🔗 Waiting for debugger to attach...")
            debugpy.wait_for_client()
            print("✅ Debugger attached! Starting TUI...")
        except ImportError:
            print("❌ debugpy not installed. Install with: pip install debugpy")
            sys.exit(1)

    # If a config file is specified, check if it exists
    # File not found: stderr + exit (no point showing UI)
    # File has errors: show TUI with config picker + error modal (user can see alternatives)
    config_error = None
    if args.config_file:
        resolved_config_path = _resolve_config_path(args.config_file)
        if not resolved_config_path:
            print(f"❌ Configuration file not found: {args.config_file}", file=sys.stderr)
            sys.exit(1)

        # Check if config has validation errors
        try:
            config_loader = ConfigLoader()
            config_loader.load_from_file(resolved_config_path)
        except Exception as e:
            # Store the error to pass to TUI - don't exit here
            config_error = e

    # For TUI mode, suppress logging to stderr to prevent interference with the terminal UI
    # Log messages would appear as text above the TUI interface which is confusing
    if not args.verbose:
        # Suppress all logging unless user specifically requests verbose mode
        logging.getLogger().setLevel(logging.CRITICAL)
        logging.getLogger().handlers.clear()
    else:
        # User wants verbose logging - set up logging normally
        setup_logging(args.verbose)

    initial_plugin_modal_payload = None
    if args.open_plugin:
        parts = args.open_plugin.split(":")
        if len(parts) < 2 or len(parts) > 3:
            parser.error(
                "--open-plugin expects TYPE:HANDLER or TYPE:HANDLER:SCOPE format"
            )
        plugin_type, handler = parts[0].strip(), parts[1].strip()
        scope = parts[2].strip() if len(parts) == 3 else None
        if not plugin_type or not handler:
            parser.error("--open-plugin requires non-empty plugin type and handler")
        initial_plugin_modal_payload = (plugin_type, handler, scope)

    try:
        from gatekit.tui import run_tui
        from gatekit.tui.screens.config_editor.base import PluginModalTarget

        modal_target = (
            PluginModalTarget(*initial_plugin_modal_payload)
            if initial_plugin_modal_payload
            else None
        )

        run_tui(
            args.config_file,
            tui_debug=args.debug,
            config_error=config_error,
            initial_plugin_modal=modal_target,
        )
    except ImportError as e:
        print("Error: Failed to import Textual library for TUI.")
        print(f"  {e}")
        print()
        print("Textual is a core dependency. Try reinstalling Gatekit:")
        print("  pip install --force-reinstall gatekit")
        print()
        print("To run the gateway without TUI:")
        print("  gatekit-gateway --config config.yaml")
        sys.exit(1)
        return


def gateway_main():
    """Entry point for gateway (gatekit-gateway command)."""
    parser = argparse.ArgumentParser(description="Gatekit Security Gateway for MCP")
    parser.add_argument(
        "--config", type=Path, required=True, help="Path to configuration file"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Validate configuration and exit"
    )
    parser.add_argument(
        "--version", action="version", version=f"Gatekit v{__version__}"
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(args.verbose)

    if args.validate_only:
        # Load and validate config
        try:
            from gatekit.config.loader import ConfigLoader

            loader = ConfigLoader()
            loader.load_from_file(args.config)
            print(f"Configuration valid: {args.config}")
            sys.exit(0)
            return
        except Exception as e:
            print(f"Configuration invalid: {e}", file=sys.stderr)
            sys.exit(1)
            return

    # Run the gateway
    run_gateway(args.config, args.verbose)
