# ADR-015: Proxy-Based Capability Discovery

## Context
Gatekit operates as a transparent proxy between MCP clients and servers. A key question arose about how to handle capability discovery: should Gatekit proactively discover server capabilities during connection, or should it operate purely as a pass-through proxy that only responds to client-initiated requests?

## Decision
**Gatekit does NOT perform proactive capability discovery. Instead, it operates as a transparent proxy that broadcasts capability requests from clients to servers.**

### Key Principles:

1. **Transparent Proxy Operation**: Gatekit forwards client requests to appropriate servers without modification, except for security filtering and auditing.

2. **Client-Driven Discovery**: Capabilities are only discovered when clients explicitly request them via:
   - `initialize` requests (broadcast to all servers)
   - `tools/list` requests (broadcast to all servers, results aggregated)
   - `resources/list` requests (broadcast to all servers, results aggregated)  
   - `prompts/list` requests (broadcast to all servers, results aggregated)

3. **Broadcast Aggregation**: For multi-server configurations, Gatekit:
   - Broadcasts `*/list` requests to all connected servers
   - Aggregates responses from all servers
   - Adds server name prefixes to avoid naming conflicts (`server__tool_name`)
   - Returns unified response to client

4. **Optional Caching**: Gatekit MAY cache capability responses for performance and monitoring purposes, but this caching is:
   - Purely opportunistic (populated only after client requests)
   - Used for administrative/monitoring purposes
   - Never used to modify proxy behavior

## Implementation

### Server Connection Process
During server connection, Gatekit only:
1. Establishes transport connection
2. Sends `initialize` request to verify connectivity
3. Marks server as connected
4. **Does NOT** send `tools/list`, `resources/list`, or `prompts/list` requests

### Client Request Handling
When clients send capability discovery requests:
1. `initialize` → Broadcast to all servers, return aggregated response
2. `tools/list` → Broadcast to all servers, aggregate tool lists with namespacing
3. `resources/list` → Broadcast to all servers, aggregate resource lists with namespacing
4. `prompts/list` → Broadcast to all servers, aggregate prompt lists with namespacing

### Server Namespacing
For all server configurations:
- Tools: `server_name__tool_name`
- Resources: `server_name__resource_uri`  
- Prompts: `server_name__prompt_name`

Namespacing is applied consistently regardless of the number of configured servers.

## Rationale

### Why NOT Proactive Discovery?

1. **Proxy Semantics**: Gatekit is a proxy, not an MCP client. Proactive discovery would blur this distinction and potentially interfere with client-server interactions.

2. **Performance**: Capability discovery adds latency to server connections. Many use cases may not need immediate capability information.

3. **Client Control**: Clients should control when and how they discover capabilities, not have this imposed by the proxy.

4. **Error Handling**: Failed capability discovery during connection could unnecessarily prevent server connections that might otherwise work.

5. **Protocol Compliance**: The MCP protocol doesn't require proxies to perform capability discovery.

### Why Broadcast Approach?

1. **Transparency**: Client sees the same interface whether connecting directly to servers or through Gatekit.

2. **Unified Experience**: Multi-server setups appear as a single, unified MCP server to clients.

3. **Namespace Management**: Gatekit can resolve naming conflicts between servers automatically.

4. **Filtering Integration**: Security plugins can filter capabilities just like any other MCP communication.

## Consequences

### Positive
- Simple, predictable proxy behavior
- No connection-time capability discovery overhead
- Full client control over discovery timing
- Easy to understand and debug
- Consistent with proxy architectural patterns

### Negative  
- Capabilities not immediately available after server connection
- Administrative interfaces may show empty capabilities until first client request
- Slight complexity in broadcast aggregation logic

## Compliance
This decision aligns with:
- MCP Protocol Specification (proxies are not required to be MCP clients)
- Standard proxy architectural patterns
- Gatekit's design principle of transparent operation

## Future Considerations
- Administrative endpoints may implement separate capability discovery for monitoring
- Caching strategies could be enhanced for performance
- Health check endpoints might trigger capability refresh independently

## Related ADRs
- ADR-001: Transport Layer Selection
- ADR-002: Asynchronous Architecture  
- ADR-010: Response Filtering and Modification
- ADR-011: Concurrent Request Handling
- ADR-014: Multi-Server Support