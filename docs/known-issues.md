# Known Issues

This document tracks known issues, limitations, and workarounds in Gatekit.

## Logging

### stderr Logging Not Supported on Windsurf (Windows)

**Issue**: Windsurf on Windows appears to terminate MCP server processes that write to stderr. The MCP specification explicitly allows stderr for logging purposes, so this may be a client compatibility issue.

**Affected**: Windsurf IDE on Windows only. Claude Desktop and Windsurf on macOS handle stderr correctly.

**Workaround**: The guided setup defaults to file-only logging (`handlers: ["file"]`). If you manually add `stderr` to handlers and use Windsurf on Windows, the gateway will be terminated immediately after startup.

**Status**: This appears to be a Windsurf bug. If Windsurf fixes this behavior, stderr logging can be re-enabled as a default option.

### Multiple Clients Writing to Same Log File

**Issue**: When multiple MCP clients (e.g., Claude Desktop and Windsurf) use the same Gatekit configuration file, their logs are interleaved in the same log file, making debugging difficult.

**Workaround**: Create separate configuration files for each client with different `file_path` values:

```yaml
# configs/gatekit-claude.yaml
logging:
  handlers: ["file"]
  file_path: "logs/gatekit-claude.log"

# configs/gatekit-windsurf.yaml
logging:
  handlers: ["file"]
  file_path: "logs/gatekit-windsurf.log"
```

**Status**: Future releases may add automatic per-session log separation.

## Terminal Compatibility

### TUI Rendering Issues in Ghostty Terminal

**Issue**: The Gatekit TUI renders with washed-out colors and poor contrast in Ghostty terminal. The default blue theme appears as dark gray, and some UI elements (particularly Input field borders in config modals) may be invisible or hard to see.

**Affected**: Ghostty terminal on macOS. Other terminals (iTerm2, Terminal.app, Kitty, WezTerm) render correctly.

**Root Cause**: Multiple factors contribute to this issue:
1. **Color space differences**: Ghostty uses sRGB color space by default, which renders truecolor RGB values differently than other terminals
2. **minimum-contrast feature**: Ghostty's automatic contrast adjustment can make similar colors identical, causing borders to disappear
3. **Textual framework**: Gatekit uses Textual which relies on 16.7 million truecolor values rather than ANSI palette colors, making it sensitive to color space handling

**Workaround**: Add the following to your Ghostty config (`~/.config/ghostty/config`):

```ini
# Use Display P3 color space (macOS only) - fixes washed-out colors
window-colorspace = display-p3

# Disable aggressive contrast adjustments that can hide UI elements
minimum-contrast = 1
```

**References**:
- [Ghostty Config Reference](https://ghostty.org/docs/config/reference)
- [Ghostty Discussion #5322 - ANSI colors muted](https://github.com/ghostty-org/ghostty/discussions/5322)
- [Ghostty Discussion #6083 - minimum-contrast muting colors](https://github.com/ghostty-org/ghostty/discussions/6083)

**Status**: This is a terminal-specific rendering behavior. The workaround above resolves most issues. Future Gatekit releases may add Ghostty-specific detection and styling adjustments.

## Plugin Configuration

### Server-Specific Plugin Override Not Working

**Issue**: Setting `enabled: false` on a server-specific plugin configuration does not override a globally-enabled plugin. The global plugin still applies to that server.

**Example**:
```yaml
proxy:
  _global:
    plugins:
      - handler: prompt_injection
        enabled: true
        config:
          action: redact

  servers:
    everything:
      plugins:
        - handler: prompt_injection
          enabled: false  # Expected to disable for this server, but doesn't
```

**Expected Behavior**: Server-specific `enabled: false` should override the global plugin, effectively exempting that server from the global plugin's scope.

**Actual Behavior**: The global plugin continues to apply to the server regardless of the server-specific `enabled: false` setting.

**Workaround**: Instead of enabling globally and disabling for specific servers, disable the plugin globally and explicitly enable it on each server where you want it applied.

**Status**: Under investigation. This affects all server-aware plugins where server-specific configuration is intended to override global settings.
