# ADR-018: Plugin UI Widget Architecture

## Context

Gatekit's TUI needs two distinct mechanisms for plugin UI integration:

1. **Main Screen Display**: Datatable showing all available plugins (enabled/disabled) with status summaries
2. **Configuration Screens**: Complex forms for detailed plugin configuration

### Main Screen Requirements:
- Display ALL available plugins from HANDLERS manifests (even disabled ones)
- Show status without requiring instantiation (config-driven display)
- Structured datatable with specific columns: enabled checkbox, name, status description, action buttons
- Work uniformly for built-in and user plugins

### Configuration Screen Requirements:
- **Security plugins** need complex UIs (PII types, detection actions)  
- **Auditing plugins** need file management, formatting options, connection settings
- **Server-specific plugins** need context about available tools and server capabilities
- **Different plugin types** have fundamentally different configuration needs

We need a solution that:
- Provides structured data for datatable display while maintaining flexibility for configuration
- Gives plugin authors maximum flexibility for their detailed configuration UI
- Avoids forcing all plugins into a generic configuration schema
- Allows plugins to leverage the full power of Textual widgets
- Maintains consistency with Gatekit's TUI experience  
- Works with optional Textual dependency (graceful fallback)
- Respects the elegant simplicity of the HANDLERS manifest system

## Decision

**Plugins provide both structured display metadata AND their own Textual widgets for TUI integration.**

This dual approach addresses both requirements:

1. **Class-level display metadata** for main screen datatable (no instantiation required)
2. **Instance-level configuration widgets** for detailed configuration screens

### Display Metadata Contract

All plugins that want TUI display must provide class-level attributes:

```python
class MyPlugin(SecurityPlugin):
    # Required display metadata
    DISPLAY_NAME = "My Plugin"         # Human-readable name
    DISPLAY_SCOPE = "global"           # "global", "server_aware", or "server_specific"
    
    @classmethod
    def describe_status(cls, config: dict) -> str:
        """Generate status description from configuration.
        
        Called by TUI to populate the status column. Must work
        without plugin instantiation. Config may be empty for
        disabled plugins.
        
        Args:
            config: Current plugin configuration dict (may be empty)
            
        Returns:
            Status string for display (e.g. "Blocking: API Keys, Tokens")
        """
    
    @classmethod  
    def get_display_actions(cls, config: dict) -> List[str]:
        """Return available UI actions based on configuration state.
        
        Args:
            config: Current plugin configuration dict (may be empty)
            
        Returns:
            List of action strings (e.g. ["Configure", "Test"])
        """
```

### Configuration Widget Contract

Plugins that want detailed TUI configuration must implement:

```python
@classmethod
def get_config_widget(cls, current_config: dict, context: dict = None):
    """Return a Textual widget for configuration.
    
    Args:
        current_config: Current configuration dict for this plugin
        context: Optional context (server_name, available_tools, etc.)
        
    Returns:
        A Textual widget that implements get_config() method
        Or None if plugin doesn't support TUI configuration
    """
```

The returned widget MUST implement:
```python
def get_config(self) -> dict:
    """Extract configuration from widget state."""
```

### Complete Implementation Pattern

