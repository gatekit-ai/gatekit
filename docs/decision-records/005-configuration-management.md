# ADR-005: Configuration Management Design

**Last Validated**: 2026-01-17 - Updated to reflect current implementation (env var overrides not implemented, upstream config simplified).

## Context

Gatekit requires flexible configuration management to support:

1. **Security Policies**: Configurable filtering rules and security parameters
2. **Server Connections**: Dynamic configuration of upstream MCP servers
3. **Transport Settings**: Different transport types with specific parameters
4. **Environment Adaptation**: Different settings for dev/staging/production
5. **Runtime Updates**: Some configurations may need dynamic updates
6. **Type Safety**: Prevent configuration errors that could impact security
7. **Plugin Extensibility**: Support for varied plugin configurations with proper validation

The configuration system must balance flexibility, type safety, ease of use, and extensibility.

## Decision

We will implement a **hybrid configuration system** that combines the strengths of Python dataclasses and Pydantic models:

### 1. Pydantic Models for Configuration Input/Validation

Pydantic models will handle the initial loading and validation of configuration from YAML files. This provides:

- Strong validation of user input with clear error messages
- Schema validation for complex, nested structures
- Type coercion for configuration values
- Support for default values and complex constraints

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# Pydantic schemas for YAML validation
class UpstreamConfigSchema(BaseModel):
    """Schema for validating upstream server configuration."""
    name: str
    command: Optional[List[str]] = None  # For stdio transport
    url: Optional[str] = None  # For http transport
    # Note: 'env' field is NOT supported - environment variables should be
    # set in your MCP client configuration or shell environment

class PluginConfigSchema(BaseModel):
    """Schema for validating plugin configuration.

    Uses a consolidated format where all fields (enabled, priority, and
    plugin-specific config) are stored in the config dict.
    """
    handler: str  # Plugin handler name
    config: Dict[str, Any] = Field(default_factory=dict)  # Contains enabled, priority, and plugin-specific fields
    
class PluginsConfigSchema(BaseModel):
    """Schema for validating all plugin configurations.

    Uses upstream-scoped format where plugins are organized by scope
    (e.g., '_global' for all servers, or specific server names).
    """
    security: Dict[str, List[PluginConfigSchema]] = Field(default_factory=dict)
    auditing: Dict[str, List[PluginConfigSchema]] = Field(default_factory=dict)
    middleware: Dict[str, List[PluginConfigSchema]] = Field(default_factory=dict)
```

### 2. Dataclasses for Internal Representation

After validation, configurations are converted to immutable dataclasses for internal use:

- Lightweight representation with no runtime dependencies
- Consistent with Python standard library
- Clear type hints for IDE support and static analysis
- Immutability to prevent accidental modification

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class UpstreamConfig:
    """Internal representation of upstream server configuration."""
    name: str
    command: Optional[List[str]] = None  # For stdio transport
    url: Optional[str] = None  # For http transport

    @classmethod
    def from_schema(cls, schema: UpstreamConfigSchema) -> 'UpstreamConfig':
        """Create from validated schema."""
        return cls(
            name=schema.name,
            command=schema.command,
            url=schema.url
        )

@dataclass
class PluginConfig:
    """Internal representation of plugin configuration.

    Framework-level fields (enabled, priority) are stored in the config dict
    alongside plugin-specific configuration, providing a single source of truth.
    """
    handler: str  # Plugin handler name
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        """Get enabled state. Defaults to True if not specified."""
        return self.config.get("enabled", True)

    @property
    def priority(self) -> int:
        """Get execution priority (0-100, lower = higher priority)."""
        return self.config.get("priority", 50)

    # Note: The 'critical' flag is accessed directly from config dict
    # by plugins via config.get("critical", True). See ADR-006 for details.

    @classmethod
    def from_schema(cls, schema: PluginConfigSchema) -> 'PluginConfig':
        """Create from validated schema."""
        return cls(
            handler=schema.handler,
            config=dict(schema.config)
        )
```

### 3. Configuration Loading Pipeline

The configuration pipeline follows these steps:

1. Load YAML from file
2. Parse into Pydantic schema objects for validation
3. Convert validated schemas to internal dataclasses 
4. Use dataclass instances throughout the application

