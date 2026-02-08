# Stdio Server Sandboxing

Stdio MCP servers run third-party code on your machine. Gatekit can sandbox them using OS-native isolation so they only access the files and network you allow.

When enabled, the server runs in a restricted environment where the home directory is denied by default and only explicitly allowed paths are accessible.

## Platform Support

| Platform | Engine | Install |
|----------|--------|---------|
| macOS | Seatbelt (`sandbox-exec`) | Built-in |
| Linux | bubblewrap (`bwrap`) | `apt install bubblewrap` / `dnf install bubblewrap` |
| Windows | Not supported | — |

## Configuration

```yaml
upstreams:
  - name: filesystem
    command: ["npx", "@modelcontextprotocol/server-filesystem", "~/docs"]
    sandbox:
      enabled: true
      paths: ["~/docs"]
      network: true  # default
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable OS-native sandboxing |
| `paths` | list of strings | (empty) | Directories with read-write access |
| `network` | boolean | `true` | Allow outbound network access |

## What's Accessible by Default

When sandbox is enabled, servers can access:

- **System paths** (read-only) — `/usr`, `/bin`, `/lib`, `/etc`, `/opt`, and platform-specific paths
- **`/tmp`** — fresh tmpfs on Linux, allowed on macOS
- **Package manager caches** — `~/.npm`, `~/.cache`, `~/.local` (if they exist)
- **Command runtime paths** — the server's own binary and script paths are auto-detected

Everything else in the home directory is denied unless listed in `paths`.

## Sensitive Paths

These directories are always hidden from sandboxed servers:

| Path | Contents |
|------|----------|
| `~/.ssh` | SSH keys and config |
| `~/.gnupg` | GPG keys |
| `~/.aws` | AWS credentials |
| `~/.azure` | Azure credentials |
| `~/.config/gcloud` | Google Cloud credentials |
| `~/.kube` | Kubernetes credentials |
| `~/.docker` | Docker registry credentials |
| `~/.git-credentials` | Git credential store |
| `~/.vault-token` | HashiCorp Vault token |
| `~/.terraform.d` | Terraform credentials |

> **macOS note:** Seatbelt has allow-wins semantics. If you allow a parent path that contains sensitive directories (e.g., `paths: ["~"]`), those directories become accessible. Use specific paths instead.

## Network Control

Network access is allowed by default because most MCP servers need external API access. To restrict a server to loopback-only:

```yaml
sandbox:
  enabled: true
  network: false
```

## Fail-Closed Behavior

If sandbox is enabled but no engine is available (e.g., bubblewrap not installed, or running on Windows), Gatekit **refuses to start the server** rather than running it unsandboxed. The error message includes platform-specific installation instructions.

## TUI Configuration

The TUI (`gatekit`) provides a per-server sandbox configuration modal. When a sandbox engine is available, new servers default to sandbox-enabled. The modal lets you toggle network access and manage the paths list.

## Limitations

- Only applies to stdio transport (HTTP servers are remote processes)
- Does not provide resource limits (CPU, memory)
- Glob patterns are not supported in paths — each path must be an exact directory
- On macOS, allowing a parent path exposes all children (Seatbelt limitation)