```python
from typing import Dict, Any, List
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult

# Import Textual only when needed
try:
    from textual.app import ComposeResult
    from textual.containers import Container, Vertical, Horizontal
    from textual.widgets import Static, RadioSet, Checkbox
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

class MyPlugin(SecurityPlugin):
    """Complete plugin with both display metadata and configuration widget."""
    
    # ========== Display Metadata (Required for TUI) ==========
    DISPLAY_NAME = "My Security Plugin"
    DISPLAY_SCOPE = "global"  # Can appear in global security section
    
    @classmethod
    def describe_status(cls, config: dict) -> str:
        """Generate status description from configuration."""
        if not config or not config.get("enabled", False):
            return "Click to enable security filtering" 
        
        # Build description from config
        action = config.get("action", "block")
        rules_count = len(config.get("rules", []))
        
        if rules_count == 0:
            return "No rules configured"
        elif rules_count == 1:
            return f"{action.title()}: {rules_count} rule active"
        else:
            return f"{action.title()}: {rules_count} rules active"
    
    @classmethod
    def get_display_actions(cls, config: dict) -> List[str]:
        """Return available UI actions."""
        if config and config.get("enabled", False):
            return ["Configure", "Test"] 
        return ["Setup"]
    
    # ========== Core Plugin Logic (Unchanged) ==========
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize plugin - only called when enabled."""
        super().__init__(config)
        self.action = config["action"]
        # ... rest of plugin initialization
    
    async def process_request(self, request, server_name: str) -> PluginResult:
        """Core security logic - unchanged."""
        # ... existing security implementation
        pass
    
    # ========== TUI Configuration Widget (Optional) ==========
    
    @classmethod
    def get_config_widget(cls, current_config: dict, context: dict = None):
        """Return widget for detailed configuration."""
        if not HAS_TEXTUAL:
            return None
        return cls.MyConfigWidget(current_config, context)
    
    # Define widget as inner class
    if HAS_TEXTUAL:
        class MyConfigWidget(Container):
            """TUI configuration widget."""
            
            def __init__(self, config: dict, context: dict = None):
                super().__init__()
                self.config = config or {}
                self.context = context or {}
            
            def compose(self) -> ComposeResult:
                """Plugin authors have complete control over layout."""
                # Use any Textual widgets, custom layouts, styling, etc.
                pass
            
            def get_config(self) -> dict:
                """Extract config from widget state."""
                # Plugin handles their own config extraction
                return {}

# HANDLERS manifest stays simple
HANDLERS = {
    "my_plugin": MyPlugin
}
```

### TUI Integration

**Main Screen Datatable Population:**
```python
# Populate global plugins datatable
def populate_global_plugins():
    for plugin_module in discover_plugin_modules():
        for handler_name, plugin_class in plugin_module.HANDLERS.items():
            # Check if plugin should appear in global sections
            scope = getattr(plugin_class, 'DISPLAY_SCOPE', 'server')
            if scope == 'global':
                # Get current config (may be empty for disabled plugins)
                config = get_plugin_config('_global', handler_name)
                
                # Get display data without instantiation
                name = getattr(plugin_class, 'DISPLAY_NAME', handler_name)
                status = plugin_class.describe_status(config)
                actions = plugin_class.get_display_actions(config)
                enabled = config.get('enabled', False) if config else False
                
                # Add row to datatable
                add_plugin_row(enabled, name, status, actions)
```

**Configuration Screen Widget Mounting:**
```python  
# Mount plugin configuration widget
if hasattr(plugin_class, 'get_config_widget'):
    widget = plugin_class.get_config_widget(current_config, context)
    if widget:
        # Mount the plugin's widget directly
        self.mount(widget)
        return

# Plugin doesn't support TUI configuration
self.mount(Static("Plugin doesn't provide TUI configuration"))
```

## Real-World Examples

### Security Plugin: PII Filter

```python
class BasicPIIFilterPlugin(SecurityPlugin):
    """PII filtering with realistic display metadata."""
    
    DISPLAY_NAME = "PII Filter"
    DISPLAY_SCOPE = "global"
    
    @classmethod
    def describe_status(cls, config: dict) -> str:
        """Generate description from PII filter configuration."""
        if not config or not config.get("enabled", False):
            return "Click to enable PII protection"
        
        action = config.get("action", "redact")
        pii_types = config.get("pii_types", {})
        
        # Count enabled PII types
        enabled = []
        if pii_types.get("email", {}).get("enabled", False):
            enabled.append("Email")
        if pii_types.get("phone", {}).get("enabled", False):
            enabled.append("Phone")
        if pii_types.get("ssn", {}).get("enabled", False):
            enabled.append("SSN")
        
        if not enabled:
            return "No PII types configured"
        elif len(enabled) <= 3:
            return f"{action.title()}: {', '.join(enabled)}"
        else:
            return f"{action.title()}: {len(enabled)} PII types"
    
    @classmethod
    def get_display_actions(cls, config: dict) -> List[str]:
        """Return actions based on configuration state."""
        if config and config.get("enabled", False):
            return ["Configure"]
        return ["Setup"]

# Core plugin logic unchanged...
HANDLERS = {"pii": BasicPIIFilterPlugin}
```

