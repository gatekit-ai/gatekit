# ADR-009: Sequential Plugin Processing for Responses

**Note**: This ADR uses current terminology (`process_response`, `modified_content`, `PluginResult`). See ADR-022 for the unified result type.

## Context

When implementing response modification capabilities (see ADR-008), we needed to determine how multiple plugins should interact when processing responses. The key question was whether plugins should process responses in parallel with conflict resolution, or sequentially with cumulative modifications.

This decision affects:
- **Deterministic behavior**: Whether plugin processing order matters
- **Plugin interaction**: How plugins compose their modifications
- **Performance**: Processing time and resource usage
- **Debugging**: Ability to trace plugin effects
- **Configuration complexity**: How users understand plugin behavior

### Use Case Driving the Decision

The tool allowlist plugin filters `tools/list` responses, potentially followed by other plugins that might:
- Add metadata to tool descriptions
- Reorder tools based on priority
- Transform tool schemas for compatibility
- Log or audit tool access patterns

## Decision

We will implement **sequential plugin processing** where plugins process responses one after another, with each plugin receiving the output of the previous plugin as input.

```python
async def process_response(self, response: MCPResponse) -> MCPResponse:
    """Process response through plugins sequentially."""
    current_response = response
    
    for plugin in self.response_plugins:
        decision = await plugin.process_response(current_response)
        
        if not decision.allowed:
            raise PluginBlockedError(decision.reason)
        
        if decision.modified_content is not None:
            current_response = decision.modified_content
            # Next plugin receives this modified response
    
    return current_response
```

### Processing Order

Plugin processing order is determined by priority values (0-100, with 50 as default). All middleware and security plugins are sorted together in a unified pipeline:

```yaml
plugins:
  middleware:
    _global:
      - handler: "tool_manager"       # Processes first (priority: 10)
        config:
          enabled: true
          priority: 10

  security:
    _global:
      - handler: "basic_pii_filter"   # Processes second (priority: 20)
        config:
          enabled: true
          priority: 20
```

**Note**: Auditing plugins do NOT participate in sequential response processing. They observe the final result via `log_response()` after the processing pipeline completes, and they execute in definition order (not by priority).

## Alternatives Considered

### Alternative 1: Parallel Processing with Conflict Resolution

```python
async def process_response(self, response: MCPResponse) -> MCPResponse:
    """Process response through all plugins in parallel."""
    decisions = await asyncio.gather(*[
        plugin.process_response(response) 
        for plugin in self.response_plugins
    ])
    
    # Resolve conflicts between different modifications
    return resolve_response_conflicts(response, decisions)
```

**Rejected because**:
- **Conflict resolution complexity**: No clear rules for merging conflicting modifications
- **Non-deterministic behavior**: Parallel execution order can vary
- **Plugin interaction unclear**: Plugins can't build on each other's work
- **Debugging difficulty**: Hard to trace which plugin caused what change

### Alternative 3: Plugin Priority System

```yaml
plugins:
  security:
    _global:
      - handler: "tool_allowlist"
        config:
          enabled: true
          priority: 10  # Higher priority (lower number)

      - handler: "content_filter"
        config:
          enabled: true
          priority: 50  # Default priority
```

**Rejected because**:
- **Configuration complexity**: Users must understand and manage priority values
- **Maintenance burden**: Priorities need coordination across plugin ecosystem
- **Still requires conflict resolution**: Multiple plugins at same priority level
- **Harder migration**: Existing configurations would need priority assignment

Note: This alternative was later reconsidered and adopted in a subsequent decision.

### Alternative 4: Plugin Dependency Declaration

```python
class ContentFilterPlugin:
    depends_on = ["tool_allowlist"]  # Must run after allowlist
```

**Rejected because**:
- **Dependency complexity**: Creates plugin coupling and circular dependency risks
- **Configuration validation**: Need to verify dependency graphs are valid
- **Over-engineering**: Current use cases don't require complex dependencies
- **Plugin portability**: Plugins become less reusable across configurations

Note: This alternative was later reconsidered and rejected in favor of a simple priority system.

### Alternative 5: Response Accumulation with Original

```python
async def process_response(self, response: MCPResponse) -> MCPResponse:
    """Each plugin sees original response, accumulate changes."""
    modifications = []
    
    for plugin in self.response_plugins:
        decision = await plugin.process_response(response)  # Always original
        if decision.modified_content:
            modifications.append(decision.modified_content)
    
    return merge_modifications(response, modifications)
```

**Rejected because**:
- **Limited plugin capabilities**: Plugins can't see effects of previous plugins
- **Complex merging logic**: Need sophisticated merge strategies
- **Use case mismatch**: Some plugins need to see filtered/modified responses

## Consequences

### Positive

- **Deterministic Behavior**: Same input always produces same output
- **Simple Mental Model**: Easy to understand and predict plugin behavior
- **Plugin Composition**: Plugins can build on each other's modifications
- **Easy Debugging**: Clear trace of how response evolved through plugins
- **Configuration Simplicity**: Priority values determine processing order
- **Performance Predictability**: Linear processing time, no conflict resolution overhead

### Negative

- **Order Dependency**: Plugin priority values matter significantly
- **Potential Inefficiency**: Later plugins might undo work of earlier plugins
- **Plugin Coupling**: Plugins may need to be aware of other plugins' effects
- **Serial Bottleneck**: Can't parallelize plugin processing for performance

### Mitigation Strategies

1. **Clear Documentation**: Explain priority system and its implications
2. **Plugin Guidelines**: Best practices for plugin design and priority assignment
3. **Configuration Validation**: Warn about potentially problematic plugin priorities
4. **Audit Logging**: Log each plugin's decision for transparency

## Implementation Details

### Plugin Manager Sequential Processing

The actual implementation returns a `ProcessingPipeline` object that provides full visibility into each processing stage:

```python
class PluginManager:
    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: Optional[str] = None
    ) -> ProcessingPipeline:
        """Process response through all enabled plugins sequentially."""
        # Creates a ProcessingPipeline with PipelineStage for each plugin
        # Middleware and security plugins are sorted together by priority
        # Auditing plugins are NOT included - they observe via log_response() after
```

### Plugin Ordering Strategy

```python
def _get_processing_pipeline(self, server_name: str) -> List[PluginInterface]:
    """Get plugins in processing order: sorted by priority (0-100, lower = higher priority)."""
    all_plugins = []

    # Collect middleware plugins
    all_plugins.extend(self._resolve_plugins_for_upstream(self.middleware_plugins, server_name))

    # Collect security plugins
    all_plugins.extend(self._resolve_plugins_for_upstream(self.security_plugins, server_name))

    # Sort by priority (ascending - lower numbers first)
    all_plugins.sort(key=lambda p: getattr(p, "priority", 50))
    return all_plugins
```

**Key points:**
- Middleware and security plugins are **intermixed** based on priority, not processed in separate phases
- Auditing plugins execute in **definition order** (not by priority) after the pipeline completes
- The pipeline returns a `ProcessingPipeline` with full `PipelineStage` records for observability

This sequential processing approach provides predictable, debuggable plugin behavior while enabling powerful plugin composition for response modification use cases.
