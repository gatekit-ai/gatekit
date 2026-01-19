# Gatekit Configuration Specification

**Version**: 0.1.0  
**Status**: Authoritative Reference  

> **Note**: This document describes the ACTUAL configuration format as implemented. The Pydantic schemas in [`gatekit/config/models.py`](../gatekit/config/models.py) define the validation rules and accepted fields.

> **Tip**: You don't need to edit configuration files by hand. Run `gatekit` to launch the guided setup and configuration editor.

## Quick Reference

```yaml
# Minimal valid configuration
proxy:
  transport: stdio
  upstreams:
    - name: example
      command: ["npx", "@modelcontextprotocol/server-filesystem", "/tmp"]

# Full configuration with all sections
proxy:
  transport: stdio
  upstreams:
    - name: example
      transport: stdio  # Optional: inherits from proxy.transport
      command: ["npx", "@modelcontextprotocol/server-filesystem", "/tmp"]
      restart_on_failure: true
      max_restart_attempts: 3
      server_identity: "optional-mcp-server-name"

  timeouts:
    connection_timeout: 60
    request_timeout: 60

plugins:
  security:
    _global:
      - handler: "basic_pii_filter"
        config:
          enabled: true
          action: "redact"
  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "logs/gatekit_audit.jsonl"
  middleware:
    example:
      - handler: "tool_manager"
        config:
          enabled: true
          tools:
            - tool: "read_file"

logging:
  level: "INFO"
  handlers: ["stderr"]
  file_path: "logs/gatekit.log"
  max_file_size_mb: 10
  backup_count: 5
```

## Top-Level Structure

### Required: `proxy` Section

All Gatekit configurations must have a top-level `proxy` section:

```yaml
proxy:
  transport: "stdio"  # Required: "stdio" or "http"
  upstreams: [...]    # Required: List of upstream servers
  # ... other optional sections
```

**Common Mistake**: Don't put `upstreams:` at the top level. It must be inside `proxy:`.

❌ **Wrong:**
```yaml
upstreams:
  - name: example
```

✅ **Correct:**
```yaml
proxy:
  upstreams:
    - name: example
```

## Proxy Section Fields

### `transport` (Required)

**Type**: `string`
**Values**: `"stdio"` or `"http"`
**Purpose**: Defines how Gatekit communicates with MCP clients

```yaml
proxy:
  transport: "stdio"  # For Claude Desktop and most MCP clients
```

### `upstreams` (Required)

**Type**: `list` of upstream configurations
**Minimum**: At least one upstream required
**Purpose**: Defines the MCP servers that Gatekit proxies to

```yaml
proxy:
  upstreams:
    - name: "filesystem"
      command: ["npx", "@modelcontextprotocol/server-filesystem", "/tmp"]
    - name: "github"
      command: ["npx", "@modelcontextprotocol/server-github"]
```

#### Upstream Configuration Fields

Each upstream server has these fields:

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | ✅ Yes | - | Unique server identifier |
| `transport` | string | No | `"stdio"` | `"stdio"` or `"http"` |
| `command` | list of strings | Conditional | - | Required for stdio transport |
| `url` | string | Conditional | - | Required for http transport |
| `restart_on_failure` | boolean | No | `true` | Auto-restart on failure |
| `max_restart_attempts` | integer | No | `3` | Max restart attempts |
| `server_identity` | string | No | `null` | MCP-reported server name |

**Command Format:**

```yaml
command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

**HTTP Transport Example:**

```yaml
upstreams:
  - name: "remote-server"
    transport: "http"
    url: "https://example.com/mcp"
```

#### Important: Environment Variables

**Gatekit upstream configurations do NOT support `env` fields.**

❌ **Not Supported:**
```yaml
upstreams:
  - name: github
    command: ["npx", "@modelcontextprotocol/server-github"]
    env:  # ❌ This field does not exist!
      GITHUB_TOKEN: "ghp_xxx"
```

**Rationale**: Environment variables are an MCP client concern, not a gateway concern. Set them in your MCP client configuration (e.g., Claude Desktop's `claude_desktop_config.json`) or in your shell environment before launching Gatekit.

### `timeouts` (Optional)

**Type**: object
**Purpose**: Configure connection and request timeouts

```yaml
proxy:
  timeouts:
    connection_timeout: 60  # seconds
    request_timeout: 60     # seconds
