# Tool Manager

Control which tools are visible to MCP clients using an allowlist. Filter, rename, and modify tool descriptions to optimize context and simplify workflows.

> **Note:** This is a middleware plugin, NOT a security plugin. Tools are filtered for operational purposes (context optimization, workflow simplification). For security-based tool restrictions, implement a separate security plugin.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `tool_manager` |
| Type | Middleware |
| Scope | Server-aware (must be configured per-server) |

## How It Works

The tool manager uses an **allowlist** approach:
- Only tools explicitly listed in `tools` are visible to the MCP client
- Empty `tools` list blocks all tools
- Unlisted tools are hidden from `tools/list` responses
- Calls to hidden tools return a "method not found" error

The plugin intercepts:
1. **`tools/list` responses** - Filters and renames tools before they reach the client
2. **`tools/call` requests** - Translates renamed tools back to original names, blocks hidden tools

## Configuration Reference

### tools

An array of tool entries. Each entry specifies a tool to allow and optionally rename.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tool` | string | Yes | Original tool name from the upstream server |
| `display_name` | string | No | Override the tool name shown to clients |
| `display_description` | string | No | Override the tool description shown to clients |

**Tool name format:** Must start with a letter, contain only letters, numbers, underscores, or hyphens.

## YAML Configuration

### Minimal Configuration (Allow Specific Tools)

```yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@anthropic-ai/mcp-server-filesystem", "/path/to/allowed"]
    plugins:
      - handler: tool_manager
        enabled: true
        tools:
          - tool: read_file
          - tool: list_directory
```

### Full Configuration with Renaming

```yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@anthropic-ai/mcp-server-filesystem", "/path/to/allowed"]
    plugins:
      - handler: tool_manager
        enabled: true
        tools:
          - tool: read_file
            display_name: read
            display_description: "Read contents of a file"
          - tool: write_file
            display_name: write
            display_description: "Write content to a file"
          - tool: list_directory
            display_name: ls
            display_description: "List files in a directory"
```

### Block All Tools

```yaml
servers:
  dangerous-server:
    command: ./run-server.sh
    plugins:
      - handler: tool_manager
        enabled: true
        tools: []    # Empty list blocks all tools
```

### Context Optimization Example

Reduce context usage by exposing only essential tools with shorter names:

```yaml
servers:
  filesystem:
    command: npx
    args: ["-y", "@anthropic-ai/mcp-server-filesystem", "/workspace"]
    plugins:
      - handler: tool_manager
        enabled: true
        tools:
          # Only expose read operations
          - tool: read_file
            display_name: read
          - tool: list_directory
            display_name: ls
          - tool: search_files
            display_name: search
          # Block: write_file, create_directory, move_file, etc.
```

## Use Cases

### Context Window Optimization
Hide tools that aren't needed to reduce context usage. Each hidden tool saves tokens from tool listings.

### Workflow Simplification
Rename tools to shorter, more intuitive names. `read_file` → `read`, `list_directory` → `ls`.

### Capability Restriction
Limit what operations an MCP client can perform. Allow read operations but hide write/delete.

### Description Enhancement
Provide better descriptions than the upstream server offers, improving AI tool selection.

## Validation Rules

- **No duplicates:** Each tool can only appear once in the list
- **No self-renaming:** Cannot rename a tool to its own name
- **No name collisions:** Cannot rename tool A to tool B if tool B exists in the list
- **Valid names:** Tool names must match `^[a-zA-Z][a-zA-Z0-9_-]*$`

## Error Handling

When a client tries to call a hidden tool:

```json
{
  "error": {
    "code": -32601,
    "message": "Tool 'hidden_tool' is not available",
    "data": {
      "reason": "hidden_by_policy",
      "plugin": "tool_manager"
    }
  }
}
```

## Important Notes

- **Server-aware plugin:** Must be configured under a specific server, not in the global `plugins` section
- **Allowlist only:** There is no denylist mode - only listed tools are visible
- **Not for security:** This plugin filters for operational purposes. Determined users could potentially bypass middleware restrictions.