### Auditing Plugin: JSON Logger

```python
class JsonAuditingPlugin(AuditingPlugin):
    """JSON audit logging with file status display."""
    
    DISPLAY_NAME = "JSON Logger"
    # Note: AuditingPlugin subclasses don't use DISPLAY_SCOPE
    
    @classmethod
    def describe_status(cls, config: dict) -> str:
        """Show output file and status."""
        if not config or not config.get("enabled", False):
            return "Export audit logs to JSON format"
        
        output_file = config.get("output_file", "audit.json")
        
        # Check if file exists and get size (if available)
        import os
        if os.path.exists(output_file):
            size_mb = os.path.getsize(output_file) / 1_048_576
            return f"{output_file} ({size_mb:.1f}MB today)"
        else:
            return f"{output_file} (not created yet)"
    
    @classmethod
    def get_display_actions(cls, config: dict) -> List[str]:
        """Return actions with log viewing capability."""
        if config and config.get("enabled", False):
            output_file = config.get("output_file", "")
            if os.path.exists(output_file):
                return ["View Logs", "Configure"]
            return ["Configure"]
        return ["Setup"]

# Core plugin logic unchanged...
HANDLERS = {"json_auditing": JsonAuditingPlugin}
```

### Server-Specific Plugin: Tool Manager

```python
class ToolManagerPlugin(MiddlewarePlugin):
    """Tool manager with server-specific display."""

    DISPLAY_NAME = "Tool Manager"
    DISPLAY_SCOPE = "server_aware"  # Requires per-server configuration

    @classmethod
    def describe_status(cls, config: dict) -> str:
        """Show tool configuration summary."""
        if not config or not config.get("enabled", False):
            return "Control tool visibility and execution"

        tools = config.get("tools", [])

        # Count configured tools (implicit allowlist - tools in list are allowed)
        if not tools:
            return "No tools configured"

        tool_count = len(tools)
        return f"Allow {tool_count} tool{'s' if tool_count != 1 else ''}"

    @classmethod
    def get_display_actions(cls, config: dict) -> List[str]:
        """Context-aware actions."""
        if config and config.get("enabled", False):
            return ["Configure", "Test"]
        return ["Setup"]

# Core plugin logic unchanged...
HANDLERS = {"tool_manager": ToolManagerPlugin}
```

## Alternatives Considered

### 1. Schema-Based Configuration
**Approach:** Plugins declare configuration schemas, TUI generates forms automatically.

**Rejected because:**
- Forces all plugins into generic form patterns
- Cannot handle complex UI needs (grouped checkboxes, dynamic layouts)
- Requires maintaining schema language and form generator
- Plugin authors lose control over user experience

### 2. Abstraction Layer
**Approach:** Create intermediate widgets (ConfigSection, ConfigGroup) that plugins compose.

**Rejected because:**
- Adds unnecessary complexity and learning curve
- Limits plugin authors to our predefined widget types
- Still requires maintaining abstraction layer code
- Textual already provides excellent primitive widgets

### 3. External Configuration Tools
**Approach:** Launch external editors or web interfaces for plugin configuration.

**Rejected because:**
- Breaks unified TUI experience
- Adds complexity for deployment and dependencies
- Poor user experience (context switching)
- Difficult to integrate with live configuration updates

### 4. YAML-Only Configuration
**Approach:** Require all plugin configuration via YAML files.

