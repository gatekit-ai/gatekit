# Plugin Development Guide

This guide covers writing custom plugins for Gatekit. Plugins let you intercept MCP traffic to transform messages, enforce security policies, or log activity.

## Plugin Types

Gatekit has three plugin types:

| Type | Purpose | Can Block? | Can Modify? |
|------|---------|------------|-------------|
| **Middleware** | Transform requests/responses, complete requests early | No | Yes |
| **Security** | Allow/block decisions based on content | Yes | Yes |
| **Auditing** | Log and observe message flow | No | No |

Choose based on what you need:
- **Transform content** (rename tools, modify responses) → Middleware
- **Block dangerous content** (PII, secrets, injections) → Security
- **Log activity** (audit trail, debugging) → Auditing

## Quick Start

### Minimal Middleware Plugin

```python
from typing import Dict, Any
from gatekit.plugins.interfaces import MiddlewarePlugin, PluginResult
from gatekit.protocol.messages import MCPRequest

class MyMiddlewarePlugin(MiddlewarePlugin):
    DISPLAY_NAME = "My Middleware"
    DESCRIPTION = "Does something useful with requests."

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.my_setting = config.get("my_setting", "default")

    async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
        # Your logic here
        return PluginResult(reason="Processed successfully")

HANDLERS = {"my_middleware": MyMiddlewarePlugin}
```

### Minimal Security Plugin

```python
from typing import Dict, Any
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult
from gatekit.protocol.messages import MCPRequest

class MySecurityPlugin(SecurityPlugin):
    DISPLAY_NAME = "My Security Plugin"
    DESCRIPTION = "Checks requests for policy violations."
    DISPLAY_SCOPE = "global"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

    async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
        # Security plugins MUST set allowed=True or allowed=False
        if self._is_dangerous(request):
            return PluginResult(allowed=False, reason="Policy violation detected")
        return PluginResult(allowed=True, reason="Request approved")

    def _is_dangerous(self, request: MCPRequest) -> bool:
        # Your detection logic
        return False

HANDLERS = {"my_security": MySecurityPlugin}
```

### Minimal Auditing Plugin

```python
from typing import Dict, Any
from gatekit.plugins.interfaces import AuditingPlugin, ProcessingPipeline
from gatekit.protocol.messages import MCPRequest, MCPResponse

class MyAuditingPlugin(AuditingPlugin):
    DISPLAY_NAME = "My Auditing Plugin"
    DESCRIPTION = "Logs MCP activity."

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.log_file = config.get("log_file", "my_audit.log")

    async def log_request(self, request: MCPRequest, pipeline: ProcessingPipeline, server_name: str) -> None:
        # Log the request - full pipeline visibility available
        print(f"Request: {request.method} to {server_name}")

    async def log_response(self, request: MCPRequest, response: MCPResponse, pipeline: ProcessingPipeline, server_name: str) -> None:
        print(f"Response: {request.method} from {server_name}")

HANDLERS = {"my_auditing": MyAuditingPlugin}
```

### Installing Your Plugin

Place your plugin file in the appropriate directory inside your Gatekit installation:

```
gatekit/plugins/
├── middleware/
│   └── my_middleware.py      # Your middleware plugin
├── security/
│   └── my_security.py        # Your security plugin
└── auditing/
    └── my_auditing.py        # Your auditing plugin
```

For multi-file plugins, use a subdirectory:

```
gatekit/plugins/security/
└── my_complex_plugin/
    ├── __init__.py           # Can be empty
    ├── main.py               # Contains HANDLERS dict
    └── patterns.py           # Helper module
```

Once installed, your plugin appears in the terminal UI (TUI) and can be enabled on any server.

### Enabling via TUI

After installing your plugin:

1. Run `gatekit`
2. Select a server to configure, or choose global settings to apply the plugin to all servers
3. Find your plugin in the appropriate section (Middleware, Security, or Auditing)
4. Enable and configure it

The TUI handles all YAML configuration for you.

## PluginResult

All plugins return `PluginResult`. The fields you use depend on what you're doing:

