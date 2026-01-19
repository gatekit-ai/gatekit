# ADR-006: Critical Plugin Failure Modes (All Plugin Types)

## Context

Gatekit plugins (security, middleware, and auditing) need to handle failure scenarios appropriately. The key question is: when a plugin fails to initialize or encounters a runtime error, should the system fail-closed (halt) or fail-open (continue without that plugin)?

**Security Perspective**: Plugin failures that silently allow traffic through create security gaps. If a secrets filter fails to load, unprotected secrets could leak. This argues for fail-closed by default.

**Availability Perspective**: Some environments prioritize availability over strict security controls, especially during development. This argues for configurable behavior.

**Resolution**: All plugins default to `critical: true` (fail-closed). Users can explicitly opt out with `critical: false` for specific plugins in development/testing scenarios where availability is preferred over strict security.

## Decision

We implement **configuration-driven failure behavior** through a `critical` flag on all plugin types (security, middleware, auditing):

```yaml
plugins:
  security:
    _global:
      - handler: "basic_secrets_filter"
        config:
          enabled: true
          # critical: true is the default - omit for normal operation

      - handler: "basic_pii_filter"
        config:
          enabled: true
          critical: false  # Explicitly opt-out for development

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "audit.jsonl"
          # critical: true is the default
```

### Implementation Strategy

```python
class MiddlewarePlugin(PluginInterface):
    """Base class for middleware plugins with critical failure support."""

    def __init__(self, config: Dict[str, Any]):
        # All plugins default to critical (fail closed) for security
        self.critical = config.get("critical", True)

class SecurityPlugin(MiddlewarePlugin):
    """Security plugins inherit critical=True default from MiddlewarePlugin."""
    pass

class AuditingPlugin(PluginInterface):
    """Auditing plugins also default to critical=True."""

    def __init__(self, config: Dict[str, Any]):
        self.critical = config.get("critical", True)

    def is_critical(self) -> bool:
        return getattr(self, 'critical', True)
```

### Plugin Manager Behavior

For all plugin types during initialization:

```python
except Exception as e:
    # All plugins default to critical=True (fail closed)
    is_critical = plugin_config.get("config", {}).get("critical", True)
    if is_critical:
        logger.exception(f"Critical plugin '{handler_name}' failed to initialize: {e}")
        raise  # Halt system startup
    else:
        logger.exception(f"Non-critical plugin '{handler_name}' failed: {e}")
        # Continue without this plugin
```

### Key Design Principles

1. **Secure by Default**: All plugins default to `critical: true` (fail-closed)
2. **Explicit Opt-Out**: Users must explicitly set `critical: false` to allow fail-open behavior
3. **Per-Plugin Control**: Each plugin can be configured independently
4. **Clear Error Messages**: Failures explain what happened and how to configure differently
5. **Consistent Behavior**: All plugin types (security, middleware, auditing) use the same pattern

## Alternatives Considered

### Alternative 1: Default to Graceful Failure (critical: false)
```python
# Original behavior - continue on plugin failures by default
self.critical = config.get("critical", False)
```
- **Pros**: Never breaks proxy functionality, good developer experience
- **Cons**: **Security risk** - plugins can silently fail, creating protection gaps

### Alternative 2: Always Fatal Failure (no configuration)
```python
# Always propagate plugin failures
except Exception as e:
    raise PluginFailureError(f"Plugin failed: {e}")
```
- **Pros**: Maximum security, no protection gaps possible
- **Cons**: Too rigid, blocks legitimate development/testing scenarios

### Alternative 3: Different Defaults per Plugin Type
```python
# Security plugins: critical=True
# Middleware plugins: critical=False
# Auditing plugins: critical=False
```
- **Pros**: Balances security and convenience per type
- **Cons**: Inconsistent behavior, harder to reason about, middleware failures can still cause issues

**Why We Chose Uniform critical=True Default**: Security plugins failing silently is clearly dangerous. But middleware and auditing plugin failures can also cause problems - a failed call_trace plugin means no debugging visibility; a failed audit plugin means compliance gaps. The safest default is fail-closed for all types, with explicit opt-out for specific use cases.

## Consequences

### Positive
- **Secure by Default**: No silent security gaps from plugin failures
- **Early Failure Detection**: Configuration errors caught at startup, not runtime
- **Clear Error Messages**: Users immediately know what failed and why
- **Flexible When Needed**: Explicit `critical: false` available for development scenarios

### Negative
- **Breaking Change**: Existing configs with broken plugins will now fail at startup (this is intentional - previously they silently failed)
- **Configuration Burden**: Development environments may need `critical: false` for convenience
- **Testing Overhead**: Both failure modes must be tested for each plugin type

## Implementation Notes

This decision affects multiple components:

1. **Plugin Interfaces** (`gatekit/plugins/interfaces.py`):
   - `MiddlewarePlugin.__init__()`: `self.critical = config.get("critical", True)`
   - `SecurityPlugin.__init__()`: Inherits from MiddlewarePlugin, also defaults to True
   - `AuditingPlugin.__init__()`: `self.critical = config.get("critical", True)`
   - `AuditingPlugin.is_critical()`: Returns `getattr(self, 'critical', True)`

2. **Plugin Manager** (`gatekit/plugins/manager.py`):
   - `_load_upstream_scoped_security_plugins()`: Check critical flag, default True
   - `_load_upstream_scoped_auditing_plugins()`: Check critical flag, default True
   - `_load_upstream_scoped_middleware_plugins()`: Check critical flag, default True
   - All use pattern: `is_critical = plugin_config.get("config", {}).get("critical", True)`

3. **All Plugins**:
   - Support `critical` configuration parameter
   - Default to `critical: true` for fail-closed behavior

4. **Documentation**:
   - Update configuration examples to show `critical: false` for development
   - Document that omitting `critical` means fail-closed behavior

## Use Cases

### Production Environment (Default Behavior)
```yaml
plugins:
  security:
    _global:
      - handler: "basic_secrets_filter"
        config:
          enabled: true
          # critical: true is default - plugin failures halt startup

      - handler: "basic_pii_filter"
        config:
          enabled: true
          # critical: true is default

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "/var/log/gatekit/audit.jsonl"
          # critical: true is default - audit failures halt startup
```

### Development/Testing Environment
```yaml
plugins:
  security:
    _global:
      - handler: "basic_pii_filter"
        config:
          enabled: true
          critical: false  # Allow startup even if PII filter has config issues

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "debug.jsonl"
          critical: false  # Don't break development if audit log path is wrong
```

### Mixed Criticality
```yaml
plugins:
  security:
    _global:
      - handler: "basic_secrets_filter"
        config:
          enabled: true
          # critical: true - secrets MUST be protected

      - handler: "basic_pii_filter"
        config:
          enabled: true
          critical: false  # PII protection is nice-to-have in this environment

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "audit.jsonl"
          # critical: true - compliance requires audit trail

      - handler: "audit_human_readable"
        config:
          enabled: true
          output_file: "debug.log"
          critical: false  # Human-readable log is optional debugging aid
```

## Review

This decision will be reviewed when:
- User feedback indicates the default is too strict for common use cases
- New plugin types with different failure characteristics are added
- Performance impact of critical checking becomes significant

## History

- **Original behavior**: Auditing and middleware defaulted to `critical: false`; security defaulted to `critical: true` but wasn't enforced during initialization
- **Current behavior**: All plugin types default to `critical: true` after discovering that security plugins silently failing to initialize created security gaps