**Rejected because:**
- Poor user experience for complex configurations
- No validation feedback or guided setup
- Difficult to discover available options
- No integration with server context (available tools, etc.)

## Consequences

### Positive

**Display Metadata Benefits:**
- **Structured data** - TUI gets exactly the datatable columns it needs
- **No instantiation required** - Works for both enabled and disabled plugins  
- **Config-driven display** - Status reflects actual configuration state
- **Minimal plugin burden** - Simple class attributes and methods
- **Uniform treatment** - All plugins work identically for TUI integration

**Configuration Widget Benefits:**
- **Maximum flexibility** - Plugin authors use Textual however they want for detailed config
- **Single file approach** - All code (logic + display + UI) in one place
- **No abstraction overhead** - Direct use of Textual widgets
- **Future-proof** - As Textual evolves, plugins can use new features immediately
- **Context-aware** - Plugins receive server context for intelligent UIs

**Overall Benefits:**
- **Equal treatment** - Built-in plugins follow same rules as user plugins
- **Graceful fallback** - Works without Textual installed  
- **Respects HANDLERS** - Works perfectly with existing plugin discovery system
- **Separation of concerns** - Display metadata vs. detailed configuration widgets

### Negative

**Display Metadata Limitations:**
- **Additional methods required** - Plugin authors must implement `describe_status()` and `get_display_actions()`
- **Config parsing complexity** - Status generation requires understanding config structure
- **Static class attributes** - Less dynamic than instance-based approaches

**Configuration Widget Limitations:**
- **Learning curve** - Plugin authors must learn Textual for detailed configuration  
- **Code duplication** - Similar UI patterns may be repeated across plugins
- **Testing complexity** - Plugin authors must test their UI components
- **Textual dependency** - Optional but required for TUI configuration features

### Mitigations

**For Display Metadata:**
- Provide clear examples and templates for common plugin types
- Default implementations for simple cases
- Configuration parsing utilities for common patterns
- Comprehensive testing of display methods

**For Configuration Widgets:**
- Comprehensive examples and documentation for Textual patterns
- Include common UI patterns in documentation
- Make Textual dependency optional with clear fallback behavior
- Ensure core plugin functionality works without UI components

## Implementation Notes

### Display Metadata Requirements
- `DISPLAY_NAME` must be a human-readable string suitable for datatable display
- `DISPLAY_SCOPE` (SecurityPlugin only) must be one of: `"global"`, `"server_aware"`, or `"server_specific"`
  - AuditingPlugin subclasses don't use DISPLAY_SCOPE - they always appear in global sections
- `describe_status()` must handle empty/missing config gracefully  
- `get_display_actions()` should return 1-3 action strings maximum for UI space constraints

### Configuration Widget Context Parameter
The `context` parameter in `get_config_widget()` allows plugins to receive relevant information:
- `server_name`: For server-specific plugins
- `available_tools`: For tool-related security plugins  
- `upstream_config`: Server configuration details
- `capabilities`: Server capabilities from MCP discovery

### Error Handling

**Display Metadata:**
- Missing `DISPLAY_NAME` defaults to handler name from HANDLERS
- Missing `DISPLAY_SCOPE` defaults to `"global"`
- Exceptions in `describe_status()` show "Error loading status"
- Exceptions in `get_display_actions()` default to `["Configure"]`

**Configuration Widgets:**
- If `get_config_widget()` raises an exception, treat as "no TUI support"
- If returned widget doesn't implement `get_config()`, show error message
- Invalid configuration from `get_config()` should be handled gracefully

### Testing Strategy

**Display Metadata Testing:**
- Unit test `describe_status()` with various config scenarios (empty, disabled, various settings)
- Unit test `get_display_actions()` with different configuration states
- Integration test that display metadata populates datatables correctly

**Configuration Widget Testing:**
- Plugin UI components should be unit tested independently
- TUI integration tests verify widget mounting and config extraction
- Manual testing for complex UI interactions

## Plugin Configuration Behavior

