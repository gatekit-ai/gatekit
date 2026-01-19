# ADR-014: Multi-Server Support Architecture

## Context

Gatekit supports proxying to one or more upstream MCP servers. Real-world usage patterns often require connecting to multiple MCP servers simultaneously:

1. **Specialized Servers**: Different servers provide different capabilities (filesystem, GitHub, databases, etc.)
2. **Service Isolation**: Separate servers for different security domains or environments
3. **Performance Distribution**: Load distribution across multiple server instances
4. **Flexible Deployment**: Ability to start with one server and add more servers over time

The architecture provides:
- Consistent behavior whether using one or multiple servers
- Clean tool discovery and routing
- Consistent security policy application across all servers
- Simple client experience without protocol changes

## Decision

We implemented a **flat list configuration architecture** with intelligent request routing:

### Core Architecture

1. **ServerManager**: Centralized management of multiple upstream server connections
2. **Tool Name Prefixing**: Automatic prefixing of tool names with server identifiers
3. **Request Routing**: Parse tool names to route requests to appropriate servers
4. **Consistent Architecture**: Unified handling whether one or multiple servers are configured

### Configuration Design

```yaml
# Single server (ALL servers must have names for consistency)
upstreams:
  - name: "filesystem"
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/"]

# Multiple servers
upstreams:
  - name: "filesystem"
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/"]
  - name: "github"
    command: ["npx", "-y", "@modelcontextprotocol/server-github"]
```

**IMPORTANT**: All servers MUST have names. This simplifies plugin configuration and provides consistent architecture.

### Tool Discovery and Routing

```python
# Tool names are automatically prefixed with double underscore separator
# Original: "read_file" -> Multi-server: "filesystem__read_file"
# Original: "create_issue" -> Multi-server: "github__create_issue"

def _parse_tool_name(self, tool_name: str) -> Tuple[str, str]:
    """Parse server name and original tool name"""
    if '__' in tool_name:
        parts = tool_name.split('__', 1)
        if parts[0] in self.server_manager.servers:
            return parts[0], parts[1]
    return "default", tool_name
```

### Implementation Components

1. **ServerManager Class**: Handles lifecycle management of multiple server connections
2. **Enhanced UpstreamServer**: Supports named instances and tool prefixing
3. **Request Routing Layer**: Intelligent routing based on tool name parsing
4. **Plugin Context Extension**: Security plugins receive server context information

## Alternatives Considered

### Alternative 1: Hierarchical Configuration
```yaml
servers:
  filesystem:
    type: "mcp"
    config:
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
  github:
    type: "mcp"
    config:
      command: ["npx", "-y", "@modelcontextprotocol/server-github"]
```

**Rejected**: More complex, harder to migrate existing configurations, over-engineered for current needs.

### Alternative 2: Route-Based Configuration
```yaml
routes:
  - pattern: "file_*"
    server: "filesystem"
  - pattern: "github_*"
    server: "github"
```

**Rejected**: Requires explicit routing rules, more configuration overhead, less intuitive.

### Alternative 3: Namespace-Based Tools
```yaml
servers:
  - namespace: "fs"
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem"]
```

**Rejected**: Requires client-side namespace awareness, breaks MCP protocol transparency.

## Implementation Strategy

### Phase 1: Infrastructure (Completed)
- `ServerManager` class for connection management
- Configuration schema updates with validation
- `UpstreamServer` enhancements for named instances
- Backward compatibility preservation

### Phase 2: Core Functionality (Completed)
- Tool name prefixing and parsing
- Request routing logic
- Plugin context extensions
- Error handling and graceful degradation

### Phase 3: Production Features (Completed)
- Concurrent server startup
- Connection health monitoring
- Comprehensive test coverage
- Documentation and examples

## Migration Strategy

**Zero-Breaking-Change Migration**:
1. Existing `upstream_server` configurations continue to work unchanged
2. New `upstream_servers` provides multi-server capabilities
3. Configuration validation prevents mixing both approaches
4. All tool names are namespaced consistently (unified multi-server architecture)

