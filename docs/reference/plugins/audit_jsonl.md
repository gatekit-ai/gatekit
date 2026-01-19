# JSON Lines Auditing

Log MCP requests, responses, and notifications in JSON Lines format for structured logging and integration with log aggregation systems (ELK, Splunk, etc.).

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `audit_jsonl` |
| Type | Auditing |
| Scope | Global (can be configured globally or per-server) |

## How It Works

The JSON Lines auditing plugin:
1. Logs each MCP request, response, and notification as a single JSON object per line
2. Includes full pipeline processing metadata (which plugins ran, decisions made)
3. Optionally includes message bodies (request params, response results)
4. Supports body size limits to control log volume

## Log Entry Fields

Each log entry includes:

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `event_type` | REQUEST, RESPONSE, NOTIFICATION, or error types |
| `request_id` | MCP request ID for correlation |
| `server_name` | Which upstream server handled the request |
| `method` | MCP method (e.g., `tools/call`, `resources/read`) |
| `pipeline_outcome` | Final pipeline result (allowed, blocked, modified, etc.) |
| `security_evaluated` | Whether security plugins made a decision |
| `modified` | Whether any plugin modified the content |
| `pipeline` | Detailed plugin processing information |
| `reason` | Combined reasons from all plugins |

Additional fields for responses:
- `duration_ms` - Request processing time
- `response_status` - success or error
- `error_code` / `error_message` - For error responses

## Configuration Reference

### output_file

Path to the JSON Lines log file. Supports `~` for home directory.

**Type:** string
**Default:** `logs/gatekit_audit.jsonl`
**Required:** Yes

> **Note:** Relative paths are resolved relative to the config file's directory.

### include_request_body

Include full request parameters in logs.

**Type:** boolean
**Default:** `false`

### include_response_body

Include full response result/error in logs.

**Type:** boolean
**Default:** `false`

### include_notification_body

Include full notification parameters in logs.

**Type:** boolean
**Default:** `false`

### max_body_size

Maximum size in bytes for logged message bodies. Bodies larger than this are truncated.

**Type:** integer
**Default:** `10240` (10 KB)
**Range:** 0 (unlimited) or 50-1048576 (50 bytes to 1 MB)

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: audit_jsonl
    enabled: true
    output_file: logs/audit.jsonl
```

### Full Configuration

```yaml
plugins:
  - handler: audit_jsonl
    enabled: true
    critical: false           # Don't block requests if logging fails
    output_file: logs/audit.jsonl

    include_request_body: false
    include_response_body: false
    include_notification_body: false
    max_body_size: 10240      # 10 KB limit
```

### Debug Configuration (Full Bodies)

```yaml
plugins:
  - handler: audit_jsonl
    enabled: true
    output_file: logs/debug_audit.jsonl

    include_request_body: true
    include_response_body: true
    include_notification_body: true
    max_body_size: 102400     # 100 KB limit for debugging
```

### Production Configuration (Minimal Logging)

```yaml
plugins:
  - handler: audit_jsonl
    enabled: true
    critical: false
    output_file: /var/log/gatekit/audit.jsonl

    include_request_body: false
    include_response_body: false
    include_notification_body: false
    max_body_size: 1024       # 1 KB limit
```

## Example Log Entry

```json
{"timestamp":"2025-01-12T15:30:45.123Z","event_type":"RESPONSE","request_id":42,"server_name":"filesystem","method":"tools/call","tool":"read_file","pipeline_outcome":"allowed","security_evaluated":true,"modified":false,"response_status":"success","duration_ms":45,"pipeline":{"stages":[{"plugin":"basic_pii_filter","outcome":"ALLOWED","reason":"No PII detected"}]},"reason":"No PII detected"}
```

## Event Types

| Type | Description |
|------|-------------|
| `REQUEST` | Incoming MCP request |
| `RESPONSE` | Successful response |
| `NOTIFICATION` | MCP notification |
| `SECURITY_BLOCK` | Request blocked by security plugin |
| `UPSTREAM_ERROR` | Error from upstream server (-32000 to -32099) |
| `PARSE_ERROR` | JSON-RPC parse error (-32700) |
| `INVALID_REQUEST_ERROR` | Invalid request structure (-32600) |
| `METHOD_NOT_FOUND_ERROR` | Method not found (-32601) |
| `INVALID_PARAMS_ERROR` | Invalid parameters (-32602) |
| `INTERNAL_ERROR` | Internal JSON-RPC error (-32603) |
| `APPLICATION_ERROR` | Other application errors |

## Security Note

When security plugins redact content (PII, secrets, etc.), the audit log receives the **redacted** version, not the original. This ensures sensitive data is not written to log files.
