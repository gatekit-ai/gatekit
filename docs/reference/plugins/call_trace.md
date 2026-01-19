# Call Trace

Append diagnostic trace information to tool responses for debugging, visibility, and audit log correlation.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `call_trace` |
| Type | Middleware |
| Scope | Global (can be configured globally or per-server) |
| Default Priority | 90 (runs late in pipeline) |

## How It Works

The call trace plugin:
1. Records the start time when a `tools/call` request arrives
2. After the response returns, appends a formatted trace block to the response content
3. Provides visibility into which server handled the request, timing, and audit log correlation

This is useful for:
- **Debugging** - See exactly what happened for each tool call
- **Multi-server visibility** - Know which server handled the request
- **Audit correlation** - Find related entries in audit logs using request ID and timestamp

## Example Output

```
---
🔍 **Gatekit Gateway Trace**
- Server: filesystem
- Tool: read_file
- Params: {"path": "/home/user/projects/gatekit/README.md"}
- Response: 2.3 KB
- Duration: 45ms
- Request ID: 1
- Timestamp: 2025-01-12T15:30:45Z

Search your audit logs near timestamp 2025-01-12T15:30:45Z (request_id: 1) to see the audit trail for this request.
To find audit log locations, open your Gatekit config using `gatekit <path_to_config.yaml>`
---
```

## Configuration Reference

### max_param_length

Maximum characters to display for tool parameters. Longer values are truncated with `...`.

**Type:** integer (minimum: 0)
**Default:** `200`

### trace_fields

Configure which fields appear in the trace output.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server` | boolean | `true` | Which server handled the request |
| `tool` | boolean | `true` | Which tool was called |
| `params` | boolean | `true` | Tool call parameters (respects max_param_length) |
| `response_size` | boolean | `true` | Response size (e.g., "2.3 KB") |
| `duration` | boolean | `true` | Processing time in milliseconds |
| `request_id` | boolean | `true` | MCP request ID for audit log correlation |
| `timestamp` | boolean | `true` | ISO 8601 timestamp |

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: call_trace
    enabled: true
```

### Full Configuration

```yaml
plugins:
  - handler: call_trace
    enabled: true
    priority: 90              # Run late in pipeline (after other middleware)
    critical: false           # Don't block requests if tracing fails

    max_param_length: 200     # Truncate params longer than 200 chars

    trace_fields:
      server: true            # Show server name
      tool: true              # Show tool name
      params: true            # Show parameters
      response_size: true     # Show response size
      duration: true          # Show timing
      request_id: true        # Show request ID
      timestamp: true         # Show timestamp
```

### Minimal Trace (Reduced Noise)

```yaml
plugins:
  - handler: call_trace
    enabled: true
    max_param_length: 50      # Shorter param display

    trace_fields:
      server: true
      tool: true
      params: false           # Hide parameters
      response_size: false    # Hide size
      duration: true          # Keep timing
      request_id: true        # Keep for correlation
      timestamp: false        # Hide timestamp
```

## Known Issues

**MCP servers with structuredContent:** Some MCP servers return both `content` and `structuredContent` in their responses (e.g., `memory`, `sequential-thinking`). Claude Code appears to prefer displaying `structuredContent` when both are present, so the trace may not be visible in the UI. However, the trace IS recorded in audit logs regardless of client display behavior.

## Fail-Open Behavior

The call trace plugin is designed to fail open:
- If an error occurs during trace generation, the original response is returned unmodified
- Errors are logged but don't block the request
- Consider setting `critical: false` to ensure trace failures never block requests