```python
# Example configuration loading pipeline
def load_config(path: Path) -> ProxyConfig:
    """Load configuration from YAML file."""
    # 1. Load and parse YAML
    with open(path, 'r') as f:
        data = yaml.safe_load(f)
    
    # 2. Validate with Pydantic schema
    config_schema = ProxyConfigSchema(**data)
    
    # 3. Convert to dataclass for internal use
    return ProxyConfig.from_schema(config_schema)
```

## Alternatives Considered

### Alternative 1: Pure Dataclasses Approach
```python
@dataclass
class ServerConfig:
    """Configuration for an upstream MCP server."""
    name: str
    command: List[str]
    timeout: int = 30
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.command:
            raise ValueError("Server command cannot be empty")
```
- **Pros**: Standard library only, no dependencies, lightweight
- **Cons**: Manual validation in `__post_init__`, limited validation features, error messages not as user-friendly

### Alternative 2: Pure Pydantic Approach
```python
from pydantic import BaseModel, Field, validator

class ServerConfig(BaseModel):
    name: str
    command: List[str]
    timeout: int = Field(default=30, gt=0)
    
    @validator('command')
    def command_not_empty(cls, v):
        if not v:
            raise ValueError("Server command cannot be empty")
        return v
```
- **Pros**: Rich validation, excellent error messages, JSON schema support
- **Cons**: Additional dependency for the entire application, performance overhead

### Alternative 3: Dictionary-Based Configuration
```python
# Simple dictionary approach
config = {
    "servers": [
        {"name": "server1", "command": ["python", "server.py"]},
        {"name": "server2", "command": ["node", "server.js"]}
    ],
    "security": {
        "allowed_methods": ["ping", "tools/list"],
        "rate_limit": 100
    }
}
```
- **Pros**: Simple, flexible, familiar
- **Cons**: No type safety, runtime errors, hard to validate

### Alternative 4: Configuration Classes with Properties
```python
class Config:
    def __init__(self, config_dict):
        self._config = config_dict
    
    @property
    def servers(self):
        return self._config.get('servers', [])
```
- **Pros**: Encapsulation, lazy loading
- **Cons**: No type hints, manual property implementation

### Alternative 5: Environment Variables Only
```python
import os

ALLOWED_METHODS = os.getenv('GATEKIT_ALLOWED_METHODS', '').split(',')
RATE_LIMIT = int(os.getenv('GATEKIT_RATE_LIMIT', '100'))
```
- **Pros**: 12-factor app compliance, simple deployment
- **Cons**: Limited structure, difficult complex configurations

## Consequences

### Positive
- **Strong Input Validation**: Pydantic provides robust validation with clear error messages
- **Type Safety**: Compile-time checking prevents configuration errors through the system
- **IDE Support**: Auto-completion and type hints in both validation and internal models
- **Separation of Concerns**: Clear distinction between external validation and internal representation
- **Extensibility**: Pydantic's validation capabilities support complex plugin configuration needs
- **Testability**: Easy to create and validate test configurations
- **Immutability**: Internal dataclass models prevent accidental configuration changes

### Negative
- **Additional Dependency**: Introduces Pydantic as a project dependency
- **Conversion Overhead**: Small performance cost to convert between validation and internal models
- **Two Systems to Maintain**: Need to keep Pydantic schemas and dataclasses in sync
- **Learning Curve**: Team must understand both Pydantic and dataclass patterns
- **Schema Evolution**: Requires careful handling of breaking changes in both systems

## Implementation Examples

### Configuration Loading Pipeline

```python
class ConfigLoader:
    """YAML configuration file loader with hybrid validation approach."""
    
    def load_from_file(self, path: Path) -> ProxyConfig:
        """Load configuration from YAML file."""
        try:
            # 1. Load YAML content
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
            # 2. Parse YAML into dictionary
            if not content:
                raise ValueError("Configuration file is empty")
                
            config_dict = yaml.safe_load(content)
            
            if config_dict is None:
                raise ValueError("Configuration file contains only comments or is empty")
                
            # 3. Validate with Pydantic schema
            proxy_schema = ProxyConfigSchema(**config_dict)
            
            # 4. Convert to dataclass for internal use
            return ProxyConfig.from_schema(proxy_schema)
            
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML syntax: {e}")
        except ValidationError as e:
            raise ValueError(f"Invalid configuration: {e}")
        except Exception as e:
            raise ValueError(f"Error loading configuration: {e}")
```