```python
@dataclass
class PluginResult:
    allowed: Optional[bool] = None        # Security decision (required for SecurityPlugin)
    modified_content: Optional[...] = None # Modified request/response/notification
    completed_response: Optional[MCPResponse] = None  # Return this directly to client, skip MCP server
    reason: str = ""                       # Human-readable explanation
    metadata: Dict[str, Any] = field(default_factory=dict)  # Extra info for auditing
```

### Common Patterns

**Pass through unchanged:**
```python
return PluginResult()
```

**Block a request (Security only):**
```python
return PluginResult(allowed=False, reason="Contains PII")
```

**Allow a request (Security only):**
```python
return PluginResult(allowed=True, reason="Clean")
```

**Modify content:**
```python
# Safely merge new values into params (params can be None or List)
new_params = dict(request.params) if isinstance(request.params, dict) else {}
new_params["name"] = "new_tool_name"

modified_request = MCPRequest(
    jsonrpc=request.jsonrpc,
    id=request.id,
    method=request.method,
    params=new_params,
)
return PluginResult(
    modified_content=modified_request,
    reason="Renamed tool"
)
```

**Complete request early (Middleware only):**
```python
cached_result = self.cache.get(cache_key)
if cached_result:
    return PluginResult(
        completed_response=MCPResponse(
            jsonrpc=request.jsonrpc,
            id=request.id,
            result=cached_result,
        ),
        reason="Returned from cache"
    )
```

## Middleware Plugins

Middleware plugins transform messages or complete requests early. They cannot block messages (use SecurityPlugin for that).

### Key Methods

```python
class MiddlewarePlugin(PluginInterface):
    async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
        """Process incoming request before it reaches the server."""
        return PluginResult()

    async def process_response(self, request: MCPRequest, response: MCPResponse, server_name: str) -> PluginResult:
        """Process response from server before it reaches the client."""
        return PluginResult()

    async def process_notification(self, notification: MCPNotification, server_name: str) -> PluginResult:
        """Process notification messages."""
        return PluginResult()
```

### Example: Tool Filtering

The built-in `tool_manager` plugin shows how to filter tools (simplified):

```python
async def process_response(self, request: MCPRequest, response: MCPResponse, server_name: str) -> PluginResult:
    # Only process tools/list responses
    if request.method != "tools/list" or not response.result:
        return PluginResult()

    tools = response.result.get("tools", [])
    allowed_names = {t["tool"] for t in self.tools}  # self.tools from config

    # Filter tools based on allowlist
    filtered_tools = [t for t in tools if t.get("name") in allowed_names]

    # Create modified response
    modified_result = {**response.result, "tools": filtered_tools}
    modified_response = MCPResponse(
        jsonrpc=response.jsonrpc,
        id=response.id,
        result=modified_result,
    )

    return PluginResult(
        modified_content=modified_response,
        reason=f"Filtered to {len(filtered_tools)} tools"
    )
```

### Priority

Middleware and security plugins share the same priority ordering (0-100, lower = higher priority). This determines the order plugins execute in the pipeline:

```python
def __init__(self, config: Dict[str, Any]):
    super().__init__(config)
    # Priority is set automatically from config, defaults to 50
    # self.priority is available after super().__init__
```

Configure priority in the TUI or YAML:
```yaml
plugins:
  middleware:
    server_name:
      - handler: my_middleware
        config:
          priority: 10  # Runs before plugins with priority > 10
```

## Security Plugins

Security plugins make allow/block decisions. They **must** set `allowed=True` or `allowed=False` in their return value.

### Key Requirement

Every `process_*` method must return a PluginResult with `allowed` set:

```python
async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
    # CORRECT - always set allowed
    if dangerous:
        return PluginResult(allowed=False, reason="Blocked")
    return PluginResult(allowed=True, reason="Allowed")

    # WRONG - missing allowed field will cause issues
    # return PluginResult(reason="Something")
```

### Display Scopes

Middleware and security plugins declare where they appear in the TUI:

```python
class MySecurityPlugin(SecurityPlugin):
    DISPLAY_SCOPE = "global"  # One of: "global", "server_aware", "server_specific"
```

