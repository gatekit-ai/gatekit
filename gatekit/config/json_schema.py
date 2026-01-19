"""Centralized JSON Schema validation for Gatekit."""

from typing import Dict, Any, List, Optional
import logging
from jsonschema import Draft202012Validator

from .framework_fields import inject_framework_fields

logger = logging.getLogger(__name__)


class SchemaValidator:
    """Centralized validator supporting JSON Schema 2020-12."""

    def __init__(self):
        self.validator_class = Draft202012Validator
        self.validators: Dict[str, Draft202012Validator] = {}
        # Load schemas dynamically
        self._load_schemas()

    def _load_schemas(self):
        """Load all plugin schemas dynamically.

        Framework fields (enabled, priority) are injected into each schema
        before creating validators. This ensures validation accepts the
        same fields that the TUI config adapter injects for form display.

        See ADR-005 for the consolidated configuration architecture.
        """
        from gatekit.plugins.manager import PluginManager
        from gatekit.plugins.interfaces import PluginInterface

        # Discover all plugins via the plugin manager
        pm = PluginManager({})

        # Discover handlers for each category, preserving category info
        for category in ["security", "auditing", "middleware"]:
            handlers = pm._discover_handlers(category)

            for handler_name, plugin_class in handlers.items():
                # Only register schemas that override the base implementation
                if (
                    hasattr(plugin_class, "get_json_schema")
                    and plugin_class.get_json_schema is not PluginInterface.get_json_schema
                ):
                    try:
                        schema = plugin_class.get_json_schema()

                        # Inject framework fields based on plugin category
                        # - Auditing: only enabled (no priority)
                        # - Security/Middleware: enabled + priority
                        schema = inject_framework_fields(schema, category)

                        # Use Draft202012Validator explicitly
                        self.validators[handler_name] = Draft202012Validator(schema)
                        logger.debug(
                            f"Loaded JSON Schema for handler '{handler_name}' "
                            f"(category: {category})"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to load schema for '{handler_name}': {e}")

    def validate(self, handler_name: str, config: Dict[str, Any]) -> List[str]:
        """Validate a plugin configuration.

        Returns list of error messages with JSON pointer paths for context.
        """
        if handler_name not in self.validators:
            return [f"No schema found for handler '{handler_name}'"]

        validator = self.validators[handler_name]
        errors = []

        for error in validator.iter_errors(config):
            # Include JSON pointer path for better error context
            error_path = (
                "/" + "/".join(str(p) for p in error.absolute_path)
                if error.absolute_path
                else "/"
            )
            errors.append(f"At {error_path}: {error.message}")

        return errors

    def is_valid(self, handler_name: str, config: Dict[str, Any]) -> bool:
        """Check if a plugin configuration is valid.

        Returns True if valid, False otherwise.
        """
        return len(self.validate(handler_name, config)) == 0

    def get_schema(self, handler_name: str) -> Optional[Dict[str, Any]]:
        """Get the JSON Schema for a specific handler.

        Returns the schema dict or None if not found.
        """
        if handler_name in self.validators:
            return self.validators[handler_name].schema
        return None

    def has_schema(self, handler_name: str) -> bool:
        """Check if a schema exists for the given handler.

        Returns False for plugins that haven't implemented get_json_schema().
        This allows custom plugins to work without schemas.
        """
        return handler_name in self.validators


# Module-level singleton for performance
_schema_validator_instance: Optional[SchemaValidator] = None


def get_schema_validator() -> SchemaValidator:
    """Get cached SchemaValidator instance.

    Avoids repeated plugin discovery on every config load.
    """
    global _schema_validator_instance
    if _schema_validator_instance is None:
        _schema_validator_instance = SchemaValidator()
    return _schema_validator_instance


def clear_validator_cache() -> None:
    """Clear the cached validator (for testing or reload).

    Tests use this to reset plugin discovery state between test runs.
    """
    global _schema_validator_instance
    _schema_validator_instance = None
