# ADR-021: Handler Nomenclature for Plugin Manifest Declarations

## Context

Gatekit's plugin system originally used the term "POLICIES" for manifest declarations that map plugin names to their implementation classes. This terminology was inherited from the initial security-focused design where plugins were conceptualized as "security policies."

With the introduction of middleware plugins, this terminology became problematic:

1. **Semantic Inaccuracy**: The term "policy" implies rules or governance, which makes sense for security plugins but not for middleware that performs transformations, routing, or other non-policy operations.

2. **Conceptual Confusion**: Auditing plugins that simply observe and log are not "policies" in any meaningful sense. They don't enforce anything or make decisions.

3. **Limited Scope**: As the plugin architecture expanded to support different plugin types (security, auditing, middleware), the term "policy" became increasingly inappropriate for non-security contexts.

4. **Developer Experience**: New plugin developers were confused about why they needed to declare "POLICIES" for plugins that weren't implementing any policies.

## Decision

We will rename all references from "POLICIES" to "HANDLERS" throughout the codebase:

1. **Manifest Declarations**: Change `POLICIES = {...}` to `HANDLERS = {...}` in all plugin files
2. **Configuration Fields**: Change `policy: "plugin_name"` to `handler: "plugin_name"` in YAML configurations
3. **Plugin Attributes**: Change `plugin.policy` to `plugin.handler` for runtime plugin identification
4. **Method Names**: Change `_discover_policies()` to `_discover_handlers()` in the plugin manager
5. **Variable Names**: Change all `policy_name`, `available_policies` to `handler_name`, `available_handlers`

## Consequences

### Positive

1. **Semantic Clarity**: "Handler" accurately describes what these are - code that handles messages, regardless of plugin type.

2. **Universal Applicability**: The term "handler" works equally well for all plugin types:
   - Security handlers make security decisions
   - Middleware handlers transform or route messages
   - Auditing handlers observe and log activity

3. **Improved Developer Experience**: Plugin developers immediately understand that they're declaring message handlers, not policies.

4. **Future-Proof**: As new plugin types are added, "handler" remains appropriate terminology.

5. **Industry Alignment**: "Handler" is widely used in similar contexts (event handlers, request handlers, message handlers).

### Negative

1. **Migration Effort**: All existing plugins and configurations need to be updated.

2. **Documentation Updates**: All documentation references must be changed.

3. **Potential User Confusion**: Users with existing configurations will need to update them (mitigated by helpful error messages).

### Migration Strategy

Since Gatekit is at v0.1.0 with no backward compatibility requirements, we can make this a clean break. However, we will:

1. Provide clear error messages when old "policy" configuration is detected
2. Include a migration script for users to update their configurations
3. Update all documentation and examples
4. Ensure comprehensive testing of the new terminology

## Implementation

The implementation includes:

1. Comprehensive grep audit to find all uses of "policy" terminology
2. Systematic updates to all plugin files, tests, and documentation
3. Addition of helpful error messages for old configuration format
4. Creation of migration tooling for user configurations

## Notes

This change exemplifies Gatekit's commitment to semantic accuracy and developer experience. While "policy" made sense in the initial security-focused context, the evolution to a general-purpose plugin architecture requires terminology that accurately reflects the broader scope of functionality.

The term "handler" was chosen over alternatives like "processor", "plugin", or "implementation" because:
- It's concise and clear
- It accurately describes the function (handling messages)
- It's familiar to developers from other contexts
- It doesn't imply any specific type of processing or decision-making