### Plugin Configuration Example

```python
# 1. Pydantic schema for plugin configuration validation
class PluginConfigSchema(BaseModel):
    """Schema for validating plugin configuration.

    Consolidated format: enabled, priority, and plugin-specific fields
    are all stored in the config dict.
    """
    handler: str  # Plugin handler name
    config: Dict[str, Any] = Field(default_factory=dict)

class PluginsConfigSchema(BaseModel):
    """Schema for validating all plugin configurations."""
    security: Dict[str, List[PluginConfigSchema]] = Field(default_factory=dict)  # Upstream-scoped
    auditing: Dict[str, List[PluginConfigSchema]] = Field(default_factory=dict)  # Upstream-scoped
    middleware: Dict[str, List[PluginConfigSchema]] = Field(default_factory=dict)  # Upstream-scoped

# 2. Dataclass for internal representation
@dataclass
class PluginConfig:
    """Internal dataclass representation of plugin configuration.

    Framework-level fields (enabled, priority) are stored in the config dict
    alongside plugin-specific configuration. Properties provide convenient access.
    """
    handler: str
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled", True)

    @property
    def priority(self) -> int:
        return self.config.get("priority", 50)

    @classmethod
    def from_schema(cls, schema: PluginConfigSchema) -> 'PluginConfig':
        return cls(
            handler=schema.handler,
            config=dict(schema.config)
        )

# 3. Usage example in PluginManager
class PluginManager:
    def __init__(self, plugins_config: Dict[str, Any]):
        # Convert from dictionary to Pydantic model for validation
        plugins_schema = PluginsConfigSchema(**plugins_config)
        
        # Convert validated schemas to internal dataclasses
        self.security_plugins_config = [
            PluginConfig.from_schema(schema) 
            for schema in plugins_schema.security
        ]
        self.auditing_plugins_config = [
            PluginConfig.from_schema(schema)
            for schema in plugins_schema.auditing
        ]
```

### Logging Configuration

Gatekit supports configurable logging for system events (distinct from auditing plugins which log MCP traffic):

```python
@dataclass
class LoggingConfig:
    """Internal representation of logging configuration."""
    level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR
    handlers: List[str] = field(default_factory=lambda: ["stderr"])  # stderr, file
    file_path: Optional[Path] = None  # Required if "file" in handlers
    max_file_size_mb: int = 10
    backup_count: int = 5
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
```

Logging configuration in YAML:
```yaml
proxy:
  logging:
    level: "INFO"
    handlers: ["stderr", "file"]
    file_path: "logs/gatekit.log"  # Relative to config file location
    max_file_size_mb: 10
    backup_count: 5
```

### Complete Configuration Example (YAML)

```yaml
# gatekit.yaml example with all sections
proxy:
  transport: "stdio"  # "stdio" or "http"

  # Upstream server settings
  upstream:
    command: ["python", "-m", "mcp_server"]
    restart_on_failure: true
    max_restart_attempts: 3

  # Connection timeouts
  timeouts:
    connection_timeout: 30
    request_timeout: 60

  # HTTP transport settings (when transport is "http")
  http:
    host: "127.0.0.1"
    port: 8080

  # System logging (distinct from auditing)
  logging:
    level: "INFO"
    handlers: ["stderr"]

  # Plugin configuration section (upstream-scoped)
  plugins:
    # Security plugins
    security:
      _global:  # Global plugins apply to all upstreams
        - handler: "basic_pii_filter"
          config:
            enabled: true
            priority: 50
            critical: true  # Default: fail-closed on errors
            action: "redact"

        - handler: "basic_secrets_filter"
          config:
            enabled: true
            priority: 60
            critical: false  # Opt-out: log errors but continue
            action: "redact"

    # Auditing plugins
    auditing:
      _global:
        - handler: "file_auditing"
          config:
            enabled: true
            priority: 50
            file: "gatekit.log"
            max_size_mb: 10
            format: "json"  # json or text

        - handler: "database_logger"
          config:
            enabled: false  # Disabled plugin
            priority: 50
            connection_string: "sqlite:///audit.db"
            batch_size: 100
```