```

**Defaults**: Both default to 60 seconds

### `http` (Conditional)

**Type**: object
**Required**: Only when `transport: "http"`
**Purpose**: Configure HTTP server settings

```yaml
proxy:
  transport: "http"
  http:
    host: "127.0.0.1"
    port: 8080
```

### `plugins` (Optional)

**Section**: Top-level `plugins` (optional, sibling to `proxy`)
**Purpose**: Configure security, auditing, and middleware plugins

```yaml
plugins:
  security: {...}
  auditing: {...}
  middleware: {...}
```

**Note**: `plugins` is a root-level section, NOT nested under `proxy`. See [Plugin Configuration](#plugin-configuration) section below.

## Plugin Configuration

Plugins use an **upstream-scoped dictionary format** with special `_global` key:

```yaml
plugins:
  security:
    _global:              # Applies to all upstreams
      - handler: "basic_pii_filter"
        config:
          enabled: true
          action: "redact"
    filesystem:           # Applies only to 'filesystem' upstream
      - handler: "basic_pii_filter"
        config:
          enabled: true
          action: "block"  # Overrides global setting
```

### Plugin Categories

1. **`security`**: Plugins that block/allow/modify content (PII filter, secrets filter, tool allowlist)
2. **`auditing`**: Plugins that observe and log events (JSON, CSV, human-readable)
3. **`middleware`**: Plugins that transform or complete requests (tool manager)

### Plugin Configuration Structure

Each plugin entry has:

```yaml
- handler: "plugin_name"  # Required: Handler name
  config:                 # Optional: Plugin-specific configuration
    enabled: true         # Optional: Default true
    priority: 50          # Optional: 0-100, lower = higher priority
    # ... plugin-specific fields
```

### Special Keys

- **`_global`**: Applies to all upstream servers
- **Upstream names**: Must match names in `proxy.upstreams`
- **`_*` keys**: Other underscore-prefixed keys are ignored (useful for YAML anchors)

### Plugin Resolution Algorithm

For each upstream server:
1. Start with plugins from `_global` section
2. Add/override with plugins from server-specific section
3. Merge by handler name (same handler = override, different handler = add)
4. Sort by priority (lower number = higher priority)

**Example:**

```yaml
plugins:
  security:
    _global:
      - handler: "basic_pii_filter"
        config: {action: "redact"}
      - handler: "basic_secrets_filter"
        config: {action: "redact"}
    production:
      - handler: "basic_pii_filter"
        config: {action: "block"}  # Override global
      - handler: "tool_manager"    # Add new plugin
        config: {tools: ["read_file"]}

# Result for 'production' upstream:
# 1. basic_pii_filter with action: "block" (overridden)
# 2. basic_secrets_filter with action: "redact" (from global)
# 3. tool_manager with specified tools (added)
```

### Plugin Scope Validation

Plugins declare their scope via class attributes:

- **`global` scope**: Can be configured in `_global` or server sections
- **`server_aware` scope**: CANNOT be in `_global`, requires per-server config
- **`server_specific` scope**: CANNOT be in `_global`, only works with compatible servers

❌ **Invalid Configuration:**
```yaml
security:
  _global:
    - handler: "tool_manager"  # ❌ Server-aware plugin in global section
```

✅ **Valid Configuration:**
```yaml
security:
  filesystem:
    - handler: "tool_manager"  # ✅ Server-aware plugin in server section
      config:
        tools: ["read_file", "write_file"]
