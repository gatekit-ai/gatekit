# ADR-012: Configuration Path Resolution Strategy

## Context

Gatekit configurations contained relative paths that were resolved relative to the current working directory where the MCP client started Gatekit. This created several problems:

1. **Unpredictable behavior**: Users couldn't reliably use relative paths because they don't control the working directory when Gatekit runs as an MCP server
2. **Tutorial failures**: Sample configurations with relative paths failed when run from different directories
3. **Poor portability**: Configurations weren't portable across different deployment scenarios
4. **User confusion**: Users had to use absolute paths, which aren't portable across systems

### Technical Challenge

MCP servers like Gatekit are typically started by MCP clients (like Claude Desktop) with unpredictable working directories. The working directory depends on:
- How the MCP client was launched
- The client's internal working directory management
- The user's system configuration

This made relative paths in configuration files unreliable and created a poor user experience.

## Decision

We will implement **config-relative path resolution** where all relative paths in configuration files are resolved relative to the configuration file's location, not the current working directory.

### Key Components

1. **Path Resolution Utility Module** (`gatekit/utils/paths.py`)
   ```python
   def resolve_config_path(path: str, config_dir: Union[str, Path]) -> Path:
       """Resolve path relative to config directory with home expansion support."""
   ```

2. **ConfigLoader Enhancement**
   - Store the absolute path of the configuration file's directory
   - Pass config directory to all components that need path resolution
   - Resolve the config file path itself to absolute before loading

3. **Component Integration**
   - LoggingConfig resolves log file paths relative to config directory
   - FileAuditingPlugin resolves output_file relative to config directory
   - PluginManager passes config directory to all plugins

4. **Path Resolution Rules**
   - **Absolute paths**: Used unchanged (e.g., `/var/log/audit.log`)
   - **Home directory paths**: Expanded (e.g., `~/logs/audit.log` → `/Users/username/logs/audit.log`)
   - **Relative paths**: Resolved relative to config directory (e.g., `logs/audit.log` → `/config/dir/logs/audit.log`)

## Alternatives Considered

### Alternative 1: Working Directory Normalization
```python
# Set working directory to config file location
os.chdir(config_file.parent)
```
**Rejected because**:
- Global state changes can affect other parts of the system
- Thread safety concerns in async environment
- Doesn't work well with multiple config files
- Can break other file operations that expect original working directory

### Alternative 2: Environment Variable Based Paths
```yaml
logging:
  file_path: "${GATEKIT_CONFIG_DIR}/logs/audit.log"
```
**Rejected because**:
- Requires environment variable management
- More complex for users to understand and configure
- Platform-specific environment variable handling
- Doesn't solve the core issue of predictable path resolution

### Alternative 3: Configuration Preprocessing
```python
# Expand all paths during config loading
def preprocess_config(config_dict, base_dir):
    # Walk config tree and expand all path-like values
```
**Rejected because**:
- Requires heuristics to identify which values are paths
- Risk of false positives (non-path strings that look like paths)
- More complex than explicit path resolution
- Harder to debug when path resolution goes wrong

### Alternative 4: Absolute Path Only
```yaml
# Force users to use only absolute paths
logging:
  file_path: "/absolute/path/to/logs/audit.log"
```
**Rejected because**:
- Poor user experience - configurations aren't portable
- Makes development and testing harder
- Doesn't follow principle of least surprise
- Examples and tutorials become system-specific

## Consequences

### Positive
- **Predictable behavior**: Same configuration works regardless of working directory
- **Portable configurations**: Relative paths work consistently across deployments
- **Better user experience**: Users can use relative paths confidently
- **Tutorial reliability**: Example configurations work from any directory
- **Backward compatibility**: Absolute paths continue to work unchanged
- **Cross-platform support**: Path resolution works on Windows, macOS, and Linux

### Negative
- **Implementation complexity**: Additional path resolution logic throughout codebase
- **Testing overhead**: Need to test path resolution in multiple components
- **Migration effort**: Existing configurations need updates to use relative paths
- **Debugging complexity**: Path resolution can add a layer of indirection

### Risk Mitigation
- **Comprehensive testing**: Tests covering all path resolution scenarios
- **Graceful fallbacks**: Invalid paths produce clear error messages
- **Clear documentation**: Path resolution rules documented with examples
- **Backward compatibility**: Absolute paths and home directory paths still work
- **Environment variable expansion**: `${VAR}` syntax supported in paths

## Implementation Details

### Path Resolution Pipeline
```python
def resolve_config_path(path: str, config_dir: Union[str, Path]) -> Path:
    # 1. Validate input
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Path cannot be empty")
    
    # 2. Expand home directory if present
    expanded_path = expand_user_path(path.strip())
    
    # 3. If already absolute, return as-is
    if expanded_path.is_absolute():
        return expanded_path
    
    # 4. Resolve relative to config directory
    config_path = Path(config_dir) if isinstance(config_dir, str) else config_dir
    resolved_path = config_path / expanded_path
    return resolved_path.resolve()
```

### Integration Points
1. **ConfigLoader**: Stores config directory and passes to components
2. **LoggingConfig**: Resolves `file_path` during schema conversion
3. **PluginManager**: Passes config directory to all plugins
4. **FileAuditingPlugin**: Resolves `output_file` during initialization

### Configuration Examples
```yaml
# Before (unreliable)
logging:
  file_path: "./logs/gatekit.log"  # Depends on working directory

# After (reliable)
logging:
  file_path: "logs/gatekit.log"    # Relative to config file location
```

## Review

This decision will be reviewed when:
- Path resolution performance becomes a bottleneck
- Cross-platform compatibility issues arise
- User feedback indicates configuration complexity
- New configuration sources are added (environment variables, remote configs, etc.)

The config-relative path resolution strategy provides a solid foundation for reliable, portable configurations while maintaining backward compatibility and following user expectations.