| Scope | When to Use |
|-------|-------------|
| `global` | Plugin works the same for all servers (PII filter, secrets filter) |
| `server_aware` | Plugin needs per-server configuration (tool allowlists) |
| `server_specific` | Plugin is designed for a specific server type |

### Example: Pattern Detection

The built-in PII filter shows pattern-based security:

```python
class BasicPIIFilterPlugin(SecurityPlugin):
    DISPLAY_NAME = "Basic PII Filter"
    DISPLAY_SCOPE = "global"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.action = config.get("action", "redact")  # block, redact, or audit_only
        self._compile_patterns()

    async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
        if request.params:
            detections = self._detect_pii(request.params)

            if detections and self.action == "block":
                return PluginResult(
                    allowed=False,
                    reason="PII detected",
                    metadata={"detections": detections}
                )
            elif detections and self.action == "redact":
                redacted_params = self._redact(request.params, detections)
                modified = MCPRequest(
                    jsonrpc=request.jsonrpc,
                    id=request.id,
                    method=request.method,
                    params=redacted_params,
                )
                return PluginResult(
                    allowed=True,
                    modified_content=modified,
                    reason="PII redacted"
                )

        return PluginResult(allowed=True, reason="No PII detected")
```

## Auditing Plugins

Auditing plugins observe the processing pipeline without affecting message flow. They have full visibility into what happened during processing.

### Key Methods

```python
class AuditingPlugin(PluginInterface):
    async def log_request(self, request: MCPRequest, pipeline: ProcessingPipeline, server_name: str) -> None:
        """Log request with full pipeline visibility."""
        pass

    async def log_response(self, request: MCPRequest, response: MCPResponse, pipeline: ProcessingPipeline, server_name: str) -> None:
        """Log response with full pipeline visibility."""
        pass

    async def log_notification(self, notification: MCPNotification, pipeline: ProcessingPipeline, server_name: str) -> None:
        """Log notification with full pipeline visibility."""
        pass
```

### ProcessingPipeline

The pipeline gives you full observability into how a message was processed:

```python
async def log_request(self, request: MCPRequest, pipeline: ProcessingPipeline, server_name: str) -> None:
    # Overall outcome
    print(f"Outcome: {pipeline.pipeline_outcome.value}")  # allowed, blocked, modified, etc.
    print(f"Blocked by: {pipeline.blocked_at_stage}")     # Plugin name if blocked
    print(f"Total time: {pipeline.total_time_ms}ms")

    # Per-stage details
    for stage in pipeline.stages:
        print(f"  {stage.plugin_name}: {stage.outcome.value}")
        print(f"    Reason: {stage.result.reason}")
        print(f"    Time: {stage.processing_time_ms}ms")
```

### PathResolvablePlugin Mixin

For auditing plugins that write to files, use the `PathResolvablePlugin` mixin for proper path resolution:

```python
from gatekit.plugins.interfaces import AuditingPlugin, PathResolvablePlugin
from pathlib import Path
from typing import List, Union

class MyFileAuditingPlugin(AuditingPlugin, PathResolvablePlugin):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.raw_output_file = config.get("output_file", "audit.log")
        self.output_file = self.raw_output_file
        self.config_directory = None

    def set_config_directory(self, config_directory: Union[str, Path]) -> None:
        """Called by plugin manager after initialization."""
        self.config_directory = Path(config_directory)
        # Resolve relative paths against config directory
        if not Path(self.raw_output_file).is_absolute():
            self.output_file = str(self.config_directory / self.raw_output_file)

    def validate_paths(self) -> List[str]:
        """Return list of validation errors (empty if valid)."""
        errors = []
        parent = Path(self.output_file).parent
        if parent.exists() and not os.access(parent, os.W_OK):
            errors.append(f"No write permission: {parent}")
        return errors
```

### Using BaseAuditingPlugin

For file-based auditing, extend `BaseAuditingPlugin` instead of `AuditingPlugin` directly. It provides:
- Rotating file handlers
- Path resolution
- Request duration tracking
- Log sanitization
- Buffering for early events