```

## Logging Configuration

**Section**: Top-level `logging` (optional)
**Purpose**: Configure Gatekit system logs (not audit logs)

```yaml
logging:
  level: "INFO"                    # DEBUG, INFO, WARNING, ERROR, CRITICAL
  handlers: ["stderr", "file"]     # stderr, file, or both
  file_path: "logs/gatekit.log"  # Required if handlers includes "file"
  max_file_size_mb: 10            # File rotation size
  backup_count: 5                 # Number of backup files
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  date_format: "%Y-%m-%d %H:%M:%S"
```

### Log Handlers

- **`stderr`**: Output to console (not supported on Windsurf/Windows - see [known issues](known-issues.md))
- **`file`**: Output to file (requires `file_path`) - **default for guided setup**
- Can specify both: `["stderr", "file"]`

### Path Resolution

- Relative paths are resolved relative to the config file directory
- Absolute paths are used as-is
- Home directory expansion (`~`) is supported

## Validation Rules

### Server Names

- Must be unique across all upstreams
- Cannot contain `__` (reserved as namespace delimiter)
- Must match pattern: `^[a-z][a-z0-9_-]*$`

### Plugin References

- Plugin upstream keys must match upstream server names
- `_global` is a special reserved key
- Unknown upstream names in plugin config will cause validation error

### Required Fields

Validation enforces:
- `proxy.transport` is required
- `proxy.upstreams` must have at least one entry
- Each upstream must have a `name`
- stdio transport requires `command`
- http transport requires `url`
- http transport requires `proxy.http` section

## Complete Working Example

The following example shows a complete working configuration with inline comments.

```yaml
# Complete example configuration
proxy:
  transport: stdio

  upstreams:
    - name: "filesystem"
      command: ["npx", "@modelcontextprotocol/server-filesystem", "/Users/user/Documents"]
      restart_on_failure: true
      max_restart_attempts: 3
      server_identity: "secure-filesystem-server"

  timeouts:
    connection_timeout: 60
    request_timeout: 60

plugins:
  security:
    _global:
      - handler: "basic_pii_filter"
        config:
          enabled: true
          action: "redact"
          pii_types:
            email: {enabled: true}
            phone: {enabled: true}
            national_id: {enabled: true}

      - handler: "basic_secrets_filter"
        config:
          enabled: true
          action: "block"
          secret_types:
            aws_access_keys: {enabled: true}
            github_tokens: {enabled: true}

  middleware:
    filesystem:
      - handler: "tool_manager"
        config:
          enabled: true
          priority: 25
          tools:
            - tool: "read_file"
            - tool: "write_file"
            - tool: "list_directory"

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "logs/gatekit_audit.jsonl"
          include_request_body: true
          include_response_body: false
          include_notification_body: false
          max_body_size: 10000
          # critical: true is the default - uncomment below for development
          # critical: false

logging:
  level: "INFO"
  handlers: ["stderr", "file"]
  file_path: "logs/gatekit.log"
  max_file_size_mb: 10
  backup_count: 5
```

## Common Mistakes

### 1. Missing `proxy` wrapper
❌ **Wrong:**
```yaml
transport: stdio
upstreams: [...]
```

✅ **Correct:**
```yaml
proxy:
  transport: stdio
  upstreams: [...]
```

### 2. Adding `env` to upstream config
❌ **Wrong:**
```yaml
upstreams:
  - name: github
    command: ["npx", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "xxx"
```

✅ **Correct:**
Set environment variables in your shell or MCP client config, not in Gatekit config.

### 3. Server-aware plugins in `_global`
❌ **Wrong:**
```yaml
plugins:
  middleware:
    _global:
      - handler: "tool_manager"  # Needs per-server config
```

✅ **Correct:**
```yaml
plugins:
  middleware:
    filesystem:
      - handler: "tool_manager"
        config:
          tools: ["read_file"]
```

### 4. Plugin handler vs policy naming
❌ **Wrong (outdated):**
```yaml
- policy: "tool_allowlist"
```

✅ **Correct (current):**
```yaml
- handler: "tool_manager"
```

## Related Documentation

- **Implementation**: [`gatekit/config/models.py`](../gatekit/config/models.py) - Pydantic schemas (source of truth)
- **Loader**: [`gatekit/config/loader.py`](../gatekit/config/loader.py) - Configuration loading logic
- **Test Examples**: [`tests/validation/`](../tests/validation/) - Test configurations
- **Architecture**: [`docs/decision-records/005-configuration-management.md`](decision-records/005-configuration-management.md) - Design decisions
- **Plugin Structure**: [`docs/decision-records/007-plugin-configuration-structure.md`](decision-records/007-plugin-configuration-structure.md) - Plugin config evolution

## Version History

- **0.1.0**: Current specification
- **0.1.0**: Initial release with handler-based plugin system

---

**When in doubt**: Refer to the Pydantic schemas in `gatekit/config/models.py`. The schemas define the validation rules and are the authoritative source of truth for what fields are accepted and how they are validated.