### Environment Variables

**Note**: Environment variable overrides for configuration (`AG_` prefix) are **not currently implemented**. This was a planned feature that has not been built yet.

For environment variables needed by upstream MCP servers:
- Set them in your shell environment before running Gatekit
- Or configure them in your MCP client's server configuration
- Gatekit upstream configurations do NOT support an `env` field

### Schema Evolution Strategy

Our hybrid approach facilitates configuration schema evolution through version tracking and migration functions:

```python
class ProxyConfigSchema(BaseModel):
    """Schema for proxy configuration with version support."""
    version: str = "1.0"
    transport: str
    upstream: UpstreamConfigSchema
    timeouts: TimeoutConfigSchema
    http: Optional[HttpConfigSchema] = None
    plugins: Optional[PluginsConfigSchema] = None
    
    @validator('version')
    def validate_version(cls, v):
        """Validate configuration version."""
        if v not in ["0.9", "1.0"]:
            raise ValueError(f"Unsupported configuration version: {v}")
        return v
    
    def apply_migrations(self):
        """Apply migrations based on configuration version."""
        if self.version == "0.9":
            # Convert v0.9 to v1.0 format
            if not hasattr(self, 'plugins'):
                self.plugins = PluginsConfigSchema()
            # Other migration logic...
            self.version = "1.0"
        return self
```

## Testing Strategy

The hybrid configuration system can be thoroughly tested at multiple levels:

```python
# Unit testing the validation layer
def test_plugin_config_schema_validation():
    """Test Pydantic validation for plugin configuration."""
    # Valid configuration (consolidated format)
    valid_config = {
        "handler": "test_plugin",
        "config": {"enabled": True, "priority": 50, "key": "value"}
    }
    schema = PluginConfigSchema(**valid_config)
    assert schema.handler == "test_plugin"
    assert schema.config["enabled"] is True

    # Invalid configuration (missing required field)
    invalid_config = {"config": {"enabled": True}}
    with pytest.raises(ValidationError):
        PluginConfigSchema(**invalid_config)

# Testing the conversion to internal dataclasses
def test_plugin_config_conversion():
    """Test conversion from schema to dataclass."""
    schema = PluginConfigSchema(
        handler="test_plugin",
        config={"enabled": False, "priority": 30, "setting": 123}
    )
    dataclass_config = PluginConfig.from_schema(schema)

    assert isinstance(dataclass_config, PluginConfig)
    assert dataclass_config.handler == "test_plugin"
    assert dataclass_config.enabled is False  # Property access
    assert dataclass_config.priority == 30  # Property access
    assert dataclass_config.config["setting"] == 123

# Integration testing with YAML files
def test_config_loading_from_yaml(tmp_path):
    """Test loading configuration from YAML file."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
    proxy:
      transport: stdio
      upstream:
        command: ["python", "-m", "server"]
      timeouts:
        connection_timeout: 30
        request_timeout: 60
      plugins:
        security:
          _global:
            - handler: test_plugin
              config:
                enabled: true
                priority: 50
                mode: test
    """)

    config = ConfigLoader().load_from_file(config_file)
    assert config.transport == "stdio"
    assert len(config.plugins.security["_global"]) == 1
    assert config.plugins.security["_global"][0].handler == "test_plugin"
    assert config.plugins.security["_global"][0].enabled is True
```

## Review and Evolution

This hybrid configuration management approach addresses the needs of both stability (through dataclasses) and flexibility (through Pydantic schemas). It provides a solid foundation for Gatekit's configuration requirements while enabling the extensibility needed for plugins.

### Key Benefits Realized
- **Type Safety** throughout the configuration pipeline
- **Clear Error Messages** for configuration issues
- **Extensibility** for plugin configuration
- **Separation of Concerns** between validation and internal representation

### Additional Considerations
- Configuration update API for runtime changes
- Schema versioning for backward compatibility as the system evolves
- Generating JSON schema from Pydantic models for configuration documentation
- Performance impact of the validation and conversion process

This approach may need adjustment when:
- Configuration schema complexity increases significantly
- New validation requirements emerge that are challenging to implement
- Performance profiling indicates overhead concerns
- Additional configuration sources beyond YAML files are needed
