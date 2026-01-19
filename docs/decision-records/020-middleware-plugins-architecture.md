# ADR-020: Middleware Plugin Architecture with Request Completion Capability

**Note**: This ADR originally proposed a separate `MiddlewareResult` type. That design was later unified into a single `PluginResult` type (see ADR-022). Code examples below use the current `PluginResult` interface.

## Context

Gatekit was initially conceived as a security gateway for MCP (Model Context Protocol) communications, with security plugins that could block malicious content and auditing plugins that observed traffic. However, as we considered real-world developer needs for agentic workflows, we identified a gap in our architecture:

### Developer Pain Points
1. **Context Window Bloat**: LLMs receive too many tools, consuming valuable context
2. **Poor Tool Naming**: MCP servers provide tools with names that LLMs struggle to understand
3. **Missing Functionality**: No way to cache, rate limit, or transform content
4. **Limited Extensibility**: Security plugins are semantically wrong for non-security enhancements

### The tool_allowlist Dilemma
Our `tool_allowlist` plugin highlighted this architectural gap. It:
- Hides/blocks tools (security-like behavior)
- But does so for performance/usability, not security
- Marketing it as "security" confused the value proposition
- Developers want capability shaping, not just security

### Marketing Challenge
Positioning Gatekit solely as a security gateway limits adoption. Developers need:
- Performance optimization tools
- Workflow enhancement capabilities  
- Integration points for their systems
- Context management for agents

## Decision

We will introduce a new **Middleware Plugin** type that:

1. **Sits between the client and security plugins** in the processing pipeline
2. **Can either transform OR complete requests** without conflating with security
3. **Focuses on functionality and developer productivity** rather than trust decisions

### Key Architectural Decisions

#### 1. Three Distinct Plugin Types
```
Client → [Middleware & Security Plugins (ordered by priority)] → Server → [Audit Plugins]
                              ↓                                             ↓
                  (Shape/Optimize + Trust/Block)                        (Observe)
```

- **Middleware**: Shapes functionality - "How can I make this work better?"
- **Security**: Makes trust decisions - "Is this safe? Does it violate policy?"
- **Auditing**: Observes everything - "What happened? Who did what?"

**Note**: Middleware and security plugins are intermixed and processed in priority order (0-100, lower = higher priority), not in separate sequential phases. This allows fine-grained control over when transformations occur relative to security checks.

#### 2. PluginResult with Dual Capability
```python
@dataclass
class PluginResult:
    # Security decision (None for middleware that doesn't make security decisions)
    allowed: Optional[bool] = None

    # Option 1: Transform and continue
    modified_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None

    # Option 2: Complete the request here
    completed_response: Optional[MCPResponse] = None

    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
```

This allows middleware to:
- **Transform**: Modify content and pass it along
- **Complete**: Fully handle the request (cache hit, rate limit, capability filtered)

#### 3. No "Blocking" for Middleware
Critically, middleware does NOT set the `allowed` field (leaving it as `None`). When middleware returns a `completed_response`:
- It's not "blocking" the request
- It's saying "I've fully handled this request, here's the response"
- Semantically different from security blocking (which sets `allowed=False`)

#### 4. tool_manager as Middleware
The `tool_allowlist` plugin becomes `tool_manager` middleware:
- Moves from `plugins/security/` to `plugins/middleware/`
- When hiding tools, returns "tool not available" (not "blocked")
- Framed as capability shaping, not security enforcement
- Reduces LLM context, improves tool selection

## Consequences

### Positive

1. **Clear Mental Model**: Developers immediately understand the three-tier architecture
2. **Expanded Use Cases**: Enables caching, rate limiting, monitoring, transformations
3. **Better Marketing**: Position Gatekit as "agentic workflow optimizer" not just security
4. **Honest Semantics**: Hidden tools are "not available" not "blocked for security"
5. **Extensibility**: Developers can add custom middleware for their specific needs
6. **Performance**: Caching and rate limiting become first-class features
7. **Debugging**: Pipeline tracking shows exactly how requests are transformed/completed

