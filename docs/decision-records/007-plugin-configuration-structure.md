# ADR-007: Plugin Configuration Structure

**Last Validated**: 2026-01-17 - Updated to reflect current handler-based implementation.

## Historical Context

This ADR documents the evolution of the plugin configuration system from path-based to policy-based to the current handler-based approach.

### Original Path-Based Decision (v0.1.0 Initial)
Gatekit v0.1.0 initially implemented a path-based plugin configuration system:

```yaml
plugins:
  security:
    _global:
      - path: "./plugins/security/tool_allowlist.py"
        config:
          enabled: true
          mode: "allowlist"
          tools: ["read_file"]
```

### Evolution to Policy-Based System (v0.1.0 Mid)
During v0.1.0 development, the system evolved to use a policy-based manifest approach:

```yaml
plugins:
  security:
    _global:
      - policy: "tool_allowlist"  # Changed from 'path'
        config:
          enabled: true
          mode: "allowlist"
          tools: ["read_file", "list_directory"]
```

### Current Handler-Based System (v0.1.0 Final)
The final implementation uses 'handler' as the field name for better clarity:

```yaml
plugins:
  middleware:
    _global:
      - handler: "tool_manager"  # Final field name
        config:
          enabled: true
          priority: 50
          tools:
            - tool: "read_file"
            - tool: "list_directory"
```

Note: Tool management is implemented as a **middleware plugin** (not security) because it handles operational concerns. The `mode` field is no longer supported - the plugin uses implicit allowlist semantics.

## Current Implementation (Handler-Based)

The final v0.1.0 implementation uses a **handler-based plugin configuration** system where:

1. **Plugins declare handlers** via HANDLERS manifest in their modules
2. **Configuration references handlers** by name rather than file paths
3. **Plugin discovery** is automatic based on installed plugin manifests

### Key Benefits of Handler-Based Approach
- **Abstraction**: Configuration independent of file structure
- **Discoverability**: Automatic policy discovery from installed plugins
- **Flexibility**: Multiple plugins can implement the same policy
- **Maintainability**: Plugin reorganization doesn't break configurations

## Implementation Details

### Plugin Manifest System
Each plugin module contains a HANDLERS manifest:

```python
# In gatekit/plugins/middleware/tool_manager.py
HANDLERS = {
    "tool_manager": ToolManagerPlugin
}
```

### Configuration Schema
Plugin configurations use handler names:

```yaml
plugins:
  middleware:
    _global:
      - handler: "tool_manager"  # References handler name, not file path
        config:
          enabled: true
          priority: 50
          tools:
            - tool: "read_file"
            - tool: "write_file"
```

### Plugin Scope Validation
Plugins declare their scope via `DISPLAY_SCOPE` class attribute:
- `"global"`: Can be configured in `_global` section (default)
- `"server_aware"`: Can be in `_global` or per-server sections
- `"server_specific"`: Must be configured per-server only

Server-aware and server-specific plugins **cannot** be placed in `_global` when they require per-server context.

### Discovery and Loading Process
1. Plugin manager scans `gatekit/plugins/{category}/` directories for HANDLERS manifests
2. Builds registry of available handlers and their implementations via `_discover_handlers()`
3. Configuration loader validates handler names at config load time (not runtime)
4. Runtime loads appropriate plugin classes based on handler names

## Migration Impact

### Breaking Changes from Path-Based System
- Configuration field evolved: `path:` → `policy:` → `handler:`
- Plugin discovery no longer requires explicit file paths
- Validation checks handler availability instead of file existence

### Benefits Gained
- **Simplified configuration**: No need to know internal file structure
- **Better error messages**: Clear indication when handlers are unavailable
- **Plugin portability**: Plugins can be reorganized without config changes
- **Extensibility**: Foundation for future plugin marketplace/registry

## Legacy Information

The remainder of this document contains the original path-based design rationale, preserved for historical context.

<details>
<summary>Original Path-Based Design (Historical)</summary>

### Original Decision Rationale
The path-based approach was chosen initially to avoid premature optimization and infrastructure complexity. However, during implementation, the benefits of a policy-based manifest system became apparent and justified the additional complexity.

### Original Consequences

#### Positive (Path-Based)
- **Simplicity**: No indirection between configuration and plugin location
- **Transparency**: Users see exactly which files are being loaded
- **No infrastructure dependency**: Works entirely offline
- **Familiar pattern**: Similar to Docker volumes, Kubernetes ConfigMaps
- **Easy debugging**: Clear path from config to plugin file

#### Negative (Path-Based)
- **More verbose**: Full file paths instead of short names
- **Manual management**: No automatic plugin discovery from registry
- **Path dependencies**: Configuration tied to specific file structure

#### Neutral (Path-Based)
- **Compatibility**: Registry support can be added alongside existing configurations
- **Plugin distribution**: Third-party plugins distributed as files

</details>

## Related ADRs

- ADR-021: Handler Nomenclature - documents the shift from "policy" to "handler" terminology
- ADR-019: Plugin Equality Principle - ensures built-in and user plugins are treated equally

## Review Criteria

This approach may need adjustment when:
- Users request easier plugin distribution mechanisms
- Multiple third-party plugins exist that would benefit from centralized hosting
- Plugin management complexity becomes a significant user pain point
- Registry infrastructure can be properly maintained and supported
