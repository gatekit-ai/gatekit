# Gatekit Routing Model

**Version**: 0.1.0  
**Status**: Authoritative Reference  

> **Note**: This document describes the ACTUAL behavior of the Gatekit routing model as implemented. It serves as the single source of truth for routing and namespacing decisions.

## Table of Contents

1. [Core Concepts](#core-concepts)
2. [Namespacing Requirements](#namespacing-requirements)
3. [Request Flow](#request-flow)
4. [Routing Components](#routing-components)
5. [Boundary Translation Pattern](#boundary-translation-pattern)
6. [Error Handling](#error-handling)
7. [Multi-Server Operations](#multi-server-operations)
8. [Example Scenarios](#example-scenarios)

## Core Concepts

### Purpose of Routing

Gatekit acts as a proxy between MCP clients (like Claude Code) and multiple upstream MCP servers. The routing system:
- **Directs requests** to the appropriate upstream server
- **Maintains namespace isolation** between servers
- **Preserves clean interfaces** for internal processing
- **Enables per-server security policies**

### Namespace Format

Tool calls use a double-underscore (`__`) separator:
```
server__tool_name
```

Examples:
- `filesystem__read_file` - Routes the `read_file` tool to the `filesystem` server
- `github__create_issue` - Routes the `create_issue` tool to the `github` server
- `puppeteer__screenshot` - Routes the `screenshot` tool to the `puppeteer` server

### Key Principles

1. **No Single-Server Special Cases**: ALL tool calls must be namespaced, even with one server
2. **Parse Once at Ingress**: Namespace extraction happens exactly once when the request enters
3. **Clean Internal Representation**: All internal processing uses denamespaced tool names
4. **Restore at Egress**: Namespacing is restored in error messages for the client
5. **Preserved Context**: Original namespaced names are preserved for error messages and auditing

## Namespacing Requirements

### Tool Calls Require Namespacing

The `tools/call` method **MUST** include a server namespace:

```json
{
  "method": "tools/call",
  "params": {
    "name": "server__tool_name",
    "arguments": {...}
  }
}
```

### Broadcast Methods (No Namespacing)

These methods are sent to ALL servers without namespacing:

| Method | Behavior |
|--------|----------|
| `initialize` | Sent to all servers for protocol handshake |
| `tools/list` | Aggregated from all servers with namespacing applied |
| `resources/list` | Aggregated from all servers (experimental) |
| `prompts/list` | Aggregated from all servers (experimental) |

> **Note**: Gatekit v0.1.0 focuses on **tool management**. Resources and prompts have basic aggregation support but are **experimental and untested**. Use at your own risk.

### Invalid Namespace Errors

Requests without proper namespacing receive JSON-RPC error responses:

```json
{
  "jsonrpc": "2.0",
  "id": "request-id",
  "error": {
    "code": -32602,  // Invalid params
    "message": "Tool 'my_tool' is not properly namespaced. All tool calls must use 'server__tool' format"
  }
}
```

## Request Flow

### 1. Client Request Arrives
```python
# Client sends namespaced request
{
  "method": "tools/call",
  "params": {"name": "filesystem__read_file", "arguments": {...}}
}
```

### 2. Parse at Ingress (Once)
```python
# parse_incoming_request() extracts namespace ONCE
routed = parse_incoming_request(request)
# Returns RoutedRequest with:
#   - request: Clean MCPRequest with name="read_file"
#   - target_server: "filesystem"
#   - namespaced_name: "filesystem__read_file" (preserved for errors)
```

### 3. Plugin Processing (Clean)
```python
# Plugins see CLEAN request without namespacing
pipeline = await plugin_manager.process_request(
    routed.request,  # Clean: name="read_file"
    routed.target_server  # "filesystem"
)
```

### 4. Server Validation
```python
# AFTER plugins (allows future routing plugins)
if routed.target_server and not is_broadcast_method():
    if not server_exists(routed.target_server):
        return error_response("Unknown server 'filesystem'")
```

### 5. Route to Upstream
```python
# Send clean request to target server
response = await route_request(routed)
# Upstream sees: name="read_file" (no namespace)
```

### 6. Response Processing
```python
# Response plugins also see clean request
response_pipeline = await plugin_manager.process_response(
    routed.request,  # Still clean
    response,
    routed.target_server
)
```

### 7. Restore at Egress
```python
# Re-namespace error messages for client
final = prepare_outgoing_response(response, routed)
# Error: "Tool read_file not found" → "Tool filesystem__read_file not found"
```

## Routing Components

### RoutedRequest Data Structure

The `RoutedRequest` class carries both the clean request and routing context:

```python
@dataclass
class RoutedRequest:
    request: MCPRequest           # Clean, denamespaced request
    target_server: Optional[str]  # Extracted server name
    namespaced_name: Optional[str] # Original for error formatting
```

### Core Functions

#### parse_incoming_request()
- **Purpose**: Single parsing point at system ingress
- **Input**: Original namespaced MCPRequest
- **Output**: RoutedRequest with clean request OR MCPResponse error
- **Auditing**: Parse-time rejections are logged for security visibility

#### prepare_outgoing_response()
- **Purpose**: Restore namespacing in error messages
- **Input**: MCPResponse and RoutedRequest
- **Output**: MCPResponse with re-namespaced error messages
- **Method**: Regex with word boundaries (e.g., won't replace "sum" in "summary")

### Routing Invariants

The `RoutedRequest.update_request()` method enforces:
1. **Request ID cannot change** - Maintains correlation
2. **Method cannot change** - Request type is immutable

Attempts to violate these raise `ValueError`. This prevents stale namespacing.

> **Note**: Tool names (in `params.name`) can be modified by plugins. The routing context preserves the original namespaced name in `namespaced_name` for error message formatting, even if a plugin modifies the denamespaced tool name in the request.

## Boundary Translation Pattern

### Why Boundary Translation?

The system implements a **boundary translation pattern** where:
- **External boundaries** use namespacing (client ↔ proxy, proxy ↔ servers)
- **Internal processing** uses clean identifiers (plugins, logging, validation)

Benefits:
1. **Plugins don't need namespacing logic** - Simpler plugin development
2. **Single parsing point** - No redundant extraction or inconsistencies
3. **Clean error handling** - Errors reference what the client requested
4. **Performance** - Parse once, not repeatedly

### Information Preservation

The original namespaced identifier is preserved in `namespaced_name` for:
- **Error message formatting** - Client sees errors about what they requested
- **Audit logging** - Complete request tracking
- **Debugging** - Full context available

## Error Handling

### Parse-Time Errors

Invalid namespacing is caught immediately and returns structured errors:

```python
if "__" not in tool_name:
    return MCPResponse(
        error={
            "code": -32602,  # Invalid params
            "message": f"Tool '{tool_name}' is not properly namespaced..."
        }
    )
```

These rejections are **audited** even though they don't reach normal processing.

### Server Validation Timing

Server existence is validated **AFTER** plugin processing:
- **Rationale**: Allows future routing plugins to redirect/create virtual servers
- **Trade-off**: Some plugin CPU on impossible routes, but maximum flexibility
- **Audit benefit**: Can log attempts to unknown servers

### Error Message Re-namespacing

Error messages from upstream servers are re-namespaced:

```python
# Upstream error: "Tool 'read_file' not found"
# Client sees: "Tool 'filesystem__read_file' not found"

# Uses regex word boundaries to avoid partial matches:
pattern = r'\b' + re.escape("read_file") + r'\b'
# Won't match "read_file" in "thread_file_reader"
```

## Multi-Server Operations

### Tools List Aggregation

The `tools/list` method aggregates tools from all servers:

1. **Request broadcast** to all configured servers
2. **Each server responds** with its available tools
3. **Proxy aggregates** responses
4. **Namespacing applied** to each tool (e.g., `read_file` → `filesystem__read_file`)
5. **Security filtering** per server's configured plugins
6. **Unified response** sent to client

### Server-Specific Security

Each server can have different security policies:

```yaml
plugins:
  middleware:
    filesystem:
      - handler: tool_manager
        config:
          mode: "allowlist"
          tools: ["read_file", "list_directory"]
    
    github:
      - handler: tool_manager
        config:
          mode: "allowlist"
          tools: ["create_issue", "list_repos"]
```

The routing system ensures policies are applied to the correct server's requests.

### Concurrent Request Handling

- Multiple requests can be processed simultaneously
- Each maintains independent `RoutedRequest` context
- Request limiting prevents overwhelming upstreams (default: 100 concurrent)

## Example Scenarios

### Scenario 1: Valid Tool Call

**Client Request:**
```json
{
  "method": "tools/call",
  "params": {"name": "filesystem__read_file", "arguments": {"path": "/etc/hosts"}}
}
```

**Processing:**
1. Parse: Extract `filesystem` server, `read_file` tool
2. Plugins see: `name="read_file"`
3. Route to: `filesystem` server
4. Upstream sees: `name="read_file"`
5. Response returned to client

### Scenario 2: Missing Namespace

**Client Request:**
```json
{
  "method": "tools/call",
  "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}}
}
```

**Result:**
```json
{
  "error": {
    "code": -32602,
    "message": "Tool 'read_file' is not properly namespaced. All tool calls must use 'server__tool' format"
  }
}
```

### Scenario 3: Unknown Server

**Client Request:**
```json
{
  "method": "tools/call",
  "params": {"name": "unknown__read_file", "arguments": {...}}
}
```

**Result:**
```json
{
  "error": {
    "code": -32602,
    "message": "Unknown server 'unknown' in request"
  }
}
```

### Scenario 4: Tool Not Found

**Client Request:**
```json
{
  "method": "tools/call",
  "params": {"name": "filesystem__nonexistent", "arguments": {...}}
}
```

**Upstream Error:**
```json
{
  "error": {
    "message": "Tool 'nonexistent' not found"
  }
}
```

**Client Sees (re-namespaced):**
```json
{
  "error": {
    "message": "Tool 'filesystem__nonexistent' not found"
  }
}
```

### Scenario 5: Aggregated Tools List

**Client Request:**
```json
{
  "method": "tools/list"
}
```

**Aggregated Response:**
```json
{
  "result": {
    "tools": [
      {"name": "filesystem__read_file", "description": "Read a file"},
      {"name": "filesystem__write_file", "description": "Write a file"},
      {"name": "github__create_issue", "description": "Create an issue"},
      {"name": "github__list_repos", "description": "List repositories"}
    ]
  }
}
```

Each tool is namespaced with its server prefix.

### Scenario 6: Plugin Modification of Tool Name

**Plugin Modifies Tool:**
```python
# Middleware plugin renames tool (e.g., for aliasing)
new_params = dict(request.params) if isinstance(request.params, dict) else {}
new_params["name"] = "aliased_tool"  # was "original_tool"
modified_request = MCPRequest(
    jsonrpc=request.jsonrpc,
    id=request.id,
    method=request.method,
    params=new_params,
)
return PluginResult(modified_content=modified_request, reason="Tool renamed")
```

**Result:**
- The modified tool name is used for upstream communication
- The original namespaced name is preserved in `routed.namespaced_name` for error formatting
- Error messages to the client use the original name the client requested

> **Note**: Tool name modifications are allowed. Only request ID and method changes are blocked by `update_request()`.

## Configuration

### Basic Multi-Server Setup

```yaml
upstreams:
  - name: filesystem
    command: ["npx", "@modelcontextprotocol/server-filesystem", "/"]
  
  - name: github
    command: ["npx", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
  
  - name: puppeteer
    command: ["npx", "@modelcontextprotocol/server-puppeteer"]
```

### Client Configuration (Claude Desktop)

```json
{
  "mcpServers": {
    "gatekit": {
      "command": "gatekit",
      "args": ["--config", "/path/to/gatekit.yaml"]
    }
  }
}
```

The client only knows about Gatekit, not the individual upstream servers.

## Design Rationale

### Why Require Namespacing?

1. **Explicit routing** - No ambiguity about target server
2. **Tool collision prevention** - Multiple servers can have same tool names
3. **Security isolation** - Clear boundaries for policy application
4. **Future compatibility** - Enables dynamic routing features

### Why Parse Once?

1. **Performance** - Single extraction vs repeated parsing
2. **Consistency** - One source of truth for routing decisions
3. **Simplicity** - Clear separation of concerns
4. **Correctness** - No parsing inconsistencies

### Plugin Trust Model

1. **Plugins are trusted** - They are internal Gatekit components, not external actors
2. **Transformations allowed** - Middleware and security plugins can transform requests (e.g., tool renaming, content redaction)
3. **Security evaluated** - All plugins (middleware and security) are processed in priority order
4. **Audit complete** - All transformations are tracked in the ProcessingPipeline
5. **Context preserved** - Original namespaced names remain available for error formatting

## Future Considerations

### Potential Enhancements

1. **Dynamic routing plugins** - Redirect based on load/availability
2. **Virtual servers** - Plugin-created logical servers
3. **Routing rules** - Pattern-based routing decisions
4. **Fallback servers** - Automatic failover

These would require relaxing routing immutability with careful design.

## Implementation Notes

This document reflects actual behavior as of Gatekit v0.1.0. The implementation is in:
- `/gatekit/core/routing.py`: Core routing logic and boundary translation
- `/gatekit/proxy/server.py`: Request flow and server validation
- `/gatekit/server_manager.py`: Multi-server connection management
- Tests in `/tests/unit/test_routing.py` and `/tests/integration/`

---

## Summary

### Key Takeaways

1. **All tool calls must be namespaced** - No exceptions, even for single server
2. **Parse once, use everywhere** - Single extraction point at ingress
3. **Clean internal processing** - Plugins see denamespaced tool names
4. **Restore for client** - Error messages use original namespaced format
5. **Routing context is preserved** - Original namespaced names preserved for error formatting
6. **Tools/list aggregates** - Combines tools from all servers with namespacing
7. **Per-server security** - Each server has independent policies

### Common Misconceptions

1. ❌ **"Single server doesn't need namespacing"** → ALL tool calls need namespacing
2. ❌ **"Plugins see namespaced tools"** → Plugins see clean, denamespaced tool names
3. ❌ **"Middleware cannot modify tool names"** → Plugins can modify tool names; only ID and method are immutable
4. ❌ **"Server validation happens first"** → Happens AFTER plugins for flexibility
5. ❌ **"Each server needs client config"** → Client only configures Gatekit

### Quick Reference

| Component | Purpose |
|-----------|---------|
| `parse_incoming_request()` | Extract namespace once at ingress |
| `RoutedRequest` | Carry clean request + routing context |
| `prepare_outgoing_response()` | Re-namespace error messages |
| `server__tool_name` | Namespace format for tools |
| `tools/list` | Aggregate tools from all servers |

---