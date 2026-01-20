# Gatekit

[![Open Source](https://img.shields.io/badge/Open%20Source-Apache%202.0-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/gatekit-ai/gatekit/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Docs](https://img.shields.io/badge/docs-gatekit.ai-blue.svg)](https://gatekit.ai)

**A hackable MCP gateway.**

Gatekit is a Model Context Protocol gateway that controls traffic between your LLM and MCP tools for better visibility, security, and control.

It ships with plugins for tool management, content security, and audit logging.

Need custom behavior? **Extend with plugins, not forks.** Your customizations stay separate, so you can keep getting Gatekit updates without merge conflicts.

Built-in plugins handle:

- **Tool management** — expose only the tools you want, rename and modify descriptions for cleaner context and better discoverability
- **Content security** — catch PII and secrets before they leave your machine, defend against basic prompt injection attacks (regex-based)
- **Audit logging** — debug failures, track usage, inspect full request and response bodies

<img src="https://raw.githubusercontent.com/gatekit-ai/gatekit/main/docs/images/gatekit-config-editor.png" width="800" alt="Gatekit configuration editor">

*Gatekit configuration editor (Terminal UI)*

## Quick Start

### Installation

```bash
# With uv (recommended)
uv tool install gatekit

# With pipx
pipx install gatekit

# With pip (in a virtual environment)
pip install gatekit
```

Requires Python 3.10+.

### Usage

```bash
gatekit
```

## Guided Setup

The TUI includes a guided setup wizard that:

1. **Auto-detects** MCP clients on your system (Claude Desktop, Codex, Claude Code, Cursor, Windsurf)
2. **Discovers** all configured MCP servers from each client
3. **Generates** a complete Gatekit configuration
4. **Provides** client-specific setup instructions with copy buttons
5. **Creates** restore scripts in case you want to revert

<img src="https://raw.githubusercontent.com/gatekit-ai/gatekit/main/docs/images/guided-setup-wizard.png" width="800" alt="Guided setup wizard showing server discovery">

### Manual Configuration

For MCP clients not detected by Guided Setup, configure Gatekit as an MCP server with `command` and `args`:

```json
{
  "servers": {
    "gatekit": {
      "command": "gatekit-gateway",
      "args": ["--config", "/absolute/path/to/gatekit.yaml"]
    }
  }
}
```

Example for VS Code (`.vscode/mcp.json`):

```json
{
  "servers": {
    "gatekit": {
      "command": "gatekit-gateway",
      "args": ["--config", "${userHome}/.config/gatekit/gatekit.yaml"]
    }
  }
}
```

## How It Works

Gatekit proxies traffic between Model Context Protocol (MCP) clients and servers. **Config files** define which servers to proxy and which plugins to run.

```
┌─────────────┐              ┌───────────────────┐              ┌─────────────────┐
│ MCP Client  │              │  gatekit-gateway  │              │  MCP Server(s)  │
│ (Claude,    │─────────────▶│                   │─────────────▶│  (filesystem,   │
│  Cursor)    │◀─────────────│      plugins      │◀─────────────│   github, etc.) │
└─────────────┘              └───────────────────┘              └─────────────────┘
                                       ▲
                                       │ configures
                                       │
                             ┌─────────┴────────┐              ┌─────────────┐
                             │   gatekit.yaml   │    writes    │   gatekit   │
                             │                  │◀─────────────│   (TUI)     │
                             │  • mcp servers   │              └─────────────┘
                             │  • security      │
                             │  • auditing      │
                             │  • middleware    │
                             └──────────────────┘
```

- **`gatekit`** - The TUI. Detects your MCP clients, discovers servers, and generates YAML config files.
- **`gatekit.yaml`** - Your config. Defines upstream servers and plugins. 
- **`gatekit-gateway`** - The runtime. Your MCP client points here. Applies your plugins to all traffic.

**Plugins** intercept traffic between client and servers, allowing you to modify, block, or log messages:
- **Security** - Block or redact sensitive content (PII, secrets)
- **Middleware** - Transform requests/responses (filter tools, rename, modify)
- **Auditing** - Log all MCP traffic for debugging or compliance

## Built-in Plugins

### Middleware

- **Tool Manager** - Filter, rename, and customize tool descriptions
- **Call Trace** - Append diagnostic info to tool responses

<img src="https://raw.githubusercontent.com/gatekit-ai/gatekit/main/docs/images/tool-manager-modal.png" width="600" alt="Tool Manager configuration modal">

### Security

- **PII Filter** - Detect and redact personally identifiable information (regex-based)
- **Secrets Filter** - Detect API keys, tokens, and other secrets (regex-based)
- **Prompt Injection Filter** - Detect common prompt injection patterns (regex-based basic protection)

### Auditing

- **JSON Lines** - Structured logs for processing
- **CSV** - Spreadsheet-compatible logs
- **Human Readable** - Plain text logs for quick review

## Custom Plugins

When the built-in plugins aren't enough, write your own. Plugins intercept and modify tool calls and responses, enabling:

- Pruning responses to avoid context bloat
- Injecting credentials into tool calls without exposing them to the LLM
- Joining additional information from other data sources
- Human-in-the-loop approval for dangerous actions
- Response caching and deduplication

```python
from gatekit.plugins.interfaces import MiddlewarePlugin, PluginResult

class MyPlugin(MiddlewarePlugin):
    async def process_request(self, request, server_name):
        # Your logic here
        return PluginResult()

    async def process_response(self, request, response, server_name):
        # Your logic here
        return PluginResult()

HANDLERS = {"my_plugin": MyPlugin}
```

See the [plugin development guide](docs/plugin-development-guide.md) for details.

## Documentation

- [Full Documentation](https://gatekit.ai) - Guides, tutorials, and reference
- [Getting Started](docs/getting-started.md) - Installation, quick start, and tutorials
- [Configuration Specification](docs/configuration-specification.md)
- [Plugin Development Guide](docs/plugin-development-guide.md)
- [Security Model](docs/security-model.md)

## Roadmap and Limitations

Gatekit currently only supports local stdio servers and regex pattern matching based security and privacy filters.

Planned features include:

- **HTTP transport** - Connect to remote MCP servers
- **Hot-reload** - Change config without restarting the gateway
- **Enhanced detection** - Support for best-in-class third-party security and privacy solutions like Microsoft Presidio, Yelp Secrets, etc.
- **Token usage estimation** - Track token consumption by server and tool
- **Response pruning** - Built-in response trimming functionality to help reduce context bloat

## Feedback

Have feedback on the roadmap? [Join the discussion](https://github.com/gatekit-ai/gatekit/discussions). Found a bug? [Open an issue](https://github.com/gatekit-ai/gatekit/issues). For anything else: dbright@gatekit.ai

## License

Apache License 2.0 - see [LICENSE](LICENSE)

---

**Gatekit v0.1.0** - A hackable MCP gateway
