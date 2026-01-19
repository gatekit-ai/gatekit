# ADR-019: Plugin Equality Principle

## Context

Gatekit uses a plugin-based architecture with three categories of plugins:
- **Security plugins**: Make allow/block decisions on requests
- **Middleware plugins**: Transform or complete requests
- **Auditing plugins**: Log and observe traffic

A key design question: should plugins that ship with Gatekit receive special treatment over user-created plugins? Many systems have "blessed" built-in components with access to private APIs or special validation rules.

### The Temptation

It would be easier to hardcode plugin names for common operations:

```python
# Tempting but wrong
if plugin.handler == "tool_manager":
    # special handling for this common plugin

SERVER_AWARE_PLUGINS = {'tool_manager', 'filesystem_server'}  # hardcoded list
```

This creates a two-tier system where built-in plugins have capabilities that user plugins cannot replicate.

## Decision

**All plugins are first-class citizens.** Plugins that ship with Gatekit receive NO special treatment.

### Core Rules

1. **No hardcoded plugin names** - Core code must never contain hardcoded references to specific plugin names in validation, configuration, or business logic

2. **Dynamic discovery only** - Use the plugin discovery system to find and interact with plugins

3. **Metadata-driven behavior** - Plugins declare their own capabilities via class attributes:
   - `DISPLAY_SCOPE`: Whether plugin is `global`, `server_aware`, or `server_specific`
   - `DISPLAY_NAME`: Human-readable name for TUI
   - `HANDLERS`: Dictionary mapping handler names to plugin classes

4. **Equal validation** - Built-in and user plugins must pass through identical validation logic

5. **Same interfaces** - Built-in plugins use the same interfaces and base classes as user plugins

## Rationale

### Security Credibility

Gatekit is security software. Users who deploy security tools are rightfully skeptical of hidden behaviors. By ensuring all plugins—including built-in ones—use the same discovery and validation paths, we demonstrate that:
- No special backdoors exist for built-in plugins
- All code paths are equally validated
- User plugins can achieve the same capabilities

### Extensibility

When users create plugins, they should be able to replicate any capability of built-in plugins. If `tool_manager` can declare itself as `server_aware`, user plugins must be able to do the same.

### Maintainability

Hardcoded lists become maintenance burdens. When new plugins are added, every hardcoded list must be updated. Metadata-driven discovery eliminates this class of bugs.

### Testability

Generic, metadata-driven code is easier to test. Instead of testing each hardcoded plugin name, tests verify that the discovery system works correctly for any plugin.

## Implementation Guidelines

### Discovering Plugin Capabilities

```python
# CORRECT: Dynamic discovery via metadata
plugin_class = discover_plugin_class(plugin.handler)
display_scope = getattr(plugin_class, 'DISPLAY_SCOPE', 'global')

if display_scope == 'server_aware':
    # Handle server-aware plugins generically
    pass
```

### Iterating Over Plugins

```python
# CORRECT: Use plugin discovery
for handler_name, plugin_class in discover_all_plugins().items():
    display_name = getattr(plugin_class, 'DISPLAY_NAME', handler_name)
    # Process plugin...
```

### Validation

```python
# CORRECT: Same validation for all plugins
def validate_plugin_config(handler: str, config: dict) -> None:
    plugin_class = discover_plugin_class(handler)  # Works for any plugin
    schema = plugin_class.get_json_schema()
    validate(config, schema)
```

## Consequences

### Positive

- **User plugins are truly first-class** - Can implement any capability built-in plugins have
- **No hidden behaviors** - All plugin capabilities are documented and discoverable
- **Clean interfaces** - Forces good API design
- **Easier onboarding** - Third-party developers see their plugins treated equally

### Negative

- **Cannot take shortcuts** - Must always use discovery even for common plugins
- **More verbose code** - `getattr(plugin_class, 'DISPLAY_SCOPE', 'global')` instead of checking a list
- **Slight performance overhead** - Discovery instead of direct lookup (negligible in practice)

## Related Decisions

- **ADR-007**: Plugin Configuration Structure (defines per-server plugin configuration)
- **ADR-018**: Plugin UI Widget Architecture (defines metadata plugins expose for TUI)
- **ADR-024**: Security Plugin Detection Defaults (uses metadata for default detection options)

## Decision Makers

Core architecture principle established to ensure extensibility and trust in security-critical software.