```python
from gatekit.plugins.auditing.base import BaseAuditingPlugin

class MyJsonAuditingPlugin(BaseAuditingPlugin):
    DISPLAY_NAME = "My JSON Logger"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)  # Handles output_file, rotation, etc.

    def _format_request_entry(self, data: Dict[str, Any]) -> str:
        """Format extracted request data into log entry."""
        import json
        return json.dumps(data) + "\n"

    def _format_response_entry(self, data: Dict[str, Any]) -> str:
        import json
        return json.dumps(data) + "\n"

    def _format_notification_entry(self, data: Dict[str, Any]) -> str:
        import json
        return json.dumps(data) + "\n"
```

## Configuration

### JSON Schema for TUI

Plugins can provide JSON Schema for automatic TUI form generation:

```python
@classmethod
def get_json_schema(cls) -> Dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["block", "redact", "audit_only"],
                "description": "What to do when PII is detected",
                "default": "redact",
            },
            "patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Custom regex patterns to detect",
                "default": [],
            },
        },
        "additionalProperties": False,
    }
```

### Schema Defaults Requirement

**Important:** If your schema defines a field as `required`, you must also provide a `default` value:

```python
# CORRECT - required field has default
"properties": {
    "output_file": {
        "type": "string",
        "default": "logs/audit.log",  # Default provided
    },
},
"required": ["output_file"],

# WRONG - will crash TUI when enabling plugin
"properties": {
    "output_file": {
        "type": "string",
        # No default!
    },
},
"required": ["output_file"],
```

The TUI creates initial configuration using schema defaults when a plugin is enabled. Missing defaults for required fields will cause errors.

### Constructor Pattern

Parse and validate configuration in `__init__`:

```python
def __init__(self, config: Dict[str, Any]):
    super().__init__(config)

    # Validate required fields
    if "output_file" not in config:
        raise ValueError("output_file is required")

    # Store validated values
    self.output_file = config["output_file"]
    self.action = config.get("action", "redact")

    # Validate enum values
    if self.action not in ("block", "redact", "audit_only"):
        raise ValueError(f"Invalid action: {self.action}")
```

## TUI Integration

### Display Metadata

Provide class attributes for TUI display:

```python
class MyPlugin(SecurityPlugin):
    # Required for TUI visibility
    DISPLAY_NAME = "My Plugin"           # Human-readable name
    DESCRIPTION = "What this plugin does."  # Short description

    # Middleware and Security plugins only (not Auditing)
    DISPLAY_SCOPE = "global"  # "global", "server_aware", or "server_specific"
```

### Status Display

Override `describe_status` for custom status text in the TUI:

```python
@classmethod
def describe_status(cls, config: Dict[str, Any]) -> str:
    """Generate status text from config (without instantiating plugin)."""
    if not config or not config.get("enabled", False):
        return "Disabled"

    action = config.get("action", "redact")
    count = len(config.get("patterns", []))
    return f"{action.title()}: {count} patterns"
```

### Available Actions

Override `get_display_actions` for TUI action buttons:

```python
@classmethod
def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
    if config and config.get("enabled", False):
        return ["Configure", "Test"]
    return ["Setup"]
```

## Error Handling

### Critical vs Non-Critical

All plugins default to `critical: true` (fail-closed). Set `critical: false` for fail-open behavior:

```yaml
plugins:
  security:
    _global:
      - handler: my_plugin
        config:
          critical: false  # Plugin errors won't halt processing
```

In code, check criticality:

```python
def __init__(self, config: Dict[str, Any]):
    super().__init__(config)
    # self.critical is set by parent class from config

    if self.critical:
        # Fail loudly on config errors
        raise ValueError("Invalid config")
    else:
        # Log warning but continue
        logging.warning("Invalid config, using defaults")
```

### Graceful Degradation

For non-critical plugins, handle errors gracefully:

