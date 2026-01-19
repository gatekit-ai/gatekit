# CSV Auditing

Log MCP requests, responses, and notifications in CSV format for spreadsheet analysis and simple log review.

## Quick Reference

| Property | Value |
|----------|-------|
| Handler | `audit_csv` |
| Type | Auditing |
| Scope | Global (can be configured globally or per-server) |

## How It Works

The CSV auditing plugin:
1. Creates a CSV file with headers on first write
2. Logs each MCP event as a row with key metadata
3. Supports configurable delimiters and quote styles
4. Protects against CSV injection attacks

## CSV Columns

| Column | Description |
|--------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `event_type` | REQUEST, RESPONSE, NOTIFICATION, error types |
| `request_id` | MCP request ID |
| `server_name` | Upstream server name |
| `method` | MCP method called |
| `tool` | Tool name (for tools/call) |
| `pipeline_outcome` | allowed, blocked, modified, etc. |
| `security_evaluated` | true/false |
| `modified` | true/false |
| `reason` | Combined plugin reasons |
| `duration_ms` | Processing time (responses only) |
| `response_status` | success/error (responses only) |
| `error_code` | JSON-RPC error code (errors only) |
| `error_message` | Error message (errors only) |
| `error_classification` | Error category (errors only) |

## Configuration Reference

### output_file

Path to the CSV log file. Supports `~` for home directory.

**Type:** string
**Default:** `logs/gatekit_audit.csv`
**Required:** Yes

### csv_config

Optional CSV format configuration.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `delimiter` | string | `,` | Field delimiter: `,`, `\t` (tab), `;`, or `\|` |
| `quote_char` | string | `"` | Character to quote fields |
| `quote_style` | string | `minimal` | When to quote: `minimal`, `all`, `nonnumeric`, `none` |
| `escape_char` | string | `\` | Escape character (used with `quote_style: none`) |
| `null_value` | string | `""` | Value to use for null/empty fields |

## YAML Configuration

### Minimal Configuration

```yaml
plugins:
  - handler: audit_csv
    enabled: true
    output_file: logs/audit.csv
```

### Full Configuration

```yaml
plugins:
  - handler: audit_csv
    enabled: true
    critical: false           # Don't block requests if logging fails
    output_file: logs/audit.csv

    csv_config:
      delimiter: ","          # Standard comma delimiter
      quote_char: '"'         # Standard double-quote
      quote_style: minimal    # Only quote when needed
      escape_char: '\'        # Backslash escaping
      null_value: ""          # Empty string for nulls
```

### Tab-Separated Values (TSV)

```yaml
plugins:
  - handler: audit_csv
    enabled: true
    output_file: logs/audit.tsv

    csv_config:
      delimiter: "\t"         # Tab delimiter for TSV
      quote_style: nonnumeric # Quote strings, not numbers
```

### European Style (Semicolon)

```yaml
plugins:
  - handler: audit_csv
    enabled: true
    output_file: logs/audit.csv

    csv_config:
      delimiter: ";"          # Semicolon for locales using comma as decimal
      null_value: "NULL"      # Explicit null marker
```

## Example Output

```csv
timestamp,event_type,request_id,server_name,method,tool,pipeline_outcome,security_evaluated,modified,reason,duration_ms,response_status,error_code,error_message,error_classification
2025-01-12T15:30:45.123Z,RESPONSE,42,filesystem,tools/call,read_file,allowed,true,false,No PII detected,45,success,,,
2025-01-12T15:30:46.456Z,SECURITY_BLOCK,43,filesystem,tools/call,write_file,blocked,true,false,"Secret detected: 1 secret(s) found",0,,,,
```

## Use Cases

### Quick Analysis
Open in Excel, Google Sheets, or Numbers for sorting and filtering.

### Log Rotation
Use standard log rotation tools (logrotate) on the output file.

### Simple Monitoring
Use `tail -f logs/audit.csv` for real-time monitoring.

## Security Features

### CSV Injection Protection
Values starting with `=`, `+`, `-`, `@`, or tab are prefixed with a single quote to prevent formula execution when opened in spreadsheets.

### Newline Escaping
Newlines in values are escaped as `\n` to ensure each CSV record stays on one line, which is critical for line-based log analysis tools.

## Limitations

- **No message bodies** - CSV format doesn't include request/response bodies. Use JSON Lines for full body logging.
- **Flat structure** - Complex pipeline data is flattened; use JSON Lines for full pipeline details.
- **Excel cell limit** - Values longer than 32,000 characters are truncated (Excel limit: 32,767).
