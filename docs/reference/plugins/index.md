# Built-in Plugins

Gatekit ships with plugins for common security, middleware, and auditing use cases. Use the TUI (`gatekit`) to configure plugins interactively, or see individual plugin pages for YAML configuration details.

All built-in plugins follow the same interfaces as user plugins and receive no special treatment.

## Security Plugins

Security plugins make allow/block decisions on MCP messages. They can detect and act on sensitive content.

| Plugin | Handler | Description |
|--------|---------|-------------|
| [Basic PII Filter](basic_pii_filter.md) | `basic_pii_filter` | Regex-based detection of emails, phone numbers, credit cards, IPs, and national IDs |
| [Basic Secrets Filter](basic_secrets_filter.md) | `basic_secrets_filter` | Pattern-based detection of API keys, tokens, and high-entropy strings |
| [Basic Prompt Injection Defense](basic_prompt_injection_defense.md) | `basic_prompt_injection_defense` | Regex-based detection of obvious prompt injection patterns |

> **Warning:** The built-in security plugins provide basic protection only and are NOT suitable for production use. They can be bypassed with encoding or obfuscation. For production environments, implement enterprise-grade solutions.

## Middleware Plugins

Middleware plugins can transform requests/responses or complete requests themselves.

| Plugin | Handler | Description |
|--------|---------|-------------|
| [Tool Manager](tool_manager.md) | `tool_manager` | Control which tools are visible to MCP clients; filter, rename, and modify descriptions |
| [Call Trace](call_trace.md) | `call_trace` | Append diagnostic trace information to tool responses for debugging |

## Auditing Plugins

Auditing plugins observe MCP traffic and log it without affecting message flow.

| Plugin | Handler | Description |
|--------|---------|-------------|
| [JSON Lines](audit_jsonl.md) | `audit_jsonl` | Log MCP messages in JSON Lines format for log aggregation systems |
| [CSV](audit_csv.md) | `audit_csv` | Log MCP messages in CSV format for spreadsheet analysis |
| [Human Readable](audit_human_readable.md) | `audit_human_readable` | Log MCP messages in human-readable format for quick inspection |

## Common Configuration

All plugins support these framework-injected options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable or disable the plugin |
| `critical` | boolean | `true` | If true, plugin failure blocks the request (fail-closed) |
| `priority` | integer | `50` | Execution order (0-100, lower runs first) |

```yaml
plugins:
  - handler: audit_jsonl
    enabled: true
    critical: false    # Don't block requests if logging fails
    priority: 90       # Run after security plugins
    output_file: logs/audit.jsonl
```

## Writing Custom Plugins

See the [Plugin Development Guide](/docs/plugins/development-guide.html) for information on writing your own plugins.