This section documents how plugin configurations are resolved and applied across upstream servers, which directly impacts plugin display in the TUI.

### Configuration Resolution Rules

Gatekit uses an upstream-scoped configuration system where plugins can be configured globally (`_global`) or per-server. The resolution algorithm is:

1. **Start with global plugins**: Copy all plugins from `_global` section
2. **Add server-specific plugins**: For each plugin in the server's section:
   - If a plugin with the same handler name exists from global, **replace it** (override)
   - If no matching global plugin exists, **add it** (augment)
3. **Sort by priority**: Order final plugin list by priority (lower numbers = higher priority)

**Example Configuration:**
```yaml
plugins:
  security:
    _global:
      - handler: "basic_pii_filter"
        config: {action: "redact"}
      - handler: "secrets_detection"
        config: {action: "redact"}
    filesystem:
      - handler: "basic_pii_filter"    # Override global pii
        config: {action: "block"}
  middleware:
    filesystem:
      - handler: "tool_manager"        # Server-aware middleware
        config:
          tools:
            - tool: "read_file"
            - tool: "write_file"

# Result for 'filesystem' server:
# 1. basic_pii_filter with action: "block" (overridden from global)
# 2. secrets_detection with action: "redact" (inherited from global)
# 3. tool_manager with configured tools (server-specific middleware)
```

### Plugin Scope Restrictions

Plugin scope categories determine where plugins can be meaningfully configured:

**Global Scope Plugins** (`DISPLAY_SCOPE = "global"`):
- ✅ Can be configured in `_global` section
- ✅ Can be configured in server sections
- ✅ Can use mixed global + override pattern
- Examples: `pii`, `secrets`, `prompt_injection`, all auditing plugins

**Server-Aware Scope Plugins** (`DISPLAY_SCOPE = "server_aware"`):
- ❌ CANNOT be configured in `_global` section
- ✅ Can be configured in server sections
- Examples: `tool_manager` (needs per-server tool names)

**Server-Specific Scope Plugins** (`DISPLAY_SCOPE = "server_specific"`):
- ❌ CANNOT be configured in `_global` section
- ✅ Can be configured in compatible server sections only
- Examples: `filesystem_server` (only for filesystem servers)

### Validation Rules

The configuration validation enforces these rules:
- Server-aware and server-specific plugins in `_global` sections generate validation errors
- Plugin references to unknown servers generate validation errors
- Server-specific plugins in incompatible server sections generate validation errors

### TUI Display Implications

This configuration behavior directly impacts plugin display in the TUI:

**Global Security Section:**
- Shows only `DISPLAY_SCOPE = "global"` plugins
- Status should reflect which servers the plugin is enabled on
- Example: "PII Filter ✅ Enabled on 2/3 servers"

**Server Security Sections:**
- Shows `DISPLAY_SCOPE = "global"`, `"server_aware"`, and compatible `"server_specific"` plugins
- Status should indicate configuration source
- Examples:
  - "PII Filter ✅ Enabled (from global config)"
  - "PII Filter ✅ Block (overrides global redact)"
  - "Tool Manager ✅ Allow 5 tools"

**Global Auditing Section:**
- Shows all auditing plugins (they don't use DISPLAY_SCOPE)
- Typically configured globally for consistent audit trails
- Server-specific auditing configurations are supported but less common

### Plugin Configuration Patterns

The configuration system supports three main patterns:

1. **Global-Only**: Same policies for all servers (simple deployments)
2. **Server-Specific Only**: Independent policies per server (maximum control)
3. **Mixed Global + Override**: Global defaults with targeted server overrides (balanced approach)

Plugin display metadata methods (`describe_status()`, `get_display_actions()`) should handle all these patterns appropriately and provide meaningful status descriptions that reflect the actual effective configuration for each plugin-server combination.

## References
- Textual Documentation: https://textual.textualize.io/
- Plugin Interface Definition: `gatekit/plugins/interfaces.py`