"""Domain-specific exceptions for Gatekit.

This module provides specialized exception classes for different components
of Gatekit, enabling more precise error handling and better debugging.
"""

from typing import Optional, Any


# Base Exceptions


class GatekitError(Exception):
    """Base exception for all Gatekit-specific errors."""

    pass


# Configuration Exceptions


class ConfigurationError(GatekitError):
    """Base exception for configuration-related errors."""

    pass


class ConfigValidationError(ConfigurationError):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        self.field = field
        self.value = value
        super().__init__(message)


class ConfigLoadError(ConfigurationError):
    """Raised when configuration cannot be loaded."""

    pass


# Plugin Exceptions


class PluginError(GatekitError):
    """Base exception for plugin-related errors."""

    pass


class PluginLoadError(PluginError):
    """Raised when a plugin cannot be loaded."""

    def __init__(self, plugin_name: str, reason: str):
        self.plugin_name = plugin_name
        self.reason = reason
        super().__init__(f"Failed to load plugin '{plugin_name}': {reason}")


class PluginValidationError(PluginError):
    """Raised when plugin configuration is invalid."""

    pass
