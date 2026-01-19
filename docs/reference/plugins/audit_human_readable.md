# Human Readable Auditing

Log MCP requests, responses, and notifications in human-readable format for quick visual inspection and monitoring.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `audit_human_readable` |
| Type | Auditing |
| Scope | Global (can be configured globally or per-server) |

## How It Works

The human-readable auditing plugin:
1. Formats each MCP event as a single line for easy log scanning
2. Uses human-readable timestamps (YYYY-MM-DD HH:MM:SS UTC)
3. Shows method, tool name, server, and pipeline outcome on each line
4. Designed for `tail -f` monitoring and quick debugging

## Configuration Reference

### output_file

Path to the log file. Supports `~` for home directory.

**Type:** string
**Default:** `logs/gatekit_audit.log`
**Required:** Yes

> **Note:** Relative paths are resolved relative to the config file's directory.

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: audit_human_readable
    enabled: true
    output_file: logs/audit.log
```

### Full Configuration

```yaml
plugins:
  - handler: audit_human_readable
    enabled: true
    critical: false           # Don't block requests if logging fails
    output_file: logs/audit.log
```

### Console Output (for debugging)

```yaml
plugins:
  - handler: audit_human_readable
    enabled: true
    output_file: /dev/stdout  # Write to console
```

## Example Output

Each event is logged on a single line for easy scanning with `tail -f` and log analysis tools:

```
2025-01-12 15:30:45 UTC - REQUEST: tools/call - read_file - filesystem - ALLOWED
2025-01-12 15:30:45 UTC - RESPONSE - filesystem - success (0.045s)
2025-01-12 15:30:46 UTC - REQUEST: tools/call - write_file - filesystem - BLOCKED - Secret detected: 1 secret(s) found
2025-01-12 15:30:47 UTC - NOTIFICATION: $/progress - filesystem - NO_SECURITY
```

## Use Cases

### Real-Time Monitoring
```bash
tail -f logs/audit.log
```

### Quick Debugging
Human-readable format makes it easy to understand what's happening without parsing JSON.

### Development
See MCP traffic in a readable format while developing plugins or debugging issues.

## When to Use

| Format | Best For |
|--------|----------|
| Human Readable | Quick debugging, real-time monitoring, development |
| JSON Lines | Log aggregation, automated analysis, long-term storage |
| CSV | Spreadsheet analysis, simple reporting |

## Multiple Log Formats

You can run multiple auditing plugins simultaneously:

```yaml
plugins:
  # Human-readable for quick debugging
  - handler: audit_human_readable
    enabled: true
    output_file: logs/audit.log

  # JSON for log aggregation
  - handler: audit_jsonl
    enabled: true
    output_file: logs/audit.jsonl
    include_response_body: true
```

## Limitations

- **No message bodies** - Human-readable format doesn't include request/response bodies. Use JSON Lines for full body logging.
- **Not machine-parseable** - Use JSON Lines or CSV for automated analysis.
- **No configurable format** - The output format is fixed. For custom formats, consider writing a custom plugin.
