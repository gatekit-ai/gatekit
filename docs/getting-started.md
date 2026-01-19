# Getting Started

Gatekit is a Model Context Protocol (MCP) gateway that sits between your LLM/MCP client and servers, allowing you to filter, audit, and secure communication.

## Installation

Requires Python 3.10+.

```bash
# With uv (recommended)
uv tool install gatekit

# With pipx
pipx install gatekit

# With pip (in a virtual environment)
pip install gatekit
```

## Quick Start

Launch the TUI to configure Gatekit:

```bash
gatekit
```

The guided setup wizard will:

1. **Auto-detect** MCP clients on your system (Claude Desktop, Codex, Claude Code, Cursor, Windsurf)
2. **Discover** all configured MCP servers from each client
3. **Generate** a complete Gatekit configuration
4. **Provide** client-specific setup instructions with copy buttons
5. **Create** restore scripts in case you want to revert

After completing setup and restarting your MCP client, Gatekit is active.

## Manual Configuration

For MCP clients not detected by Guided Setup, configure Gatekit as an MCP server in your client's configuration:

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


### Configuration Files

Gatekit stores its settings in a YAML configuration file. While the TUI is the recommended way to configure Gatekit, you can also edit the config file directly -- useful for version control, scripting, or AI-assisted configuration. See the [Configuration Reference](/docs/concepts/configuration.html) for the complete schema.


## See Gatekit in Action

Guided setup enables the **Call Trace** plugin, which appends diagnostic info to every tool response. Most MCP clients don't display raw tool responses directly, but you can ask your AI agent:

> "What does the Gatekit trace say for the last tool call?"

The agent will see something like:

```
---
🔍 **Gatekit Gateway Trace**
- Server: filesystem
- Tool: read_file
- Params: {"path": "/home/user/document.txt"}
- Response: 1.2 KB
- Duration: 23ms
- Request ID: 42
- Timestamp: 2025-01-15T10:30:45Z
---
```

This confirms Gatekit is intercepting traffic. The trace shows which server handled the request, timing info, and a request ID you can use to find this request in your audit logs.

## Using Tool Manager to Reduce Unnecessary Tool Calls

Let's use the **Tool Manager** plugin to optimize an MCP server. We'll hide an unnecessary tool and improve a tool description to help the AI use it more effectively.

After guided setup, you're on the config editor screen. We'll use [Context7](https://context7.com) as our example server—it provides up-to-date documentation for any programming library.

### Add Context7 (if needed)

If Context7 isn't already in your config:

1. Click the **+ Add** button in the MCP Servers panel header
2. Enter `context7` as the server name
3. Paste this command:
   ```
   npx -y @upstash/context7-mcp
   ```
4. Click **Connect**

Context7 should now appear in your server list with its tools loaded.

### Configure Tool Manager

1. **Select context7** in the MCP Servers panel

2. **Find Tool Manager** in the Middleware Plugins table and click **Configure**

3. **In the configuration dialog:**
   - **Uncheck** `resolve-library-id` — we'll hardcode the library ID instead
   - **Replace the `query-docs` description** with:
     ```
     Retrieves and queries up-to-date documentation and code examples. Use the library ID '/websites/devdocs_io_python_3_14' for Python documentation.
     ```

4. **Click OK** to close the configuration dialog

5. **Save** with `Ctrl+S`

6. **Restart your MCP client** to pick up the changes

### Verify It Works

After restarting, check that:
- The `resolve-library-id` tool no longer appears in your available tools
- The `query-docs` tool shows your new description

### Test It

Ask your AI agent:

> "Ask context7 what parameters does asyncio.gather accept and how does return_exceptions work? Then list all tool calls you made with the parameters you used."

The agent should answer your question and show that it called `query-docs` directly with the hardcoded library ID—no extra fluff in the description and not extra call to `resolve-library-id` needed. You've reduced token usage and made the workflow more efficient.

## Using Basic Secrets Filter to Protect Credentials

Gatekit's security plugins can detect and redact sensitive data flowing through MCP servers. Let's see this in action with a simple demo.

### A Note on This Demo

This example is easy to observe but also easy to bypass. An AI agent with shell access could read the same environment variable using `echo $GITHUB_TOKEN` instead of the MCP server. Gatekit only inspects traffic flowing through MCP.

In practice, Gatekit's security filtering provides the most value when protecting data the agent *can't* access any other way:

- **Database queries** returning customer records, API keys stored in config tables, or PII from user tables
- **Business app integrations** like Salesforce, HubSpot, or healthcare systems where MCP servers have authenticated access your AI agent couldn't otherwise reach
- **Exfiltration prevention** when MCP servers (Slack, GitHub, email) have credentials that aren't available to the shell—blocking secrets in outgoing requests before they leave your system

Gatekit is one layer in a defense-in-depth strategy, not a complete security solution on its own.

### Demo: Watch a Token Get Redacted

We'll use the [Everything server](https://www.npmjs.com/package/@modelcontextprotocol/server-everything)—a demo MCP server that includes a `get-env` tool which returns environment variables.

**Add the Everything Server:**

1. Click **+ Add** in the MCP Servers panel header
2. Enter `everything` as the server name
3. Paste this command:
   ```
   npx -y @modelcontextprotocol/server-everything
   ```
4. Click **Connect**

**Set up a test token** (preserving any existing one):

```bash
# Save existing token if you have one
export SAVED_GITHUB_TOKEN="$GITHUB_TOKEN"

# Set a fake token for testing
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Restart the TUI (`gatekit`) so it picks up the new environment variable.

**Enable Basic Secrets Filter:**

1. **Click on Global Settings** in the MCP Servers panel
2. **Find Basic Secrets Filter** in the Security Plugins table and click **Configure**
3. **Ensure GitHub tokens are enabled** (they are by default)
4. **Set action to "redact"** — this replaces secrets with `[REDACTED]` rather than blocking the entire response
5. **Click OK** and **Save** with `Ctrl+S`
6. **Restart your MCP client**

**Test it** by asking your AI agent:

> "Use the everything server's get-env tool to show me my environment variables. What's my GITHUB_TOKEN set to?"

The agent will report that `GITHUB_TOKEN` is `[REDACTED]`. Gatekit detected the `ghp_` prefix pattern and redacted it before the response reached your AI agent.

**Clean up** by restoring your original token:

```bash
export GITHUB_TOKEN="$SAVED_GITHUB_TOKEN"
unset SAVED_GITHUB_TOKEN
```

## Next Steps

- [Configuration Reference](/docs/concepts/configuration.html) - Complete YAML schema documentation
- [Managing Tools](/docs/guides/managing-tools.html) - Advanced tool filtering, renaming, and descriptions
- [Security Plugins](/docs/concepts/security.html) - Block PII, secrets, and prompt injection
- [Plugin Development](/docs/plugins/development-guide.html) - Write your own plugins
