"""Configuration models for Gatekit MCP Gateway."""

import re
import importlib.util
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union, Literal
from pathlib import Path
from pydantic import BaseModel, Field, HttpUrl, model_validator, field_validator

from gatekit.utils.paths import resolve_config_path


# Pydantic schemas for YAML validation (ADR-005)
class LoggingConfigSchema(BaseModel):
    """Schema for validating logging configuration."""

    level: str = "INFO"
    handlers: List[str] = Field(default_factory=lambda: ["stderr"])
    file_path: Optional[str] = None
    max_file_size_mb: float = 10  # Size limit before rotating to a new log file
    backup_count: int = 5  # Number of rotated log files to keep (log.1, log.2, etc.)
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = (
        "%Y-%m-%d %H:%M:%S"  # Standard format, timezone handled by logging configuration
    )


class PluginConfigSchema(BaseModel):
    """Schema for validating plugin configuration.

    Plugin configuration uses a flat structure where all fields (including
    framework-level fields like 'enabled' and 'priority') are stored in the
    config dict. This provides a single source of truth and simplifies
    configuration management.

    Extra fields are forbidden to catch configuration errors early.
    """
    model_config = {"extra": "forbid"}

    handler: str  # Handler name for plugin (required)
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def validate_priority_range(cls, v):
        """Validate priority is within valid range (0-100) if specified."""
        if "priority" in v:
            priority = v["priority"]
            if not isinstance(priority, int) or not (0 <= priority <= 100):
                raise ValueError(
                    f"Plugin priority must be an integer between 0 and 100, got {priority}"
                )
        return v


class PluginsConfigSchema(BaseModel):
    """Schema for validating upstream-scoped plugin configurations.

    Uses a dictionary-based structure where:
    - `_global` key contains policies for all upstreams (optional)
    - Individual upstream names are keys with their specific policies
    - Upstream-specific policies override global ones with same name
    """

    security: Optional[Dict[str, List[PluginConfigSchema]]] = Field(
        default_factory=dict
    )
    auditing: Optional[Dict[str, List[PluginConfigSchema]]] = Field(
        default_factory=dict
    )
    middleware: Optional[Dict[str, List[PluginConfigSchema]]] = Field(
        default_factory=dict
    )

    @field_validator("security", "auditing", "middleware")
    @classmethod
    def validate_upstream_keys(cls, v, info):
        """Validate upstream keys - only accepts dictionary format."""
        if not v:  # Empty value is valid
            return {}

        # Only accept dictionary format
        if not isinstance(v, dict):
            raise TypeError(
                "Plugin configuration must be a dictionary with upstream keys (e.g., {'_global': [...]})"
            )

        validated_dict = {}

        for key, policies in v.items():
            # Skip special keys
            if key.startswith("_"):
                if key == "_global":
                    validated_dict[key] = policies  # Valid special key
                    continue
                else:
                    # Ignored keys (e.g., for YAML anchors) - don't include in result
                    continue

            # Validate upstream key naming pattern
            if not re.match(r"^[a-z][a-z0-9_-]*$", key):
                raise ValueError(
                    f"Invalid upstream key '{key}': must be lowercase alphanumeric "
                    f"with hyphens/underscores (pattern: ^[a-z][a-z0-9_-]*$)"
                )

            # Validate that key doesn't contain double underscores (reserved for namespace delimiter)
            if "__" in key:
                raise ValueError(
                    f"Invalid upstream key '{key}': cannot contain '__' (reserved for namespace delimiter)"
                )

            validated_dict[key] = policies

            # Note: Upstream existence validation happens at ProxyConfigSchema level
            # where we have access to the full upstreams configuration

        return validated_dict