Example migration:
```yaml
# Before (continues to work)
upstream_server:
  command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/"]

# After (new capability)
upstream_servers:
  - name: "filesystem"
    command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/"]
```

## Security Implications

### Enhanced Security Context
- Security plugins receive server context information
- Per-server security policies possible
- Audit logging tracks which server handled each request
- Resource isolation between servers

### Security Benefits
- **Principle of Least Privilege**: Each server can have different security rules
- **Failure Isolation**: One server's compromise doesn't affect others
- **Audit Trail**: Clear tracking of which server processed each request

## Performance Considerations

### Optimization Features
- **Concurrent Server Startup**: All servers start in parallel
- **Connection Reuse**: Efficient connection pooling per server
- **Tool Caching**: Reduced discovery overhead
- **Lazy Loading**: Servers only connect when needed

### Performance Impact
- Minimal overhead: Tool name parsing is O(1) operation
- Parallel operations: Multiple servers can handle requests concurrently
- Graceful degradation: System continues with available servers

## Testing Strategy

### Comprehensive Coverage
- **Unit Tests**: ServerManager lifecycle, tool parsing, configuration validation
- **Integration Tests**: Multi-server startup, request routing, plugin integration
- **E2E Tests**: Real MCP servers, client compatibility, performance validation

### Test Scenarios
- Single server backward compatibility
- Multi-server tool discovery and routing
- Server failure handling and recovery
- Security plugin integration with server context

## Configuration Schema

```python
class UpstreamConfig(BaseModel):
    """Configuration for a single upstream server"""
    name: str = Field(..., description="Unique server identifier")
    command: List[str] = Field(..., description="Command and arguments to start the server")
    # Note: Environment variables are NOT configurable per-server.
    # Set environment variables in your MCP client or shell instead.
    
class GatewayConfig(BaseModel):
    """Updated gateway configuration"""
    upstream_server: Optional[ServerConfigLegacy] = None  # Backward compatibility
    upstream_servers: Optional[List[ServerConfig]] = None  # New multi-server
    
    @validator('upstream_servers')
    def validate_server_config(cls, v, values):
        if v and values.get('upstream_server'):
            raise ValueError("Cannot specify both upstream_server and upstream_servers")
        return v
```

## Consequences

### Positive
- **Enhanced Capability**: Connect to multiple specialized MCP servers
- **Backward Compatibility**: Existing configurations continue to work
- **Clean Architecture**: Extends existing patterns without breaking them
- **Security Enhancement**: Per-server security policies and audit trails
- **Performance Benefits**: Parallel server operations and connection reuse
- **Future-Proof**: Foundation for advanced features like load balancing

### Negative
- **Increased Complexity**: More sophisticated connection management
- **Tool Name Changes**: Multi-server mode changes tool names (with prefixes)
- **Configuration Overhead**: More complex configuration when using multiple servers
- **Resource Usage**: Additional memory and connections for multiple servers

### Neutral
- **Client Compatibility**: No changes required for MCP clients
- **Plugin Compatibility**: Existing plugins work with minor context enhancements
- **Operational Impact**: Monitoring and troubleshooting slightly more complex

## Decision Rationale

The flat list configuration with tool name prefixing was chosen because:

1. **Simplicity**: Straightforward configuration and mental model
2. **Compatibility**: Zero breaking changes for existing users
3. **Transparency**: Works with any MCP client without modifications
4. **Scalability**: Efficient resource management and concurrent operations
5. **Security**: Maintains Gatekit's security-first approach
6. **Maintainability**: Clean code architecture that extends existing patterns

This approach provides a solid foundation for multi-server support while preserving the simplicity and reliability that are core to Gatekit's design philosophy.

## Future Enhancements

1. **Dynamic Server Management**: Runtime addition/removal of servers
2. **Load Balancing**: Distribute requests across multiple instances of the same server
3. **Health Monitoring**: Advanced health checks and automatic failover
4. **Configuration Templating**: Simplified configuration for common patterns
5. **Tool Conflict Resolution**: Strategies for handling duplicate tool names