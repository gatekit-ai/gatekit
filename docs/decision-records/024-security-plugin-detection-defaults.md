# ADR-024: Security Plugin Detection Option Defaults

## Context

Gatekit security plugins (PII filter, secrets filter, prompt injection filter) have configurable detection options that control which types of content they detect. For example:

- **PII filter**: `pii_types` (email, phone, credit_card, ip_address, national_id)
- **Secrets filter**: `secret_types` (api_keys, aws_credentials, jwt_tokens, private_keys, etc.)
- **Prompt injection filter**: `detection_methods` (known_patterns, instruction_override, etc.)

The question is: when a user enables a security plugin but doesn't explicitly configure these detection options, what should the default behavior be?

### The Tension

Two principles appear to be in conflict:

**Security-first principle**: Gatekit should be "secure by default," suggesting all detection types should be enabled and set to the strictest settings.

**Good first-run experience**: When users first try Gatekit, they shouldn't encounter false positives that make it appear the gateway is mangling data or causing errors. This suggests conservative defaults.

### Current State (Inconsistent)

The existing implementation is inconsistent across plugins:

| Plugin | Unspecified detection options |
|--------|-------------------------------|
| Secrets filter | Enabled by default (except `private_keys`) |
| PII filter | Disabled by default |
| Prompt injection | Enabled by default |

This inconsistency creates confusion and unpredictable behavior.

## Decision

We resolve this tension by recognizing that **two distinct defaults** are at play:

1. **Plugin existence default**: Whether the plugin appears in a new configuration
2. **Detection options default**: When a plugin IS enabled, what are its settings?

### Policy

**"Secure by default" applies to the enabled state, not the existence state.**

| State | Behavior | Rationale |
|-------|----------|-----------|
| Plugin not in config | No effect | Good first-run UX, no surprises |
| Plugin enabled, detection options not specified | All options enabled (with exceptions) | Secure by default when user opts in |
| Plugin enabled, options explicitly configured | Honor user configuration | User knows what they want |

**Analogy**: Think of it like a firewall. Installing a firewall doesn't automatically enable it (would break things). But when you DO enable the firewall, it defaults to blocking rather than allowing.

### High-False-Positive Exceptions

Some detection options have known high false-positive rates and remain **disabled by default** even when the plugin is enabled:

| Plugin | Option | Reason |
|--------|--------|--------|
| Secrets filter | `private_keys` | Matches many non-secret multi-line patterns |
| Secrets filter | `entropy_detection` | Flags random-looking but legitimate data |
| PII filter | `scan_base64` | Triggers on legitimate encoded content |
| Secrets filter | `scan_base64` | Triggers on legitimate encoded content |

These options require explicit opt-in because their false-positive rate makes them unsuitable for default-enabled behavior.

### Action Defaults

The `action` field defaults to `redact` for both PII and secrets filters. This provides protection (content is modified) without breaking the user's workflow (requests still succeed). The options are:

- `block`: Strictest, but may break legitimate workflows
- `redact`: Protective but non-breaking (default)
- `audit_only`: Logging only, no interference

## Implementation

### Plugin Implementation Pattern

Security plugins should merge user configuration with defaults:

```python
def __init__(self, config: Dict[str, Any]):
    # Define defaults - all detection types enabled except high-false-positive ones
    default_detection_types = {
        detection_type: {"enabled": True}
        for detection_type in self.DETECTION_TYPES.keys()
    }
    # Override specific high-false-positive options
    default_detection_types["high_fp_option"] = {"enabled": False}

    # Merge with user config - user settings override defaults
    self.detection_types = config.get("detection_types", {})
    for detection_type, default_config in default_detection_types.items():
        if detection_type not in self.detection_types:
            self.detection_types[detection_type] = default_config
```

### TUI Form Rendering

When displaying configuration forms for security plugins:

1. **New plugin configuration**: Detection option checkboxes should appear checked by default (reflecting the runtime defaults)
2. **Existing configuration**: Show actual configured state
3. **Visual consistency**: The form should reflect what will actually happen at runtime

This ensures users see accurate representations of the effective configuration.

## Consequences

### Positive

- **Predictable behavior**: Users know what to expect when enabling security plugins
- **Secure when enabled**: Opting into security means getting real security
- **Easy customization**: Users can disable specific types that cause false positives
- **Consistent UX**: All security plugins follow the same pattern
- **No forced interference**: New users aren't surprised by unexpected blocking/redaction

### Negative

- **Implementation work**: Existing plugins need updates for consistency
- **Documentation updates**: Need to clearly document the default-enabled behavior
- **Potential surprise for existing users**: Users who relied on disabled-by-default behavior may see new detections after updates

### Migration Consideration

For users with existing configurations that rely on the old disabled-by-default behavior, they may need to explicitly disable detection types they don't want. This is acceptable because:

1. It's a pre-1.0 release with no backward compatibility guarantees
2. The new behavior is more intuitive and secure
3. Explicit configuration is clearer than implicit defaults

## Alternatives Considered

### Alternative 1: All Detection Types Disabled by Default

```yaml
# User must explicitly enable each type
basic_pii_filter:
  enabled: true
  pii_types:
    email: {enabled: true}
    phone: {enabled: true}
    # Must list every type wanted
```

**Rejected**: Creates "security theater" - plugin appears enabled but catches nothing by default. Users may not realize they need to configure each type.

### Alternative 2: Strictest Settings by Default (Including Block Action)

```yaml
# Everything enabled, action: block
basic_pii_filter:
  enabled: true
  action: block  # Default to blocking
```

**Rejected**: Too aggressive for a default. Blocking can break legitimate workflows and frustrate users during initial setup.

### Alternative 3: Different Defaults for Development vs Production

```yaml
# environment-aware defaults
basic_pii_filter:
  enabled: true
  # defaults vary based on detected environment
```

**Rejected**: Adds complexity, hard to predict behavior, environment detection is unreliable.

## Related ADRs

- **ADR-006**: Critical Plugin Failure Modes - Establishes "secure by default" for plugin failure behavior
- **ADR-005**: Configuration Management - Defines configuration loading and validation patterns
- **ADR-018**: Plugin UI Widget Architecture - Covers TUI rendering for plugin configuration
