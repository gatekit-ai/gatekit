# Changelog

## [Unreleased]

## [0.2.0] - TBD

### Breaking Changes

- **Plugin API**: `get_json_schema()` renamed to `get_config_schema()`
  - A deprecated shim is provided for backward compatibility
  - Shim will be removed in v0.3.0
  - Update your plugins: rename `get_json_schema` → `get_config_schema`

### Features

- **Token Usage Estimator plugin**: New auditing plugin that tracks token usage per server
  - Estimates tokens using tiktoken (cl100k_base encoding)
  - Tracks input and output tokens separately, per tool
  - Per-server reset via context menu in TUI
  - CSV log for historical analysis (load into Excel, pivot by server/tool)
  - Multi-instance support for multiple gateway configurations
  - Persists across gateway restarts
- **Server enable/disable**: Toggle upstream servers on/off without removing their configuration
  - Checkbox UI in the TUI server list
  - Disabled servers are filtered out at proxy initialization
  - Server title bar shows enabled/total count
- **Streamable HTTP transport**: Connect to remote MCP servers over HTTP/SSE
  - TLS support with configurable certificate verification
  - Session management for persistent connections
  - Auto-detection of HTTP URLs in server configuration
- **Plugin output schemas**: Plugins can declare output display capabilities via `get_output_schema()` classmethod
- **Dynamic server list columns**: TUI server list displays columns from plugins that declare `server_column` in their output schema
- **FileAuditingPlugin base class**: Shared base for file-based auditing plugins with path validation improvements

### Improvements

- Improved TLS error handling and connection status updates
- Better context menu dismissal and tooltip management in TUI
- Refactored plugin configuration validation
- Enhanced server input handling and URL detection logic
- Graceful shutdown ensures child processes are terminated properly

## [0.1.0] - 2026-01-20

Initial public release.

### Features

- Terminal UI with guided setup wizard
- Auto-detection of MCP clients (Claude Desktop, Cursor, Windsurf, Codex, Claude Code)
- Built-in plugins:
  - **Security**: PII filter, Secrets filter, Prompt injection defense (all regex-based)
  - **Middleware**: Tool manager, Call trace
  - **Auditing**: JSON Lines, CSV, Human readable
- Custom Python plugin support
- Cross-platform (macOS, Linux, Windows)

### Known Limitations

- Local stdio transport only (no HTTP/SSE MCP server support)
- Security plugins use regex patterns, not production-grade ML/NLP
- See docs/known-issues.md for platform-specific notes