# Dataclasses for internal representation (ADR-005)
@dataclass
class LoggingConfig:
    """Internal representation of logging configuration."""

    level: str = "INFO"
    handlers: List[str] = field(default_factory=lambda: ["stderr"])
    file_path: Optional[Path] = None
    max_file_size_mb: float = 10  # Size limit before rotating to a new log file
    backup_count: int = 5  # Number of rotated log files to keep (log.1, log.2, etc.)
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format: str = (
        "%Y-%m-%d %H:%M:%S"  # Standard format, timezone handled by logging configuration
    )

    def __post_init__(self):
        """Validate configuration after initialization."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.level.upper() not in valid_levels:
            raise ValueError(
                f"Invalid log level: {self.level}. Must be one of {valid_levels}"
            )

        # Normalize level to uppercase
        self.level = self.level.upper()

        valid_handlers = {"stderr", "file"}
        for handler in self.handlers:
            if handler not in valid_handlers:
                raise ValueError(
                    f"Invalid handler: {handler}. Must be one of {valid_handlers}"
                )

        if "file" in self.handlers and self.file_path is None:
            raise ValueError("file_path is required when using file handler")

        if self.max_file_size_mb <= 0:
            raise TypeError("max_file_size_mb must be positive")

        if self.backup_count < 0:
            raise TypeError("backup_count must be non-negative")

    @classmethod
    def from_schema(
        cls, schema: LoggingConfigSchema, config_directory: Optional[Path] = None
    ) -> "LoggingConfig":
        """Create from validated Pydantic schema.

        Args:
            schema: Validated logging configuration schema
            config_directory: Directory containing the configuration file (for path resolution)
        """
        # Resolve file_path relative to config directory if provided
        file_path = None
        if schema.file_path:
            if config_directory is not None:
                file_path = resolve_config_path(schema.file_path, config_directory)
            else:
                file_path = Path(schema.file_path)

        return cls(
            level=schema.level,
            handlers=schema.handlers,
            file_path=file_path,
            max_file_size_mb=schema.max_file_size_mb,
            backup_count=schema.backup_count,
            format=schema.format,
            date_format=schema.date_format,
        )


@dataclass
class PluginConfig:
    """Internal representation of plugin configuration.

    Framework-level fields (enabled, priority) are stored in the config dict
    alongside plugin-specific configuration. Properties provide convenient access
    with sensible defaults while maintaining a single source of truth.
    """

    handler: str  # Handler name for handler-based system
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        """Get enabled state. Defaults to True if not specified."""
        return self.config.get("enabled", True)

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Set enabled state."""
        self.config["enabled"] = value

    @property
    def priority(self) -> int:
        """Get execution priority (0-100, lower = higher priority). Defaults to 50."""
        return self.config.get("priority", 50)

    @priority.setter
    def priority(self, value: int) -> None:
        """Set execution priority with validation (0-100)."""
        if not isinstance(value, int) or not (0 <= value <= 100):
            raise TypeError(f"Priority must be 0-100, got {value}")
        self.config["priority"] = value

    @classmethod
    def from_schema(cls, schema: PluginConfigSchema) -> "PluginConfig":
        """Create from validated Pydantic schema.

        All configuration (framework and plugin-specific) is in the config dict.
        """
        return cls(
            handler=schema.handler,
            config=dict(schema.config),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.

        Returns the consolidated format where enabled and priority are stored
        in the config dict, not as top-level fields.
        """
        return {
            "handler": self.handler,
            "config": self.config,
        }


@dataclass
class PluginsConfig:
    """Internal representation of upstream-scoped plugin configurations."""

    security: Dict[str, List[PluginConfig]] = field(default_factory=dict)
    auditing: Dict[str, List[PluginConfig]] = field(default_factory=dict)
    middleware: Dict[str, List[PluginConfig]] = field(default_factory=dict)

    @classmethod
    def from_schema(cls, schema: PluginsConfigSchema) -> "PluginsConfig":
        """Create from validated Pydantic schema."""
        # Convert dictionary of upstream -> plugin lists to internal format
        security_dict = {}
        for upstream, plugins in (schema.security or {}).items():
            security_dict[upstream] = [PluginConfig.from_schema(p) for p in plugins]

        auditing_dict = {}
        for upstream, plugins in (schema.auditing or {}).items():
            auditing_dict[upstream] = [PluginConfig.from_schema(p) for p in plugins]

        middleware_dict = {}
        for upstream, plugins in (schema.middleware or {}).items():
            middleware_dict[upstream] = [PluginConfig.from_schema(p) for p in plugins]

        return cls(
            security=security_dict, auditing=auditing_dict, middleware=middleware_dict
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        security_dict = {}
        for upstream, plugins in self.security.items():
            security_dict[upstream] = [plugin.to_dict() for plugin in plugins]

        auditing_dict = {}
        for upstream, plugins in self.auditing.items():
            auditing_dict[upstream] = [plugin.to_dict() for plugin in plugins]

        middleware_dict = {}
        for upstream, plugins in self.middleware.items():
            middleware_dict[upstream] = [plugin.to_dict() for plugin in plugins]

        return {
            "security": security_dict,
            "auditing": auditing_dict,
            "middleware": middleware_dict,
        }


class UpstreamConfigSchema(BaseModel):
    """Schema for validating upstream MCP server configuration."""

    name: str  # Mandatory server name for consistent behavior
    transport: Literal["stdio", "http"] = "stdio"
    command: Optional[List[str]] = None  # For stdio transport
    url: Optional[HttpUrl] = None  # For http transport
    restart_on_failure: bool = True
    max_restart_attempts: int = 3
    server_identity: Optional[str] = None  # MCP-reported server name from handshake

    @model_validator(mode="after")
    def validate_and_normalize_command(self) -> "UpstreamConfigSchema":
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires 'command'")
        if self.transport == "http" and not self.url:
            raise ValueError("http transport requires 'url'")

        # Enforce list-of-string format explicitly
        if self.command is not None:
            if not isinstance(self.command, list):
                raise TypeError(
                    "'command' must be a list of arguments (e.g., ['npx', 'server', '/path'])"
                )
            if not all(isinstance(arg, str) for arg in self.command):
                raise TypeError("Each entry in 'command' must be a string")
            if not self.command:
                raise ValueError("'command' cannot be an empty list")

        # Normalize server identity (strip whitespace, drop empty strings)
        if self.server_identity is not None:
            normalized_identity = self.server_identity.strip()
            self.server_identity = normalized_identity or None

        return self


@dataclass
class UpstreamConfig:
    """Configuration for upstream MCP server.

    Attributes:
        name: Mandatory server name for consistent behavior
        transport: Transport type ("stdio" or "http")
        command: List of command line arguments to start the MCP server
        url: URL for HTTP transport
        restart_on_failure: Whether to restart the server if it fails
        max_restart_attempts: Maximum number of restart attempts
    """

    name: str
    transport: str = "stdio"
    command: Optional[List[str]] = None
    url: Optional[str] = None
    restart_on_failure: bool = True
    max_restart_attempts: int = 3
    is_draft: bool = False
    server_identity: Optional[str] = None  # Last-known MCP handshake name

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.is_draft:
            return

        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires 'command'")
        if self.transport == "http" and not self.url:
            raise ValueError("http transport requires 'url'")

        if self.server_identity is not None:
            self.server_identity = self.server_identity.strip() or None

    @classmethod
    def from_schema(cls, schema: UpstreamConfigSchema) -> "UpstreamConfig":
        """Create from validated Pydantic schema."""
        return cls(
            name=schema.name,
            transport=schema.transport,
            command=schema.command,
            url=str(schema.url) if schema.url else None,
            restart_on_failure=schema.restart_on_failure,
            max_restart_attempts=schema.max_restart_attempts,
            is_draft=False,
            server_identity=schema.server_identity,
        )

    @classmethod
    def create_draft(
        cls,
        name: str,
        transport: str = "stdio",
        *,
        restart_on_failure: bool = True,
        max_restart_attempts: int = 3,
        server_identity: Optional[str] = None,
    ) -> "UpstreamConfig":
        """Construct a draft upstream that can be completed by the editor before validation.

        Draft upstreams intentionally skip transport-specific validation so the TUI can
        present an empty detail form without requiring a command or URL upfront.
        """

        normalized_identity = server_identity.strip() if server_identity else None

        return cls(
            name=name,
            transport=transport,
            command=None,
            url=None,
            restart_on_failure=restart_on_failure,
            max_restart_attempts=max_restart_attempts,
            is_draft=True,
            server_identity=normalized_identity,
        )


@dataclass
class TimeoutConfig:
    """Timeout configuration for connections and requests.

    Attributes:
        connection_timeout: Timeout for establishing connections (seconds)
        request_timeout: Timeout for individual requests (seconds)
    """

    connection_timeout: int = 60
    request_timeout: int = 60

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.connection_timeout <= 0 or self.request_timeout <= 0:
            raise TypeError("Timeout values must be positive")


@dataclass
class HttpConfig:
    """HTTP transport configuration.

    Attributes:
        host: Host address to bind the HTTP server to
        port: Port number to bind the HTTP server to
    """

    host: str = "127.0.0.1"
    port: int = 8080

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not (1 <= self.port <= 65535):
            raise TypeError("Port must be between 1 and 65535")


class ProxyConfigSchema(BaseModel):
    """Schema for validating main proxy configuration."""

    transport: Literal["stdio", "http"]
    upstreams: Optional[Union[UpstreamConfigSchema, List[UpstreamConfigSchema]]] = None
    timeouts: Optional[Dict[str, Any]] = None
    http: Optional[Dict[str, Any]] = None
    plugins: Optional[PluginsConfigSchema] = None
    logging: Optional[LoggingConfigSchema] = None

    @model_validator(mode="after")
    def validate_upstreams_and_plugins(self) -> "ProxyConfigSchema":
        if not self.upstreams:
            raise TypeError("At least one upstream server must be configured")

        # Normalize single upstream to list
        if not isinstance(self.upstreams, list):
            self.upstreams = [self.upstreams]

        # All servers must have names
        for i, upstream in enumerate(self.upstreams):
            if not upstream.name:
                raise ValueError(
                    f"All upstream servers must have a 'name'. Server at index {i} is missing a name."
                )

        # Names must be unique
        names = [u.name for u in self.upstreams]
        if len(names) != len(set(names)):
            raise TypeError("Upstream server names must be unique")

        # Validate server names - check for __ separator (namespace delimiter)
        for upstream in self.upstreams:
            if "__" in upstream.name:
                raise ValueError(f"Server name '{upstream.name}' cannot contain '__'")

        # Validate plugin configurations
        if self.plugins:
            server_names = set(u.name for u in self.upstreams)
            self._validate_plugin_server_references(self.plugins, server_names)

        return self

    def _validate_plugin_server_references(
        self, plugins: "PluginsConfigSchema", server_names: set
    ) -> None:
        """Validate that plugin configurations reference valid server names."""
        # Handle new dictionary-based structure
        all_plugin_sections = []
        if plugins.security:
            all_plugin_sections.append(plugins.security)
        if plugins.auditing:
            all_plugin_sections.append(plugins.auditing)
        if plugins.middleware:
            all_plugin_sections.append(plugins.middleware)

        for plugin_section in all_plugin_sections:
            # Validate upstream keys (except _global and ignored _* keys)
            for upstream_key in plugin_section.keys():
                if upstream_key.startswith("_"):
                    if upstream_key == "_global":
                        continue  # _global is special and doesn't need to exist in upstreams
                    else:
                        continue  # Other _* keys are ignored

                # Check if upstream exists in configuration
                if upstream_key not in server_names:
                    available = ", ".join(sorted(server_names))
                    raise ValueError(
                        f"Plugin configuration references unknown upstream '{upstream_key}'. "
                        f"Available upstreams: {available}"
                    )

            # Validate individual plugin configurations within each upstream
            for upstream_key, plugin_list in plugin_section.items():
                for plugin in plugin_list:

                    # Validate plugin scope - prevent server_aware and server_specific plugins in _global section
                    if upstream_key == "_global":
                        self._validate_plugin_scope_for_global_section(plugin.handler)

    def _validate_plugin_scope_for_global_section(self, handler_name: str) -> None:
        """Validate that plugins in _global section have appropriate display scope.

        Server-aware and server-specific plugins require per-server configuration and
        cannot be meaningfully configured in the _global section.

        Args:
            handler_name: The handler name to validate

        Raises:
            ValueError: If a server_aware or server_specific plugin is configured in _global section
        """
        # Discover plugin metadata dynamically - all plugins are first-class citizens
        # Try to find the plugin in security first, then middleware
        plugin_class = self._discover_plugin_class(handler_name, "security")
        if plugin_class is None:
            plugin_class = self._discover_plugin_class(handler_name, "middleware")
        if plugin_class is None:
            # If we can't find the plugin, allow it - the plugin loading stage will catch invalid handlers
            return

        # Check the plugin's declared display scope
        display_scope = getattr(plugin_class, "DISPLAY_SCOPE", "global")

        if display_scope == "server_aware":
            raise ValueError(
                f"Plugin '{handler_name}' has scope 'server_aware' and cannot be configured "
                f"in the _global section. Server-aware plugins require per-server configuration. "
                f"Move this plugin to individual server sections instead."
            )

        if display_scope == "server_specific":
            raise ValueError(
                f"Plugin '{handler_name}' has scope 'server_specific' and cannot be configured "
                f"in the _global section. Server-specific plugins only work with compatible server types. "
                f"Move this plugin to compatible server sections instead."
            )

    def _discover_plugin_class(
        self, handler_name: str, category: str
    ) -> Optional[type]:
        """Discover a specific plugin class by handler name and category.

        This uses the same discovery mechanism as PluginManager to ensure consistency.

        Args:
            handler_name: The handler name to find
            category: Plugin category ('security', 'middleware', or 'auditing')

        Returns:
            Plugin class if found, None otherwise
        """
        try:
            # Use the same discovery logic as PluginManager._discover_policies
            # This ensures consistent behavior between config validation and plugin loading
            base_dir = Path(__file__).parent.parent / "plugins"
            plugin_dir = base_dir / category

            if not plugin_dir.exists():
                return None

            # Scan all Python files in the category directory
            for py_file in plugin_dir.glob("**/*.py"):
                if not py_file.is_file() or py_file.name.startswith("__"):
                    continue

                try:
                    # Load the module
                    module_name = py_file.stem
                    spec = importlib.util.spec_from_file_location(module_name, py_file)
                    if spec is None or spec.loader is None:
                        continue

                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Check for HANDLERS manifest
                    if hasattr(module, "HANDLERS") and isinstance(
                        module.HANDLERS, dict
                    ):
                        if handler_name in module.HANDLERS:
                            return module.HANDLERS[handler_name]

                except Exception:
                    # Ignore module loading errors during validation
                    continue

            return None

        except Exception:
            # If discovery fails, return None to allow validation to continue
            return None


@dataclass
class ProxyConfig:
    """Main proxy configuration.

    Attributes:
        transport: Transport type ("stdio" or "http")
        upstreams: List of upstream server configurations
        timeouts: Timeout configuration
        http: Optional HTTP transport configuration
        plugins: Optional plugin configuration
        logging: Optional logging configuration
    """

    transport: str
    upstreams: List[UpstreamConfig]
    timeouts: TimeoutConfig
    http: Optional[HttpConfig] = None
    plugins: Optional[PluginsConfig] = None
    logging: Optional[LoggingConfig] = None

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.transport not in ("stdio", "http"):
            raise TypeError("Transport must be 'stdio' or 'http'")

        if self.transport == "http" and self.http is None:
            raise ValueError("HTTP transport requires http configuration")

        if not self.upstreams:
            raise TypeError("At least one upstream server must be configured")

        # All server names must be unique
        names = [u.name for u in self.upstreams]
        if len(names) != len(set(names)):
            raise TypeError("Upstream server names must be unique")

        # Validate server names - check for __ separator (namespace delimiter)
        for upstream in self.upstreams:
            if "__" in upstream.name:
                raise ValueError(f"Server name '{upstream.name}' cannot contain '__'")

    @classmethod
    def from_schema(
        cls, schema: ProxyConfigSchema, config_directory: Optional[Path] = None
    ) -> "ProxyConfig":
        """Create from validated Pydantic schema."""
        # Convert upstreams
        upstreams = [UpstreamConfig.from_schema(u) for u in schema.upstreams or []]

        # Create timeouts config
        timeouts = TimeoutConfig()
        if schema.timeouts:
            timeouts = TimeoutConfig(**schema.timeouts)

        # Create HTTP config
        http = None
        if schema.http:
            http = HttpConfig(**schema.http)

        # Create plugins config
        plugins = None
        if schema.plugins:
            plugins = PluginsConfig.from_schema(schema.plugins)

        # Create logging config
        logging = None
        if schema.logging:
            logging = LoggingConfig.from_schema(schema.logging, config_directory)

        return cls(
            transport=schema.transport,
            upstreams=upstreams,
            timeouts=timeouts,
            http=http,
            plugins=plugins,
            logging=logging,
        )

    @classmethod
    def create_empty_for_editing(cls) -> "ProxyConfig":
        """Create an empty config for TUI editing (bypasses validation).

        Used for "Create New" workflow where config starts empty and
        validation happens at save time.

        Returns:
            ProxyConfig instance with empty upstreams list and default values.
        """
        # Use object.__new__ to bypass __post_init__ validation
        instance = object.__new__(cls)
        instance.transport = "stdio"
        instance.upstreams = []
        instance.timeouts = TimeoutConfig()
        instance.http = None
        instance.plugins = None
        instance.logging = None
        return instance