```python
async def process_request(self, request: MCPRequest, server_name: str) -> PluginResult:
    try:
        # Your logic
        return PluginResult(allowed=True)
    except Exception as e:
        if self.critical:
            raise  # Let it fail
        # Non-critical: log and pass through
        logging.warning(f"Plugin error: {e}")
        return PluginResult(allowed=True, reason="Error, defaulting to allow")
```

## Handler Registration

Every plugin module must export a `HANDLERS` dict:

```python
# At module level (not inside a class)
HANDLERS = {
    "my_plugin": MyPlugin,
    "my_other_plugin": MyOtherPlugin,
}
```

The handler name is what you use in configuration:

```yaml
plugins:
  security:
    _global:
      - handler: my_plugin  # Matches key in HANDLERS dict
        config:
          enabled: true
```

## Testing

### Unit Test Pattern

```python
import pytest
from my_plugin import MySecurityPlugin
from gatekit.protocol.messages import MCPRequest

@pytest.fixture
def plugin():
    return MySecurityPlugin({"action": "block"})

@pytest.mark.asyncio
async def test_blocks_dangerous_content(plugin):
    request = MCPRequest(
        jsonrpc="2.0",
        id="1",
        method="tools/call",
        params={"name": "read_file", "arguments": {"path": "/etc/passwd"}},
    )

    result = await plugin.process_request(request, "test_server")

    assert result.allowed is False
    assert "dangerous" in result.reason.lower()

@pytest.mark.asyncio
async def test_allows_safe_content(plugin):
    request = MCPRequest(
        jsonrpc="2.0",
        id="2",
        method="tools/call",
        params={"name": "read_file", "arguments": {"path": "/home/user/safe.txt"}},
    )

    result = await plugin.process_request(request, "test_server")

    assert result.allowed is True
```

### Testing with ProcessingPipeline

```python
from gatekit.plugins.interfaces import ProcessingPipeline, PipelineOutcome

@pytest.mark.asyncio
async def test_auditing_plugin():
    plugin = MyAuditingPlugin({"output_file": "/tmp/test.log"})

    # Create a mock pipeline
    pipeline = ProcessingPipeline(
        original_content=request,
        pipeline_outcome=PipelineOutcome.ALLOWED,
    )

    # Should not raise
    await plugin.log_request(request, pipeline, "test_server")
```

## Reference

### PluginResult Fields

| Field | Type | Purpose |
|-------|------|---------|
| `allowed` | `Optional[bool]` | Security decision (`True`/`False`/`None`) |
| `modified_content` | `Optional[MCPRequest\|MCPResponse\|MCPNotification]` | Transformed message |
| `completed_response` | `Optional[MCPResponse]` | Short-circuit response (ends pipeline) |
| `reason` | `str` | Human-readable explanation |
| `metadata` | `Dict[str, Any]` | Extra data for auditing |

### StageOutcome Values

| Value | Meaning |
|-------|---------|
| `ALLOWED` | Security plugin allowed the message |
| `BLOCKED` | Security plugin blocked the message |
| `MODIFIED` | Plugin modified the content |
| `COMPLETED_BY_MIDDLEWARE` | Middleware returned a complete response |
| `ERROR` | Plugin raised an exception |

### PipelineOutcome Values

| Value | Meaning |
|-------|---------|
| `ALLOWED` | Message allowed through |
| `BLOCKED` | Message blocked by security plugin |
| `MODIFIED` | Message was modified |
| `COMPLETED_BY_MIDDLEWARE` | Middleware completed the request |
| `ERROR` | Pipeline error |
| `NO_SECURITY_EVALUATION` | No security plugin evaluated the message |

### Plugin Class Attributes

| Attribute | Required | Purpose |
|-----------|----------|---------|
| `DISPLAY_NAME` | Yes | Human-readable name for TUI |
| `DESCRIPTION` | Yes | Short description for TUI |
| `DISPLAY_SCOPE` | Middleware and Security | `"global"`, `"server_aware"`, or `"server_specific"` |

### Inherited Properties

| Property | Source | Default |
|----------|--------|---------|
| `self.critical` | Config `critical` | `True` |
| `self.priority` | Config `priority` | `50` (Middleware and Security) |
