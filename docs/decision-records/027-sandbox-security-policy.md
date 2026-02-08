# ADR-027: Sandbox Security Policy

## Context

ADR-026 established OS-native sandboxing as the mechanism for isolating MCP server processes. This ADR documents the security policy decisions: what the sandbox allows and denies by default, how it handles failure, and how user-configured paths are applied.

These decisions balance security (restrict as much as possible) against usability (sensible defaults that work for most servers with minimal configuration).

## Decision

### Fail-closed behavior

If a server has `sandbox: {enabled: true}` but no sandbox engine is available (e.g., Linux without bubblewrap installed, or Windows), Gatekit **refuses to start the server** rather than running it unsandboxed. This prevents a configuration that promises isolation from silently degrading to no isolation.

The error message includes platform-specific installation instructions (e.g., `apt install bubblewrap` on Debian/Ubuntu).

**Why not fail-open?** A user who enables sandboxing has made a deliberate security decision. Silently ignoring it undermines trust and creates a false sense of security. The cost of a clear error is far lower than the cost of running an untrusted server without the isolation the user expects.

### Filesystem policy: deny-all default with allowlist

The baseline is **deny all filesystem access**, then explicitly allow what the server needs:

**System paths (implicitly readable):**
- `/usr`, `/bin`, `/sbin`, `/lib`, `/etc`, `/opt` — binaries, libraries, certificates
- Platform-specific: `/Library`, `/System`, `/Applications` on macOS; `/proc`, `/nix` on Linux

**Read-write (allowed by default):**
- `/tmp` (fresh tmpfs on bubblewrap, allowed on Seatbelt)
- `~/.npm/`, `~/.cache/`, `~/.local/` — package manager caches needed by npx, pip, etc.
- User-configured `paths` from the sandbox config

**Always denied (sensitive credential directories):**
- `~/.ssh` — SSH keys and configuration
- `~/.gnupg` — GPG keys
- `~/.aws` — AWS credentials
- `~/.azure` — Azure authentication tokens
- `~/.config/gcloud` — Google Cloud credentials
- `~/.kube` — Kubernetes credentials and tokens
- `~/.docker` — Docker registry credentials
- `~/.git-credentials` — Git credential store
- `~/.vault-token` — HashiCorp Vault tokens
- `~/.terraform.d` — Terraform credentials

Implementation differs by engine:
- **bubblewrap**: Selectively mounts only needed paths. Sensitive paths overlaid with `--tmpfs`. Everything else is simply not mounted (invisible to the process).
- **Seatbelt**: Denies all reads in the home directory `(deny file-read* (subpath "~"))`, then selectively allows specific subdirectories. Sensitive paths are protected by not being allowed. Note: Seatbelt has allow-wins semantics, so if a user allows a parent path (e.g., `paths: ["~"]`), sensitive subdirectories become accessible — a warning is logged in this case.

Both approaches require symlink-aware path resolution to prevent traversal bypasses.

**Why deny-all rather than deny-writes-only?** A denylist approach (read everything, deny 10 known paths) is fundamentally weak: an MCP server with read access to the full filesystem plus network access can exfiltrate any sensitive file not on the deny list (.env files, database configs, API keys, etc.). Industry consensus (Docker, Flatpak, Deno, macOS App Sandbox) is deny-all with explicit allowlists.

### Network: allowed by default

Most MCP servers need external API access (e.g., Context7 calls external APIs, web search servers fetch URLs). Denying network by default would break the majority of servers and require users to understand which servers need network access.

When explicitly denied (`network: false`):
- bubblewrap: `--unshare-net` creates a new network namespace with loopback only
- Seatbelt: `(deny network-outbound)` blocks outgoing connections; Unix domain sockets are allowed (needed for some system IPC)

**Why not deny by default?** Unlike filesystem writes (where the damage from an accidental write is immediate and local), network access is fundamental to most MCP server functionality. Denying it by default would make the sandbox unusable without per-server configuration, defeating the "just works" goal.

### Explicit paths only (no workspace inference)

Workspace paths must be explicitly configured via the `paths` field. There is no automatic inference from command arguments.

**Why explicit-only rather than heuristic inference?** Workspace inference from command arguments was considered but rejected:
1. **Security risk**: Implicit magic that grants write access based on heuristics is counter to the security principle of explicit-over-implicit
2. **Unpredictable**: Not all directory arguments are workspaces (some are read-only reference paths)
3. **Industry convention**: Docker, Flatpak, Deno, and macOS App Sandbox all require explicit path configuration
4. **Clarity**: Users should know exactly what their sandbox allows — no hidden behavior

### Sandbox is opt-in

Sandboxing defaults to disabled (`enabled: false`) in YAML configuration. Users must explicitly enable it per server. The TUI defaults new servers to sandbox-enabled when a backend is available, since the TUI is an interactive setup where the secure default is appropriate.

**Why not opt-out (enabled by default)?** Sandboxing can break servers that write to unexpected locations. An opt-in approach lets users enable it deliberately and debug any issues, rather than discovering their server is broken and having to figure out why. As the feature matures and we gain confidence in the defaults, we may revisit this.

## Consequences

### Positive
- Fail-closed ensures sandbox promises are kept — no silent degradation
- Home-directory-denied default provides strong isolation — servers can only access what they're explicitly given
- Explicit paths configuration is clear and predictable — no hidden inference
- Network-allowed-by-default means API-dependent servers work out of the box

### Negative
- Servers that need filesystem access must have `paths` explicitly configured
- Network-allowed-by-default means a compromised server can exfiltrate data unless the user explicitly sets `network: false`
- Opt-in means users must know about and enable the feature
- On macOS, Seatbelt's allow-wins semantics prevent carving out exceptions within allowed parent paths

### Future considerations
- Default-on sandboxing once the feature is proven stable
- Granular network control (allow specific hosts/ports) if bubblewrap adds support or we add a Landlock fallback
- Resource limits (CPU/memory) via cgroups — requires a separate mechanism

## Status

Accepted
