# Changelog

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
