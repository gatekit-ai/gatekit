# ADR-017: TUI Invocation Pattern

> **Note: The command structure has been updated from `gatekit proxy` to `gatekit-gateway`**
to eliminate terminology confusion.

## Context

Gatekit serves two distinct use cases that require different invocation patterns:

1. **MCP Client Integration**: Automated systems (like Claude Desktop) invoke Gatekit to proxy MCP connections between clients and servers. This requires a stable, predictable command-line interface.

2. **Human Configuration**: Users need an intuitive way to configure Gatekit's security policies, audit settings, and server connections through a Terminal User Interface (TUI).

The challenge is providing both capabilities without creating confusion or breaking existing integrations.

### Initial Considerations

We initially considered several approaches:

1. **Auto-detection based on `isatty()`**: Automatically launch TUI when stdin is a terminal, proxy mode when piped. This was rejected as "too clever" and potentially confusing.

2. **Mode flags**: Using flags like `--tui` vs default proxy behavior. This requires users to remember flags and doesn't make the default use case obvious.

3. **Separate commands**: Creating `gatekit-config` alongside `gatekit`. This fragments the user experience and requires separate installation/distribution.

4. **Subcommands with serve**: Using `gatekit serve --config` vs `gatekit config`. The word "serve" was deemed inaccurate since Gatekit acts as a proxy, not a server.

## Decision

We will implement a **human-first default** with explicit subcommands:

- **`gatekit`** - Opens TUI configuration interface (default behavior)
- **`gatekit <path-to-config>`** - Opens TUI with specific configuration file loaded
- **`gatekit-gateway --config <path-to-config>`** - Run as MCP gateway/proxy (required for MCP clients)

## Rationale

### Human-First Default

Making TUI the default behavior optimizes for the most common human interaction: configuration. Users can simply type `gatekit` to manage their security policies and server configurations.

### Explicit Automation

MCP clients and automated systems must explicitly use `gatekit-gateway --config file`. This:
- Makes the intent clear in configuration files
- Prevents accidental TUI launches in automated contexts  
- Provides stability for programmatic usage
- Uses accurate terminology ("proxy" matches Gatekit's technical role)

### Progressive Disclosure

New users encounter the friendly TUI by default, while advanced users and automated systems use explicit subcommands. This follows the principle of making simple things simple and complex things possible.

### Terminology Alignment

Using `proxy` as the subcommand aligns with Gatekit's technical architecture and clarifies its role for users. The separate `gatekit-gateway` command provides a clear entry point for MCP client integration.

## Consequences

### Positive

- **Intuitive default**: Users get immediate value from typing `gatekit`
- **Clear separation**: Configuration vs operation modes are explicit
- **Future extensibility**: Easy to add more subcommands (`gatekit validate`, `gatekit status`, etc.)
- **Automation-friendly**: MCP clients have stable, explicit invocation

### Negative

- **Breaking change**: Existing MCP client configurations must be updated
- **Migration effort**: Users must update their `claude_desktop_config.json` files
- **Command complexity**: Slightly more verbose for MCP client configurations

### Migration Strategy

To minimize disruption during the transition:

1. **Backward compatibility detection**: If `--config` is used without a subcommand and stdin is not a TTY (indicating MCP client usage), show a deprecation warning and run in proxy mode.

2. **Clear migration guidance**: Provide documentation and examples for updating MCP client configurations.

3. **Graceful degradation**: If Textual fails to import, provide a helpful error message.

## Implementation Details

### Command Structure

```bash
# TUI modes (human interaction)
gatekit                         # Open TUI with default/last config
gatekit <path-to-config>        # Open TUI with specific config

# Gateway mode (MCP client integration)
gatekit-gateway --config <path-to-config>   # Run as MCP gateway/proxy

# Future extensibility
gatekit validate --config <path-to-config>  # Validate configuration
gatekit status                               # Show running instances
```

### Separate Entry Points

The final implementation uses separate entry points for clarity:
- `gatekit` - TUI entry point (human interaction)
- `gatekit-gateway` - Gateway entry point (MCP client integration)

This eliminates the need for runtime detection or deprecation warnings.

### Dependencies

- Textual (`textual~=7.2.0`) is a core dependency of Gatekit
- Both `gatekit` (TUI) and `gatekit-gateway` include Textual in their installation
- The TUI leverages Textual's rich terminal UI capabilities

## Alternative Considered

**Option: `gatekit run --config`** was considered as a neutral alternative to avoid the gateway/proxy terminology tension. The final decision was `gatekit-gateway` as a separate command to maintain technical clarity.

## Decision Makers

User preference after evaluating multiple approaches and considering both technical accuracy and user experience implications.