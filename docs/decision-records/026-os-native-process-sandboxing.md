# ADR-026: OS-Native Process Sandboxing Architecture

## Context

MCP servers run as local processes with full user privileges — installing one is equivalent to running arbitrary code. The MCP spec recommends running servers in sandboxed environments but doesn't mandate any mechanism. Real-world MCP security incidents in 2025 (10+ CVEs including RCEs and sandbox escapes) make process isolation a pressing concern.

Gatekit is uniquely positioned to add sandboxing: as the gateway that spawns MCP server processes, it can transparently wrap commands with OS-native sandboxing before process creation.

### Requirements

1. Simple per-server toggle that "just works" with sensible defaults
2. Advanced users can customize filesystem and network policy via YAML
3. No Docker dependency — must work on a bare development machine
4. Fail-closed: if sandbox is enabled but unavailable, refuse to start the server
5. Must not break process lifecycle management (killpg, graceful shutdown)

## Decision

### OS-native sandboxing, not containers

We chose OS-native sandboxing mechanisms over Docker/Podman because:
- **Zero infrastructure**: No daemon, no images, no registry — just the OS
- **Transparent stdio**: Sandboxed process communicates via stdin/stdout exactly as before
- **Process group preservation**: `sandbox-exec` and `bwrap` exec the target command, preserving process group semantics for `killpg()`
- **Minimal overhead**: No container startup time or resource allocation

### Engine selection

**macOS: Seatbelt (`sandbox-exec`)**
- Only practical option on macOS
- Technically deprecated since ~2016 but still functional and used by Apple's own services, Claude Code, OpenAI Codex, Chromium, Firefox, and Nix
- Generates `.sb` profile files consumed by `sandbox-exec -f`

**Linux: bubblewrap (`bwrap`)**
- Uses unprivileged user namespaces — no root needed, no SUID binary
- A vulnerability in bwrap itself cannot escalate to root (unlike Firejail's SUID approach)
- Battle-tested: used by Flatpak, Claude Code
- Tradeoff: cannot do cgroups, granular network control, or overlayfs — none critical for MCP sandboxing

**Alternatives evaluated and rejected:**
- **Firejail**: SUID root — multiple privilege escalation CVEs (2021, 2022)
- **nsjail**: Usually requires root, not packaged in distros
- **systemd-run**: Child managed by systemd (complicates lifecycle), many options need root
- **Landlock/landrun**: Promising future fallback (kernel-native, zero deps) but less mature
- **Podman/Docker**: Full container runtime — too heavyweight for sandboxing a single child

### Core infrastructure, not a plugin

Sandboxing operates at the process level, before any MCP messages flow. It wraps the command passed to `asyncio.create_subprocess_exec()`. This is fundamentally different from plugins which operate on messages. Making it a plugin would require the plugin to have control over process creation, which violates the transport abstraction.

### Stdio transport only

HTTP transport servers are remote — Gatekit doesn't control their process. Sandboxing only makes sense for locally-spawned stdio processes.

### Default security policy

- **Deny-all default with allowlist**: The server process has no filesystem access except explicitly allowed paths. System paths are readable (binaries, libraries, runtimes), `/tmp` and cache directories are writable, and user-configured `paths` get read-write access.
- **Hide sensitive paths**: `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.azure`, `~/.config/gcloud`, `~/.kube`, `~/.docker`, `~/.git-credentials`, `~/.vault-token`, `~/.terraform.d` — protected by not being in the allowlist (home directory is denied by default)
- **Allow network by default**: Most MCP servers need API access (e.g., Context7, web search)
- **Explicit paths only**: No workspace inference from command arguments — users must configure `paths` for directories the server needs to access

## Consequences

### Positive
- Users can sandbox untrusted MCP servers with a single config line
- Deny-all default provides strong isolation without per-server configuration
- Fail-closed design prevents accidental unsandboxed execution
- No external dependencies on macOS; single package install on Linux

### Negative
- `sandbox-exec` is deprecated (though still widely used and functional)
- Windows has no supported engine
- Servers that need filesystem access must have `paths` explicitly configured
- No resource limits (CPU/memory) — requires separate OS-level controls
- On macOS, Seatbelt's allow-wins semantics prevent carving out exceptions within allowed paths

### Risks
- Apple could remove `sandbox-exec` in a future macOS release
- Ubuntu AppArmor restrictions on unprivileged user namespaces may require extra configuration
- Process group management under `--unshare-pid` needs careful testing

## Status

Accepted
