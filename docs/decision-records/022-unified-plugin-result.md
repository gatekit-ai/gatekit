# ADR-022: Unified PluginResult for Plugin Processing

## Context

Gatekit's plugin architecture originally used two separate result types:
- `SecurityResult` for security plugin decisions (allowed/denied with reason)
- `MiddlewareResult` for middleware transformations (modified content, completed responses)

This dual-result system created several critical problems:

### 1. Semantic Incorrectness
When only middleware plugins were configured (no security plugins), the plugin manager would return:
```python
SecurityResult(allowed=True, reason="Allowed by all security plugins")
```
This was fundamentally wrong - no security plugins had even executed. The system was lying about what happened.

### 2. Type Complexity
The codebase carried `Union[SecurityResult, MiddlewareResult]` throughout, leading to:
- Constant `isinstance()` checks polluting the code
- Confusion about which type to expect in different contexts
- Complex type annotations reducing readability
- Difficulty in extending the system with new result types

### 3. Lost Processing History
The current approach only preserved the last plugin's contribution:
- Each plugin's reason replaced the previous one
- No visibility into what each plugin in the pipeline did
- Modifications weren't tracked with attribution
- Debugging complex plugin interactions was difficult

### 4. Inconsistent Accumulation
Different aspects of results were handled inconsistently:
- Metadata was merged (good)
- Reasons were replaced (bad)
- Modifications were replaced (bad)
- No record of which plugins ran or in what order

## Decision

We will replace the dual SecurityResult/MiddlewareResult system with a single unified `PluginResult` class that all plugins return, while maintaining the plugin type distinction for organizational clarity.

### Core Design

1. **Single Result Type**: All plugins return `PluginResult` with optional security decision field.

2. **Plugin Type Distinction Remains**: `SecurityPlugin` and `MiddlewarePlugin` classes stay separate for semantic clarity and contract enforcement.

3. **Security Contract Enforcement**: SecurityPlugin base class ensures `allowed` field is set.

4. **Gradual Migration Path**: Support both old and new types during transition.

The key design elements:
```python
@dataclass
class PluginResult:
    # Security decision (None if no security decision made)
    allowed: Optional[bool] = None
    
    # Content transformations
    modified_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None
    completed_response: Optional[MCPResponse] = None
    
    # Processing information
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### Why Maintain Plugin Types?

While all plugins return the same result type, different plugin classes serve important purposes:

1. **Human Understanding**: Categories match mental models ("security protects", "middleware transforms")
2. **Contract Enforcement**: Security plugins MUST decide, middleware MAY transform
3. **Configuration Organization**: Clear YAML sections for different concerns
4. **Documentation Structure**: Meaningful groupings for users

## Consequences

### Positive

1. **Semantic Correctness**: Middleware-only pipelines return results with `allowed=None`, accurately indicating no security decision was made.

2. **Simplified Type System**: No more `Union[SecurityResult, MiddlewareResult]` throughout the codebase.

3. **Clean Plugin Interface**: Plugins return a simple, consistent result type.

4. **Contract Enforcement**: SecurityPlugin base class ensures security plugins set the `allowed` field.

5. **Extensibility**: Easy to add new fields to PluginResult without breaking existing code.

6. **Gradual Migration**: Can migrate from Union types incrementally without breaking existing code.

### Negative

1. **Migration Effort**: All plugins must be updated to return PluginResult.

2. **Temporary Complexity**: Supporting both old and new types during migration adds temporary complexity.

3. **Breaking Change**: Eventually not backward compatible with existing plugin implementations.

### Neutral

1. **Learning Curve**: Developers need to understand that all plugins return the same type.

2. **Test Updates**: Tests need updating to work with new result type.

## Alternatives Considered

### 1. Keep Dual System with Better Logic
Fix the semantic incorrectness while keeping two result types. Rejected because:
- Doesn't solve the Union type complexity
- Maintains artificial distinction between result types
- More isinstance() checks throughout codebase

### 2. Each Plugin Returns PipelineResult
Have plugins return a "PipelineResult" that accumulates history. Rejected because:
- Semantically confusing (why does one plugin return pipeline result?)
- Over-couples plugins to pipeline architecture
- Makes plugin interface more complex

### 3. Complete Unification (No Plugin Types)
Single Plugin class that can do everything. Rejected because:
- Loses semantic clarity for humans
- Can't enforce contracts (security must decide)
- Configuration becomes less intuitive
- Documentation harder to organize

## Implementation

The implementation includes:

1. Adding PluginResult class alongside existing types
2. Updating plugin base classes to support both types during transition
3. Gradually migrating all plugins to return PluginResult
4. Updating plugin manager to handle single type
5. Removing deprecated SecurityResult/MiddlewareResult types
6. Comprehensive test updates

## Migration Strategy

### Phase 1: Parallel Support
- Add PluginResult alongside existing types
- Base classes accept both return types
- Manager handles Union during transition
- Gradual plugin migration

### Phase 2: Complete Migration
- All plugins use PluginResult
- Remove old result types
- Simplify manager code
- Update all tests

### Future Enhancement: PipelineResult Container

A future enhancement could add a PipelineResult container that accumulates all individual PluginResults for complete processing history:

```python
@dataclass
class PipelineResult:
    """Container for all plugin results from pipeline"""
    plugin_results: List[Tuple[str, PluginResult]]
    
    @property
    def allowed(self) -> Optional[bool]:
        # Compute from contained results
```

This would provide full observability but is not required for the initial implementation.

## Notes

This change represents a pragmatic balance between technical simplicity and organizational clarity:

- **Technical Reality**: All plugins are message processors returning similar results
- **Human Organization**: Different plugin types help with mental models and configuration
- **Contract Enforcement**: Base classes ensure security plugins make decisions
- **Migration Path**: Gradual transition from Union types to single type

The distinction between plugin types is "a useful fiction" - technically unnecessary but organizationally valuable, similar to frontend/backend distinctions in web development.