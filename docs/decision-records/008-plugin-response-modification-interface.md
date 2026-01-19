# ADR-008: Plugin Content Modification Interface

**Note**: This ADR uses the current terminology (`PluginResult`, `process_request`, `process_response`). See ADR-022 for the unified PluginResult design.

## Context

### Initial Requirement

Gatekit's original plugin architecture supported allow/block decisions for requests. However, implementing tools/list response filtering revealed a need for plugins to modify responses, not just allow or block them entirely.

The requirement emerged from the tool allowlist security plugin, which needed to filter `tools/list` responses to show only allowed tools while preserving the overall response structure and other fields.

### Original Plugin Interface Limitation

```python
@dataclass
class PluginResult:
    allowed: bool
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    # No way to specify modified content
```

This interface only supported binary allow/block decisions, making content modification impossible without significant architectural changes.

## Decision

We will **extend the existing `PluginResult` interface** to support generic content modification through a `modified_content` field that can handle any MCP message type:

```python
@dataclass
class PluginResult:
    allowed: bool
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    modified_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None
```

### Design Principles

1. **Generic Content Modification**: Support modification of requests, responses, and notifications through a single field
2. **Type Safety**: Use Union types and runtime type checking to ensure proper handling
3. **Security First**: Plugin manager must respect content modifications for all message types
4. **Clear Intent**: Field name explicitly indicates it can contain any content type
5. **Backward Compatibility**: Existing plugins continue to work without changes (those not modifying content)

### Plugin Manager Processing

Each processing method will check for the appropriate content type:

```python
# Request processing
if decision.modified_content and isinstance(decision.modified_content, MCPRequest):
    current_request = decision.modified_content

# Response processing  
if decision.modified_content and isinstance(decision.modified_content, MCPResponse):
    current_response = decision.modified_content

# Notification processing
if decision.modified_content and isinstance(decision.modified_content, MCPNotification):
    current_notification = decision.modified_content
```

### Usage Pattern

```python
class BasicPiiFilterPlugin(SecurityPlugin):
    async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
        if self.action == "redact" and contains_pii(request):
            redacted_request = redact_pii(request)
            return PluginResult(
                allowed=True,
                reason="PII detected and redacted from request",
                metadata={"pii_redacted": True},
                modified_content=redacted_request  # Proper field for request modification
            )
        return PluginResult(allowed=True, reason="No PII detected")

    async def process_response(self, request: MCPRequest, response: MCPResponse, server_name: str) -> PluginResult:
        if self.action == "redact" and contains_pii(response):
            redacted_response = redact_pii(response)
            return PluginResult(
                allowed=True,
                reason="PII detected and redacted from response",
                metadata={"pii_redacted": True},
                modified_content=redacted_response  # Same field for response modification
            )
        return PluginResult(allowed=True, reason="No PII detected")
```

## Alternatives Considered

### Alternative 1: Response-Specific Field (Original Design - Rejected)

```python
@dataclass
class PluginResult:
    modified_response: Optional[MCPResponse] = None  # Response-only
```

**Rejected because**:
- Cannot handle request or notification modifications
- Forces inappropriate workarounds for request modification (security vulnerability)
- Inconsistent interface for different message types

### Alternative 2: Separate Fields for Each Type

```python
@dataclass
class PluginResult:
    modified_request: Optional[MCPRequest] = None
    modified_response: Optional[MCPResponse] = None  
    modified_notification: Optional[MCPNotification] = None
```

**Rejected because**:
- Interface bloat with multiple optional fields
- Plugins can only modify one type per decision anyway
- More complex validation logic required

### Alternative 3: Backward Compatibility with Deprecation

```python
@dataclass
class PluginResult:
    modified_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None
    modified_response: Optional[MCPResponse] = None  # Deprecated
```

**Rejected because**:
- Added complexity for zero benefit (no existing users in v0.1.0)
- Risk of continued use of deprecated field
- Clean break preferred for security-critical fix

### Alternative 4: Separate Decision Types

```python
class RequestDecision(PluginResult):
    modified_request: Optional[MCPRequest] = None

class ResponseDecision(PluginResult):  
    modified_response: Optional[MCPResponse] = None
```

**Rejected because**:
- Plugin interface complexity increases significantly
- Method signatures become more complex
- Plugin manager needs type-specific handling

## Consequences

### Positive

- **Security Fix**: Resolves critical vulnerability in request modification handling 
- **Unified Architecture**: Single field supports all content modification use cases
- **Type Safety**: Runtime type checking prevents misuse
- **Clean Design**: No deprecated fields or backward compatibility complexity
- **Future Proof**: Supports any future MCP message types
- **Backward Compatible**: Existing plugins that don't modify content continue to work unchanged

### Negative

- **Breaking Changes**: Any plugins using `modified_response` must be updated (none exist in v0.1.0)
- **Implementation Effort**: Requires updates across codebase and test suite
- **Documentation Updates**: All documentation and examples must be updated
- **Interface Complexity**: `PluginResult` now has Union types requiring type checking

### Implementation Requirements

1. **PluginResult Interface**: Replace `modified_response` with `modified_content`
2. **Plugin Manager Updates**: Must handle `modified_content` field in all processing pipelines
3. **Security Plugins**: Update PII filter and other plugins to use new field
4. **Test Suite**: Update all tests referencing `modified_response`
5. **Validation**: Content modifications must be validated for correctness and type safety
6. **Logging**: Plugin decisions with modifications need appropriate audit logging

### Migration Strategy

Since this is v0.1.0 with no existing users:
- **No backward compatibility** required
- **Clean removal** of response-specific design
- **Complete migration** to generic content modification architecture

### Risk Mitigation

- **Comprehensive Testing**: Full test coverage for all modification scenarios
- **Code Review**: Careful review of all plugin manager changes  
- **Documentation**: Clear migration guide and security considerations

## Implementation Details

### PluginResult Structure

```python
@dataclass
class PluginResult:
    """Unified result from any plugin processing."""

    allowed: Optional[bool] = None  # Security decision (None for middleware)
    modified_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None
    completed_response: Optional[MCPResponse] = None  # For middleware short-circuit
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate state consistency."""
        if self.metadata is None:
            self.metadata = {}
        # Can't set both modified_content and completed_response
        if self.modified_content and self.completed_response:
            raise ValueError("Cannot set both modified_content and completed_response")
```

See ADR-022 for the complete unified PluginResult design.

### Plugin Manager Processing

The plugin manager processes all plugins (middleware and security) through a unified priority-sorted pipeline. See ADR-020 for the middleware architecture and ADR-009 for sequential processing details.

```python
async def process_request(self, request: MCPRequest, server_name: str) -> ProcessingPipeline:
    """Process request through all plugins sequentially by priority."""
    # Plugins are sorted by priority (0-100, lower = higher priority)
    # Both middleware and security plugins are processed in order
    # Returns a ProcessingPipeline with full visibility into each stage
```