### Negative

1. **Additional Complexity**: Three plugin types instead of two
2. **Migration Work**: Moving tool_allowlist to middleware directory
3. **Documentation**: Need to explain the distinction clearly
4. **Testing**: More plugin interaction patterns to test

### Neutral

1. **Pipeline Processing**: Order matters more (middleware → security → server)
2. **Configuration**: New `middleware:` section in YAML configs
3. **Priority System**: Now spans middleware AND security plugins

## Implementation Notes

### Example: tool_manager Hiding a Tool
```python
async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
    if request.method != "tools/call":
        return PluginResult()  # Pass through

    tool_name = request.params.get("name")

    if tool_name not in self.allowed_tools:
        # Not "blocking" - the tool doesn't exist in the shaped capability surface
        error_response = MCPResponse(
            id=request.id,
            error={
                "code": -32601,  # Method not found
                "message": f"Tool '{tool_name}' is not available in this context",
                "data": {"reason": "capability_filtered"}
            }
        )
        return PluginResult(
            completed_response=error_response,
            reason="Tool hidden to reduce LLM context"
        )
```

### Example: Cache Middleware
```python
async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
    cache_key = self._generate_key(request)

    if cached := self.cache.get(cache_key):
        return PluginResult(
            completed_response=cached,
            reason="Cache hit"
        )

    return PluginResult()  # Continue to upstream
```

### Pipeline Behavior
1. All plugins (middleware and security) are intermixed and run in priority order (0-100)
2. If any plugin returns `completed_response`, pipeline stops
3. Security plugins can block (allowed=false) at any point in the pipeline
4. If request is blocked, pipeline stops immediately
5. Everything is audited with full pipeline visibility

## Alternatives Considered

### 1. Exception-Based Flow Control
Have middleware throw exceptions to "abort" processing:
- **Rejected**: Using exceptions for normal flow is an anti-pattern
- Adds complexity without benefit
- Makes debugging harder

### 2. Unified Plugin Type with Optional Blocking
Single plugin type that can optionally block:
- **Rejected**: Muddies the waters between functionality and security
- Makes it unclear when blocking is appropriate
- Harder to market and explain

### 3. Keep tool_allowlist as Security
Continue treating capability shaping as security:
- **Rejected**: Semantically dishonest
- Limits marketing message
- Doesn't solve the broader extensibility need

### 4. Two Middleware Types (Transforming vs Completing)
Separate middleware that transforms from middleware that completes:
- **Rejected**: Over-engineered
- Most middleware needs both capabilities
- Adds complexity without clear benefit

## Related Decisions

- **ADR-002**: Async architecture (middleware must be async)
- **ADR-006**: Plugin system design (middleware extends this)
- **ADR-007**: Response filtering (middleware can filter before security)
- **ADR-008**: Request/response processing order (middleware goes first)

## Future Considerations

### Standard Middleware Library
We should provide common middleware out of the box:
- Cache with configurable TTL
- Rate limiter with sliding windows
- Request/response logger
- Metrics collector
- Circuit breaker for unreliable servers

### Middleware Composition
Consider allowing middleware to be composed:
- Chain multiple transformations
- Conditional middleware based on routes
- Middleware groups with shared configuration

### Performance Optimizations
Since middleware runs on every request:
- Consider parallel execution where possible
- Add middleware benchmarking
- Optimize the pipeline for common patterns

## Decision Outcome

We will implement the three-tier plugin architecture with middleware plugins that can either transform or complete requests. This provides a clean mental model, enables powerful developer workflows, and positions Gatekit as more than just a security gateway - it becomes an essential tool for optimizing agentic interactions.

The key insight is that "completing" a request (providing a response) is fundamentally different from "blocking" a request (security denial). This semantic distinction drives the entire architecture.