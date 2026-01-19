# ADR-010: Tools/List Response Filtering

**Note**: Tool management is now implemented as a **middleware plugin** (`tool_manager`), not a security plugin. The plugin uses implicit allowlist semantics (no `mode` field). See ADR-020 for middleware architecture.

## Context

Gatekit's tool manager plugin controls tool visibility and execution. The original implementation had a gap: clients could still discover hidden tools through `tools/list` requests, leading to:

1. **Information Disclosure**: Clients learn about tools they cannot execute
2. **Poor User Experience**: Users see tools they cannot use, causing confusion
3. **Security Inconsistency**: Policy applies to execution but not discovery
4. **Attack Surface**: Attackers can enumerate all available tools regardless of permissions

### Original Implementation Gap

```yaml
# Configuration allows specific tools
plugins:
  middleware:
    _global:
      - handler: "tool_manager"
        config:
          enabled: true
          priority: 50
          tools:
            - tool: "read_file"
            - tool: "write_file"
```

**Existing behavior**:
- `tools/call` with `read_file` → ✅ Allowed
- `tools/call` with `delete_file` → ❌ Blocked
- `tools/list` → Shows all tools including `delete_file` ⚠️ **Information leak**

## Decision

We will **extend the tool manager plugin to filter `tools/list` responses** according to the same allowlist that controls tool execution, ensuring consistent behavior across both tool discovery and tool execution.

### Unified Model

```python
class ToolManagerPlugin(MiddlewarePlugin):
    async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
        """Control tool execution (existing functionality)."""
        # Block tools/call for tools not in allowlist

    async def process_response(self, request: MCPRequest, response: MCPResponse, server_name: str) -> PluginResult:
        """Filter tool discovery (new functionality)."""
        # Filter tools/list to show only allowed tools
```

### Behavior

The tool manager uses **implicit allowlist semantics** (no `mode` field):

| Configuration | tools/call Behavior | tools/list Behavior |
|---------------|-------------------|-------------------|
| Tools in list | Allow execution | Show in list |
| Tools NOT in list | Block execution | Hide from list |

### Implementation Example

```python
async def process_response(self, request: MCPRequest, response: MCPResponse, server_name: str) -> PluginResult:
    if response.result and "tools" in response.result:
        # Filter tools list based on allowlist
        original_tools = response.result["tools"]
        filtered_tools = self._filter_tools(original_tools)

        if len(filtered_tools) != len(original_tools):
            # Create modified response with filtered tools
            modified_response = create_filtered_response(response, filtered_tools)
            return PluginResult(
                modified_content=modified_response,
                reason=f"Filtered {len(original_tools) - len(filtered_tools)} tools"
            )

    return PluginResult(reason="No filtering needed")
```

Note: Middleware plugins return `PluginResult` without setting `allowed` (security decision). The `modified_content` field holds the transformed response.

## Alternatives Considered

### Alternative 1: Warning-Based Approach

Show all tools but warn when blocked tools are called:

```json
{
  "tools": [
    {"name": "read_file", "description": "Read a file"},
    {"name": "delete_file", "description": "⚠️ Restricted - Delete a file"}
  ]
}
```

**Rejected because**:
- **Still leaks information**: Attackers learn about restricted tools
- **User confusion**: Users don't understand why some tools are marked restricted
- **Inconsistent security**: Discovery policy differs from execution policy
- **Implementation complexity**: Requires response modification anyway

### Alternative 2: Separate Discovery Policy

Allow different policies for discovery vs. execution:

```yaml
plugins:
  security:
    _global:
      - handler: "tool_manager"
        config:
          enabled: true
          priority: 50
          execution_mode: "allowlist"
          execution_tools: ["read_file"]
          discovery_mode: "allow_all"  # Show all, block execution
```

**Rejected because**:
- **Configuration complexity**: Doubles the configuration surface area
- **Security inconsistency**: Policies can diverge and create gaps
- **User confusion**: Hard to understand why visible tools can't be executed
- **Maintenance burden**: Two policies to keep in sync

### Alternative 3: Client-Side Filtering

Let clients discover all tools but expect them to respect allowlists:

**Rejected because**:
- **Zero security value**: Clients can ignore filtering entirely
- **Information disclosure**: Attackers learn full tool inventory
- **Trust model violation**: Security enforcement should be server-side
- **Poor user experience**: Clients must implement their own filtering logic

### Alternative 4: Dynamic Tool Registration

Only register allowed tools with the upstream server:

**Rejected because**:
- **Architectural complexity**: Requires upstream server modification
- **Runtime inflexibility**: Can't change policies without server restart
- **Multiple client support**: Hard to support different policies per client
- **Proxy bypass**: Defeats the purpose of a security proxy

## Consequences

### Positive

- **Consistent Security**: Same policy controls both discovery and execution
- **Information Protection**: Clients only see tools they can actually use
- **Better User Experience**: No confusion about unavailable tools
- **Security Defense in Depth**: Multiple layers enforce the same policy
- **Clean Mental Model**: One policy, consistent enforcement

### Negative

- **Response Modification Complexity**: Requires sophisticated response filtering
- **Performance Overhead**: Additional processing for every tools/list response
- **Debugging Complexity**: Tools "disappear" from discovery, harder to troubleshoot
- **Client Assumption Breaking**: Clients might assume discovery == availability

### Risk Mitigation

1. **Comprehensive Audit Logging**: Log all filtering decisions for transparency
2. **Detailed Documentation**: Explain filtering behavior and troubleshooting
3. **Allow-All Mode**: Provide escape hatch for debugging and development
4. **Error Handling**: Graceful degradation when filtering fails

## Implementation Details

### Filtering Logic

```python
def _filter_tools(self, tools_list: List[Dict]) -> List[Dict]:
    """Filter tools list according to allowlist."""
    filtered_tools = []
    for tool in tools_list:
        if not isinstance(tool, dict) or "name" not in tool:
            continue  # Skip malformed tools

        tool_name = tool["name"]

        # Implicit allowlist: only show tools in the configured list
        if tool_name in self.allowed_tools:
            filtered_tools.append(tool)

    return filtered_tools
```

The tool manager also supports **tool renaming** - tools can be displayed with different names/descriptions to clients while preserving the actual tool name for execution.

### Audit Logging

```python
# Log filtering decisions for security audit
logger.info(
    f"Tool manager filtered tools/list response: "
    f"original={len(original_tools)} tools, filtered={len(filtered_tools)} tools, "
    f"removed={removed_tool_names}, allowed={allowed_tool_names}, "
    f"request_id={response.id}"
)
```

### Configuration Example

```yaml
plugins:
  middleware:
    _global:
      - handler: "tool_manager"
        config:
          enabled: true
          priority: 50
          tools:
            - tool: "read_file"
            - tool: "write_file"
            - tool: "list_directory"
          # This applies to BOTH:
          # 1. tools/call requests (execution control)
          # 2. tools/list responses (discovery control)
```

Tools can also be renamed for display:
```yaml
tools:
  - tool: "internal_read_file"
    display_name: "read_file"
    display_description: "Read file contents"
```

### Error Handling

Error handling for tool filtering follows the plugin's `critical` setting (default: `true`). See ADR-006 for critical plugin failure modes.

This unified model ensures that Gatekit provides consistent behavior for both tool execution and tool discovery, eliminating information disclosure while improving user experience.
