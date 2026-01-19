"""Configuration loader for Gatekit MCP Gateway."""

import logging
import threading
import yaml
import re
import copy
from pathlib import Path
from typing import Dict, Any, Optional, List
from difflib import get_close_matches
from pydantic import ValidationError

from .models import (
    ProxyConfig,
    PluginsConfig,
    LoggingConfig,
    ProxyConfigSchema,
)
from .errors import ConfigError
from gatekit.utils.exceptions import ConfigValidationError
from gatekit.utils.exceptions import ConfigLoadError

# Compiled regex for secret redaction (performance optimization)
SECRET_REDACTION_PATTERN = re.compile(
    r"(password|token|key|secret|api_key)\s*:\s*[^\s]+", flags=re.IGNORECASE
)


class ConfigLoader:
    """YAML configuration file loader with validation."""

    # Class-level cache for discovered plugin handlers
    _plugin_handler_cache: Dict[str, Dict[str, type]] = {}
    _cache_lock = threading.RLock()  # RLock allows re-entrant access

    def __init__(self):
        """Initialize ConfigLoader."""
        self.config_directory: Optional[Path] = None

        # Store last config dict and directory for easier ignore flow
        self._last_config_dict: Optional[Dict[str, Any]] = None
        self._last_config_directory: Optional[Path] = None

    def load_from_file(self, path: Path) -> ProxyConfig:
        """Load configuration from YAML file.

        Args:
            path: Path to the YAML configuration file

        Returns:
            ProxyConfig: Loaded and validated configuration

        Raises:
            ConfigError: If YAML is invalid, configuration has errors, or plugins are missing
            ValueError: If file cannot be read (IO errors only)
            FileNotFoundError: If the configuration file doesn't exist
        """
        # Resolve config file path to absolute and store directory
        absolute_config_path = path.resolve()
        config_directory = absolute_config_path.parent
        self.config_directory = config_directory

        # Check if file exists
        if not absolute_config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {absolute_config_path}"
            )

        try:
            # Load YAML content
            with open(absolute_config_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            # Check for empty file
            if not content:
                # Empty file is a YAML parsing issue, not validation
                raise ConfigError(
                    message="Configuration file is empty",
                    error_type="yaml_syntax",
                    file_path=absolute_config_path,
                    suggestions=[
                        "Add basic config structure",
                        "Check file was saved properly",
                    ],
                )

            # Parse YAML
            config_dict = yaml.safe_load(content)

            # Check if YAML only had comments or was empty
            if config_dict is None:
                raise ConfigError(
                    message="Configuration file is empty",
                    error_type="yaml_syntax",
                    file_path=absolute_config_path,
                    suggestions=[
                        "Add basic config structure",
                        "Check file was saved properly",
                    ],
                )

        except yaml.YAMLError as e:
            # Extract line number if available (1-based for editors)
            line_num = getattr(e, "problem_mark", None)
            line_number = line_num.line + 1 if line_num else None

            # Get the actual line content with secret redaction
            line_snippet = (
                self._get_line_snippet_safe(absolute_config_path, line_number)
                if line_number
                else None
            )

            # Generate 1-3 heuristic suggestions
            suggestions = self._get_yaml_suggestions(str(e))

            raise ConfigError(
                message=f"YAML syntax error: {getattr(e, 'problem', str(e))}",
                error_type="yaml_syntax",
                file_path=absolute_config_path,
                line_number=line_number,
                line_snippet=line_snippet,
                suggestions=suggestions,
            )
        except (IOError, OSError, UnicodeDecodeError) as e:
            raise ConfigLoadError(f"Error reading configuration file: {e}") from e

        # Load from parsed dictionary
        return self.load_from_dict(config_dict, config_directory)

    def load_from_dict(
        self, config_dict: Dict[str, Any], config_directory: Optional[Path] = None
    ) -> ProxyConfig:
        """Load configuration from dictionary (for testing).

        Args:
            config_dict: Configuration dictionary
            config_directory: Directory containing the configuration file (for path resolution)

        Returns:
            ProxyConfig: Loaded and validated configuration

        Raises:
            ConfigError: If configuration is invalid, missing required sections, or has validation errors
        """
        # Store for potential ignore flow usage
        self._last_config_dict = config_dict.copy()
        self._last_config_directory = config_directory
        # Validate presence of proxy section
        if "proxy" not in config_dict:
            raise ConfigError(
                message="Configuration must contain 'proxy' section",
                error_type="validation_error",
                field_path="proxy",
                suggestions=["Add required field: proxy"],
            )

        proxy_config = config_dict["proxy"]

        # Check for required upstream configuration
        if "upstreams" not in proxy_config:
            raise ConfigError(
                message="Missing required 'upstreams' configuration",
                error_type="validation_error",
                field_path="upstreams",
                suggestions=["Add required field: upstreams"],
            )

        # Enforce canonical format: plugins and logging must be top-level
        if "plugins" in proxy_config:
            raise ConfigError(
                message="Invalid configuration format: 'plugins' must be at top level, not nested under 'proxy'",
                error_type="validation_error",
                field_path="proxy.plugins",
                suggestions=[
                    "Move 'plugins:' section to top level (same level as 'proxy:')",
                    "See docs or example configs for correct format",
                ],
            )
        if "logging" in proxy_config:
            raise ConfigError(
                message="Invalid configuration format: 'logging' must be at top level, not nested under 'proxy'",
                error_type="validation_error",
                field_path="proxy.logging",
                suggestions=[
                    "Move 'logging:' section to top level (same level as 'proxy:')",
                    "See docs or example configs for correct format",
                ],
            )

        try:
            # Canonical format: plugins and logging are top-level sections
            # Combine them with proxy config for validation
            combined_config = {**proxy_config}

            # Add plugins and logging from top-level (required locations)
            if "plugins" in config_dict:
                combined_config["plugins"] = config_dict["plugins"]
            if "logging" in config_dict:
                combined_config["logging"] = config_dict["logging"]

            # Use Pydantic schema for validation and normalization
            schema = ProxyConfigSchema(**combined_config)

            # Convert schema to internal representation
            config = ProxyConfig.from_schema(schema, config_directory)

        except ValidationError as e:
            # Only handle the FIRST error to keep simple
            first_error = e.errors()[0]
            field_path = ".".join(str(loc) for loc in first_error["loc"])

            suggestions = []
            error_type = first_error["type"]

            # Use startswith for robust Pydantic error matching (handles type_error.str, etc.)
            if error_type.startswith("missing"):
                suggestions.append(f"Add required field: {field_path}")
            elif error_type.startswith("type_error"):
                expected = first_error.get("ctx", {}).get(
                    "expected_type", "correct type"
                )
                suggestions.append(f"Change to {expected}")
                if "int" in str(expected):
                    suggestions.append("Remove quotes around numbers")
            elif error_type.startswith("value_error"):
                suggestions.append("Check field value is valid")
            else:
                suggestions.append("Check field value and type")

            raise ConfigError(
                message=f"Configuration validation failed: {first_error['msg']}",
                error_type="validation_error",
                field_path=field_path,
                suggestions=suggestions,
            )
        except (ValueError, TypeError) as e:
            # Handle other validation errors and Python type errors (convert to ConfigError)
            raise ConfigError(
                message=str(e),
                error_type="validation_error",
                suggestions=[
                    "Check configuration values",
                    "Review configuration documentation",
                ],
            ) from e

        # Run additional validation
        self.validate_config(config)

        # Validate plugin configs against JSON schemas (fail-closed for unknown fields)
        self.validate_plugin_schemas(config)

        # Run path validation for all path-aware components
        self.validate_paths(config, config_directory)

        return config

    def validate_config(self, config: ProxyConfig) -> None:
        """Validate configuration completeness and constraints.

        Args:
            config: Configuration to validate

        Raises:
            ValueError: If configuration has validation errors
        """
        # Basic validation is already done by dataclass __post_init__
        # This method can be extended for additional validation logic

        # Validate transport-specific requirements
        if config.transport not in ("stdio", "http"):
            raise ConfigValidationError(
                "Transport must be 'stdio' or 'http'", field="transport"
            )

        if config.transport == "http" and config.http is None:
            raise ConfigValidationError(
                "HTTP transport requires http configuration", field="transport"
            )

        # The dataclass __post_init__ methods will validate individual components
        # when the objects are created, so no additional validation needed here
        # unless we want to add cross-component validation rules

    def validate_plugin_schemas(self, config: ProxyConfig) -> None:
        """Validate plugin configurations against their JSON schemas.

        For critical plugins (default), unknown fields cause fatal startup error.
        For non-critical plugins, unknown fields log a warning and skip the plugin.

        Plugins without schemas are skipped (allows custom plugins).

        Args:
            config: Parsed ProxyConfig object

        Raises:
            ConfigError: If any critical plugin has schema violations
        """
        from gatekit.config.json_schema import get_schema_validator

        validator = get_schema_validator()
        critical_errors = []

        if not config.plugins:
            return

        for category, category_attr in [
            ("security", config.plugins.security),
            ("auditing", config.plugins.auditing),
            ("middleware", config.plugins.middleware),
        ]:
            for upstream, plugin_list in list(category_attr.items()):
                # Build new list excluding plugins that fail non-critical validation
                valid_plugins = []
                for idx, plugin_config in enumerate(plugin_list):
                    handler = plugin_config.handler
                    plugin_conf = plugin_config.config

                    # Check if schema exists for this handler
                    if not validator.has_schema(handler):
                        # Skip plugins without schemas (custom plugins, etc.)
                        valid_plugins.append(plugin_config)
                        continue

                    schema_errors = validator.validate(handler, plugin_conf)
                    if schema_errors:
                        # Check if plugin is critical (default: True)
                        is_critical = plugin_conf.get("critical", True)
                        field_path = f"plugins.{category}.{upstream}.{idx}.config"
                        error_msg = "; ".join(schema_errors)

                        if is_critical:
                            critical_errors.append({
                                "handler": handler,
                                "field_path": field_path,
                                "errors": schema_errors,
                            })
                            valid_plugins.append(plugin_config)  # Keep for error reporting
                        else:
                            # Non-critical: log warning and skip plugin
                            logging.warning(
                                f"Non-critical {category} plugin '{handler}' has schema "
                                f"validation errors: {error_msg}. Plugin will be skipped."
                            )
                            # Don't add to valid_plugins - plugin is skipped
                    else:
                        valid_plugins.append(plugin_config)

                # Update the plugin list with only valid plugins
                category_attr[upstream] = valid_plugins

        if critical_errors:
            # Format error message for critical plugins only
            error_parts = []
            suggestions_set = set()  # Use set to deduplicate suggestions

            has_unknown_field_error = False
            for err in critical_errors:
                handler = err["handler"]
                for schema_err in err["errors"]:
                    error_parts.append(f"{handler} ({err['field_path']}): {schema_err}")

                    if "Additional properties are not allowed" in schema_err:
                        has_unknown_field_error = True
                        schema = validator.get_schema(handler)
                        if schema and "properties" in schema:
                            valid_fields = ", ".join(sorted(schema["properties"].keys()))
                            suggestions_set.add(f"Valid fields for {handler}: {valid_fields}")

            suggestions = list(suggestions_set)
            # Only add "Remove or rename" suggestion when relevant
            if has_unknown_field_error:
                suggestions.append("Remove or rename unknown fields")
            elif not suggestions:
                # Generic fallback for other validation errors
                suggestions.append("Check field values match schema requirements")

            raise ConfigError(
                message="Plugin configuration validation failed:\n  " + "\n  ".join(error_parts),
                error_type="validation_error",
                field_path=critical_errors[0]["field_path"],
                suggestions=suggestions[:3],
            )

    def validate_paths(
        self, config: ProxyConfig, config_directory: Optional[Path] = None
    ) -> None:
        """Validate paths in all path-aware components.

        Args:
            config: Configuration to validate paths for
            config_directory: Directory containing the configuration file (for path resolution)

        Raises:
            ValueError: If any path validation fails
        """
        path_errors = []

        # Validate logging configuration paths
        if config.logging:
            logging_errors = self._validate_logging_paths(config.logging)
            if logging_errors:
                path_errors.extend([f"Logging: {error}" for error in logging_errors])

        # Validate plugin paths
        if config.plugins:
            plugin_errors = self._validate_plugin_paths(
                config.plugins, config_directory
            )
            if plugin_errors:
                path_errors.extend(plugin_errors)

        # If any path validation errors occurred, raise them
        if path_errors:
            error_summary = f"Path validation failed with {len(path_errors)} error(s)"
            error_details = "\n".join([f"  - {error}" for error in path_errors])
            raise ConfigError(
                message=error_summary + ":\n" + error_details,
                error_type="validation_error",
                suggestions=["Check file paths exist", "Verify permissions"],
            )

    def _validate_logging_paths(self, logging_config: LoggingConfig) -> List[str]:
        """Validate paths in logging configuration.

        Args:
            logging_config: Logging configuration to validate

        Returns:
            List of validation error messages
        """
        errors = []

        # Check if file handler is enabled and file_path is configured
        if hasattr(logging_config, "file_path") and logging_config.file_path:
            try:
                from pathlib import Path
                import os

                log_path = Path(logging_config.file_path)
                parent_dir = log_path.parent

                # Check if parent directory exists and is writable
                # Note: If directory doesn't exist, plugins will auto-create it at runtime
                # (per ADR-012 and R3.3: "Create parent directories if they don't exist")
                if parent_dir.exists():
                    # Only check write permissions if directory already exists
                    if not os.access(parent_dir, os.W_OK):
                        errors.append(
                            f"No write permission to log file parent directory: {parent_dir} (for file_path: {logging_config.file_path})"
                        )

            except (OSError, IOError, PermissionError) as e:
                errors.append(
                    f"Error validating log file path '{logging_config.file_path}': {e}"
                )

        return errors

    def _validate_plugin_paths(
        self, plugins_config: PluginsConfig, config_directory: Optional[Path] = None
    ) -> List[str]:
        """Validate paths in plugin configurations.

        Args:
            plugins_config: Plugin configuration to validate
            config_directory: Directory containing the configuration file (for path resolution)

        Returns:
            List of validation error messages
        """
        errors = []

        # Validate security plugin paths (upstream-scoped structure)
        for upstream, plugin_configs in plugins_config.security.items():
            for plugin_config in plugin_configs:
                if plugin_config.enabled:
                    plugin_errors = self._validate_single_plugin_paths(
                        "security", plugin_config, config_directory
                    )
                    if plugin_errors:
                        scope_label = (
                            "(global scope)"
                            if upstream == "_global"
                            else f"({upstream})"
                        )
                        errors.extend(
                            [
                                f"Security plugin '{plugin_config.handler}' {scope_label}: {error}"
                                for error in plugin_errors
                            ]
                        )

        # Validate auditing plugin paths (upstream-scoped structure)
        for upstream, plugin_configs in plugins_config.auditing.items():
            for plugin_config in plugin_configs:
                if plugin_config.enabled:
                    plugin_errors = self._validate_single_plugin_paths(
                        "auditing", plugin_config, config_directory
                    )
                    if plugin_errors:
                        scope_label = (
                            "(global scope)"
                            if upstream == "_global"
                            else f"({upstream})"
                        )
                        errors.extend(
                            [
                                f"Auditing plugin '{plugin_config.handler}' {scope_label}: {error}"
                                for error in plugin_errors
                            ]
                        )

        # Validate middleware plugin paths (upstream-scoped structure)
        for upstream, plugin_configs in plugins_config.middleware.items():
            for plugin_config in plugin_configs:
                if plugin_config.enabled:
                    plugin_errors = self._validate_single_plugin_paths(
                        "middleware", plugin_config, config_directory
                    )
                    if plugin_errors:
                        scope_label = (
                            "(global scope)"
                            if upstream == "_global"
                            else f"({upstream})"
                        )
                        errors.extend(
                            [
                                f"Middleware plugin '{plugin_config.handler}' {scope_label}: {error}"
                                for error in plugin_errors
                            ]
                        )

        return errors

    def _validate_single_plugin_paths(
        self, plugin_type: str, plugin_config, config_directory: Optional[Path] = None
    ) -> List[str]:
        """Validate paths for a single plugin.

        Args:
            plugin_type: Type of plugin ("security" or "auditing")
            plugin_config: Plugin configuration
            config_directory: Directory containing the configuration file (for path resolution)

        Returns:
            List of validation error messages
        """
        errors = []

        try:
            # Get plugin class using handler discovery
            plugin_class = self._get_plugin_class(plugin_type, plugin_config.handler)
            # No need to check for None - method always returns plugin class or raises ConfigError

            # Check if plugin implements PathResolvablePlugin interface
            from gatekit.plugins.interfaces import PathResolvablePlugin

            if not issubclass(plugin_class, PathResolvablePlugin):
                # Plugin doesn't use paths, no validation needed
                return []

            # Check if plugin is critical (default to True for security)
            is_critical = plugin_config.config.get("critical", True)

            # Create temporary plugin instance for path validation
            temp_plugin = plugin_class(plugin_config.config)

            # Set config directory for path resolution
            if config_directory:
                temp_plugin.set_config_directory(config_directory)

            # Validate paths
            validation_errors = temp_plugin.validate_paths()
            if validation_errors:
                if is_critical:
                    # For critical plugins, path validation errors are fatal
                    errors.extend(validation_errors)
                else:
                    # For non-critical plugins, log path validation errors but don't fail startup
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.warning(
                        f"Non-critical {plugin_type} plugin '{plugin_config.handler}' has path validation errors: {'; '.join(validation_errors)}"
                    )

        except ConfigError:
            # Re-raise ConfigError to bubble up with fuzzy suggestions
            raise
        except (ImportError, AttributeError, TypeError, ValueError) as e:
            # Check if plugin is critical to determine error handling behavior
            is_critical = plugin_config.config.get("critical", True)
            if is_critical:
                errors.append(f"Error validating plugin paths: {e}")
            else:
                # For non-critical plugins, log error but don't fail startup
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Non-critical {plugin_type} plugin '{plugin_config.handler}' path validation failed: {e}"
                )

        return errors

    def _get_plugin_class(self, category: str, handler_name: str):
        """Get plugin class using PluginManager's discovery logic with thread-safe caching.

        Args:
            category: Plugin category ("security" or "auditing")
            handler_name: Handler name to look up

        Returns:
            Plugin class if found

        Raises:
            ConfigError: If plugin not found, with fuzzy suggestions
        """
        with self._cache_lock:
            # Check cache first
            if category in self._plugin_handler_cache:
                cached_result = self._plugin_handler_cache[category].get(handler_name)
                if (
                    cached_result is not None
                    or handler_name in self._plugin_handler_cache[category]
                ):
                    # Return cached result (could be None if handler doesn't exist)
                    if cached_result is None:
                        # Generate error with fuzzy suggestions
                        return self._handle_missing_plugin(category, handler_name)
                    return cached_result

            try:
                # Discover handlers for this category if not cached
                if category not in self._plugin_handler_cache:
                    from gatekit.plugins.manager import PluginManager

                    temp_manager = PluginManager({}, None)
                    available_handlers = temp_manager._discover_handlers(category)
                    self._plugin_handler_cache[category] = available_handlers

                plugin_class = self._plugin_handler_cache[category].get(handler_name)
                if not plugin_class:
                    return self._handle_missing_plugin(category, handler_name)

                return plugin_class

            except ConfigError:
                raise  # Re-raise our ConfigError
            except Exception:
                # Cache negative result to prevent repeated discovery failures
                if category not in self._plugin_handler_cache:
                    self._plugin_handler_cache[category] = {}
                # Always raise ConfigError for consistency - don't return None silently
                return self._handle_missing_plugin(category, handler_name)

    def _handle_missing_plugin(self, category: str, handler_name: str):
        """Handle missing plugin with fuzzy suggestions."""
        # Ensure we have the available handlers cached
        if category not in self._plugin_handler_cache:
            try:
                from gatekit.plugins.manager import PluginManager

                temp_manager = PluginManager({}, None)
                available_handlers = temp_manager._discover_handlers(category)
                self._plugin_handler_cache[category] = available_handlers
            except Exception:
                self._plugin_handler_cache[category] = {}

        # Generate fuzzy suggestions (2 lines!)
        available = list(self._plugin_handler_cache[category].keys())
        similar = get_close_matches(handler_name, available, n=2, cutoff=0.6)

        suggestions = []
        if similar:
            suggestions.append(f"Did you mean '{similar[0]}'?")

        # Cap available list to prevent overwhelming line length (max 8 plugins)
        available_sorted = sorted(available)
        if len(available_sorted) <= 8:
            suggestions.append(f"Available {category}: {', '.join(available_sorted)}")
        else:
            suggestions.append(
                f"Available {category}: {', '.join(available_sorted[:8])}, ..."
            )

        raise ConfigError(
            message=f"Plugin '{handler_name}' not found",
            error_type="missing_plugin",
            field_path=f"plugins.{category}.{handler_name}",
            suggestions=suggestions,
        )

    def _get_line_snippet_safe(self, file_path: Path, line_num: int) -> str:
        """Get the problematic line, trimmed and with secrets redacted."""
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
                if 0 < line_num <= len(lines):
                    line = lines[line_num - 1].rstrip()

                    # Redact simple secrets for security using compiled regex
                    line = SECRET_REDACTION_PATTERN.sub(r"\1: ****", line)

                    return line[:80] + "..." if len(line) > 80 else line
        except (OSError, IOError, IndexError):
            # Could not read line from file - return empty (safe fallback)
            pass
        return ""

    def _get_yaml_suggestions(self, error_msg: str) -> List[str]:
        """Generate 1-3 simple suggestions based on error."""
        suggestions = []
        error_lower = error_msg.lower()

        if "expected <block end>" in error_lower:
            suggestions.append("Check indentation - use consistent spaces")
        elif "found character '\\t'" in error_lower:
            suggestions.append("Replace tabs with spaces")
        elif "could not find expected ':'" in error_lower:
            suggestions.append("Add ':' after field names")
        else:
            suggestions.append("Check YAML syntax")

        return suggestions[:3]  # Max 3

    def load_with_plugin_ignore(
        self,
        config_dict: Dict[str, Any],
        error: ConfigError,
        config_directory: Optional[Path] = None,
    ) -> ProxyConfig:
        """Load config, skipping problematic plugin when safe to do so.

        Args:
            config_dict: Original configuration dictionary
            error: The ConfigError that occurred
            config_directory: Directory containing the configuration file (for path resolution)

        Returns:
            ProxyConfig: Loaded configuration with problematic plugin disabled

        Raises:
            ConfigError: If error type cannot be safely ignored
        """
        if error.error_type != "missing_plugin":
            raise ConfigError(
                message=f"Cannot ignore {error.error_type} errors - only missing plugins can be safely ignored",
                error_type="validation_error",
                suggestions=["Fix the underlying issue", "Edit the configuration file"],
            )

        # Modify config dict to disable the problematic plugin (deep copy to avoid mutating original)
        modified_config = self._disable_plugin_entry(
            copy.deepcopy(config_dict), error.field_path
        )
        return self.load_from_dict(modified_config, config_directory)

    def _disable_plugin_entry(self, config_dict: dict, field_path: str) -> dict:
        """Remove or disable problematic plugin entry from config.

        Args:
            config_dict: Configuration dictionary to modify
            field_path: Path to the problematic plugin (e.g., "plugins.auditing.bad_plugin")

        Returns:
            Modified configuration dictionary with plugin disabled
        """
        # Parse the field path to find the plugin
        # Expected format: "plugins.{category}.{plugin_name}"
        path_parts = field_path.split(".")
        if len(path_parts) < 3 or path_parts[0] != "plugins":
            # If path format is unexpected, return original config
            return config_dict

        category = path_parts[1]  # 'security' or 'auditing'
        plugin_name = path_parts[2]  # plugin handler name

        # Navigate to the plugins section
        if "plugins" not in config_dict:
            return config_dict

        if category not in config_dict["plugins"]:
            return config_dict

        # Find and remove/disable the problematic plugin
        category_config = config_dict["plugins"][category]

        # Handle both upstream-scoped and direct plugin configurations
        for scope_key in category_config:
            if isinstance(category_config[scope_key], list):
                # Filter out plugins with the problematic handler name
                category_config[scope_key] = [
                    plugin
                    for plugin in category_config[scope_key]
                    if plugin.get("handler") != plugin_name
                ]

        return config_dict

    def retry_with_plugin_ignore(self, error: ConfigError) -> ProxyConfig:
        """Convenience method to retry loading with plugin ignore using stored config.

        Args:
            error: The ConfigError that occurred during initial load

        Returns:
            ProxyConfig: Loaded configuration with problematic plugin disabled

        Raises:
            ConfigError: If no stored config available or error type cannot be ignored
        """
        if self._last_config_dict is None:
            raise ConfigError(
                message="No stored configuration available for retry",
                error_type="validation_error",
                suggestions=[
                    "Load a configuration first",
                    "Use load_with_plugin_ignore() directly",
                ],
            )

        return self.load_with_plugin_ignore(
            self._last_config_dict, error, self._last_config_directory
        )
