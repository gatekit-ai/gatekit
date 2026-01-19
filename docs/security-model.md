# Gatekit Security Model

**Version**: 0.1.0  
**Status**: Authoritative Reference  

> **Note**: This document describes the ACTUAL behavior of the Gatekit security model as implemented. It serves as the single source of truth for security processing decisions.

## Table of Contents

1. [Threat Model](#threat-model)
2. [Core Concepts](#core-concepts)
3. [Plugin Types](#plugin-types)
4. [Processing Pipeline Flow](#processing-pipeline-flow)
5. [Decision Trees](#decision-trees)
6. [Content Clearing Rules](#content-clearing-rules)
7. [Critical vs Non-Critical Plugin Handling](#critical-vs-non-critical-plugin-handling)
8. [Reason Handling](#reason-handling)
9. [Example Scenarios](#example-scenarios)

## Threat Model

This section describes what Gatekit is designed to protect against, what it provides infrastructure for, and what falls outside its scope.

### What Gatekit Protects Against

- **Overly permissive tool access**: The Tool Manager plugin filters which tools are visible to clients. Clients can only discover and call tools on the allowlist.

- **Unaudited MCP traffic**: Audit plugins log all requests, responses, and notifications flowing through the gateway.

### What Gatekit Provides Infrastructure For

- **Bidirectional content filtering**: Security plugins inspect both requests to servers and responses from servers. This allows filtering of malicious or sensitive content in either direction.

- **Data exposure prevention**: The plugin architecture supports security plugins that inspect content for PII, secrets, or other sensitive data.

> **Note on built-in security plugins**: The built-in plugins (`basic_pii_filter`, `basic_secrets_filter`, `basic_prompt_injection_defense`) use simple regex matching. They catch obvious patterns but not sophisticated obfuscation or encoding. For production use with sensitive data, implement plugins tailored to your specific data formats and threat model.

### What Gatekit Does NOT Protect Against

- **Upstream server process behavior**: Gatekit filters MCP traffic but does not sandbox server processes. A malicious or compromised server can still access the filesystem, make network calls, or perform other actions outside the MCP protocol. Gatekit only sees what flows through the MCP channel.

- **Attackers with host filesystem access**: Configuration files, audit logs, and server processes reside on the host filesystem. Gatekit assumes the host is protected by appropriate OS-level access controls.

- **Sophisticated encoding and obfuscation**: Built-in regex-based detection catches common patterns (standard API key formats, obvious PII). It does not catch base64-encoded secrets, split credentials across multiple requests, or novel obfuscation techniques. Entropy detection can be bypassed by inserting special characters (e.g., `$@!^&*#%`), which fragment high-entropy strings into pieces below the minimum length threshold.

### Trust Boundaries

| Component | Trust Level | Notes |
|-----------|-------------|-------|
| MCP Clients | **Untrusted** | Gatekit filters what they can access and what data flows to/from them |
| Upstream Server Responses | **Filtered** | Security plugins can inspect and block malicious response content |
| Upstream Server Processes | **Trusted** | Not sandboxed; can access filesystem, network, etc. |
| Host Filesystem | **Trusted** | Config and logs assumed protected by OS permissions |

### Audit Log Security

- **Flagged content is not logged**: When security plugins block or redact content, the sensitive data is cleared from pipeline stages before audit logging. Audit logs contain metadata about what happened, not the sensitive content itself. See [Content Clearing Rules](#content-clearing-rules).

- **Log paths are not exposed to clients**: Audit log file locations are not discoverable through the MCP protocol.

- **File permissions**: Protect audit log files with restrictive permissions (mode `0600` or `0700`). Logs contain metadata about tool usage patterns that may be sensitive even without redacted content.

## Core Concepts

### Outcome Enums

#### StageOutcome
Represents the outcome of a single plugin's processing:

```python
class StageOutcome(Enum):
    ALLOWED = "allowed"                             # Plugin allowed request to continue
    BLOCKED = "blocked"                             # Security plugin blocked the request
    MODIFIED = "modified"                           # Plugin modified the content
    COMPLETED_BY_MIDDLEWARE = "completed_by_middleware"  # Middleware provided a complete response
    ERROR = "error"                                 # Plugin threw an exception
```

#### PipelineOutcome
Represents the overall outcome of the entire processing pipeline:

```python
class PipelineOutcome(Enum):
    ALLOWED = "allowed"                            # Request/response allowed through unchanged
    BLOCKED = "blocked"                            # Security plugin blocked
    MODIFIED = "modified"                          # Content was modified but allowed through
    COMPLETED_BY_MIDDLEWARE = "completed_by_middleware"  # Middleware completed the request
    ERROR = "error"                                # Critical plugin error occurred
    NO_SECURITY_EVALUATION = "no_security"         # No security plugins evaluated
```

### Key Data Structures

#### ProcessingPipeline
Contains the complete processing history:
- `original_content`: The original request/response/notification
- `stages`: List of PipelineStage objects (one per plugin)
- `final_content`: The final transformed content (or original if unmodified)
- `pipeline_outcome`: The overall pipeline result
- `had_security_plugin`: Whether any security plugin evaluated the message
- `capture_content`: Whether to capture full content (false after security actions)
- `blocked_at_stage`: Name of plugin that blocked (if any)
- `completed_by`: Name of middleware that completed (if any)

#### PipelineStage
Records a single plugin's processing:
- `plugin_name`: Name of the plugin
- `plugin_type`: "security" or "middleware"
- `result`: The PluginResult returned by the plugin
- `outcome`: StageOutcome enum value
- `error_type`: Exception class name (if error occurred)
- `input_content`/`output_content`: May be cleared for security

## Plugin Types

### SecurityPlugin
- **MUST** set `result.allowed` to `True` or `False` (never `None`)
- Default `critical = True` (fail closed)
- Can modify content via `result.modified_content`
- Sets `pipeline.had_security_plugin = True`

### MiddlewarePlugin
- Can set `result.allowed` to `True`, `False`, or `None`
- Default `critical = True` (all plugins default to fail-closed)
- Can modify content via `result.modified_content`
- Can complete request via `result.completed_response`
- Does NOT set `pipeline.had_security_plugin`

## Processing Pipeline Flow

### Request Processing Flow

1. **Initialize Pipeline**
   - Start with `PipelineOutcome.NO_SECURITY_EVALUATION`
   - Set `capture_content = True`
   - Track `had_critical_error = False` locally

2. **For Each Plugin** (in priority order):
   
   a. **Execute Plugin**
   ```python
   try:
       result = await plugin.process_request(request, server_name)
   except Exception as e:
       # Handle based on criticality (see Critical vs Non-Critical section)
   ```

   b. **Determine StageOutcome**
   - If exception thrown → `StageOutcome.ERROR`
   - If `result.allowed = False` → `StageOutcome.BLOCKED`
   - If `result.completed_response` → `StageOutcome.COMPLETED_BY_MIDDLEWARE`
   - If `result.modified_content` → `StageOutcome.MODIFIED`
   - Otherwise → `StageOutcome.ALLOWED`

   c. **Update Pipeline State**
   - If SecurityPlugin and `result.allowed = True` AND `pipeline_outcome == NO_SECURITY_EVALUATION`:
     → Set `pipeline_outcome = ALLOWED` immediately (but processing continues)
   - Track if critical error occurred → Set `had_critical_error = True` (outcome set later during finalization)
   - When `add_stage()` is called:
     - If `StageOutcome.BLOCKED` → Sets `pipeline_outcome = BLOCKED` and `blocked_at_stage = plugin_name` immediately
     - If `StageOutcome.COMPLETED_BY_MIDDLEWARE` → Sets `pipeline_outcome = COMPLETED_BY_MIDDLEWARE` and `completed_by = plugin_name` immediately
     - If `StageOutcome.ERROR` or `StageOutcome.MODIFIED` → No immediate pipeline outcome change (handled during finalization)

   d. **Determine Whether to Continue**
   - If `StageOutcome.BLOCKED` → Stop processing
   - If `StageOutcome.COMPLETED_BY_MIDDLEWARE` → Stop processing
   - If `StageOutcome.ERROR` and plugin is critical → Stop processing
   - If `StageOutcome.ERROR` and plugin is non-critical → Continue processing
   - Otherwise → Continue to next plugin

3. **Finalize Pipeline**
   - If `had_critical_error` → Set `pipeline_outcome = ERROR`
   - Else if outcome not already final (BLOCKED, COMPLETED_BY_MIDDLEWARE, ERROR):
     - If any stage has `StageOutcome.MODIFIED` → Set `pipeline_outcome = MODIFIED`
     - Else if `had_security_plugin` → Set `pipeline_outcome = ALLOWED`
     - Otherwise leave as `NO_SECURITY_EVALUATION`
   - Apply content clearing if needed (see Content Clearing Rules)

### Response and Notification Processing
Follow the same flow as Request Processing with appropriate method substitutions.

## Decision Trees

### 1. Should Processing Continue After Plugin?

```
Plugin Outcome
├── BLOCKED → STOP
├── COMPLETED_BY_MIDDLEWARE → STOP
├── ERROR
│   ├── Plugin is critical → STOP
│   └── Plugin is non-critical → CONTINUE
├── MODIFIED → CONTINUE
└── ALLOWED → CONTINUE
```

### 2. Final Pipeline Outcome Determination

```
Had Critical Error?
├── YES → pipeline_outcome = ERROR
└── NO
    └── Outcome already final (BLOCKED/COMPLETED_BY_MIDDLEWARE/ERROR)?
        ├── YES → Keep current outcome
        └── NO
            └── Any stage modified content?
                ├── YES → pipeline_outcome = MODIFIED
                └── NO
                    └── Had Security Plugin?
                        ├── YES → pipeline_outcome = ALLOWED
                        └── NO → Keep as NO_SECURITY_EVALUATION
```

### 3. Audit Logging with Pipeline Outcomes

Audit plugins receive the raw `pipeline_outcome` and `had_security_plugin` values, allowing each formatter to interpret the results according to its specific requirements:

- **BLOCKED**: Security plugin explicitly denied the request
- **ERROR**: Critical plugin failure (treated as a security block)
- **ALLOWED**: Security plugins evaluated and allowed unchanged
- **MODIFIED**: Security plugins evaluated and modified content
- **COMPLETED_BY_MIDDLEWARE**: Middleware handled the request (check `had_security_plugin` for security evaluation)
- **NO_SECURITY_EVALUATION**: No security plugins were configured or ran

Each audit formatter can then decide how to represent these outcomes based on its use case (compliance, debugging, alerting, etc.).

### Middleware Outcomes

Middleware plugins operate before security plugins and can optimize or filter tool access for operational purposes (not security). They produce specific outcomes:

#### COMPLETED_BY_MIDDLEWARE
Occurs when middleware provides a complete response, typically when:
- A tool is hidden for context optimization (returns "Tool not available" error)
- A capability is filtered to reduce token usage
- Example: `tool_manager` in allowlist mode hiding non-allowed tools

```json
// Request: tools/call for hidden tool
// Middleware returns completed response with error
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "error": {
    "code": -32601,
    "message": "Tool 'dangerous_tool' is not available"
  }
}
// Pipeline outcome: COMPLETED_BY_MIDDLEWARE
// Processing stops, security plugins never see the request
```

#### MODIFIED (Middleware-only)
When only middleware acts and modifies content:
- Filtering tools from tools/list responses
- Removing sensitive resources from listings
- The content continues to security plugins (if any) after modification

```json
// Original tools/list response has 10 tools
// Middleware filters to 3 allowed tools
// Pipeline outcome: MODIFIED (if no security plugins)
// Or further evaluated by security plugins
```

#### NO_SECURITY_EVALUATION
This outcome currently serves dual purposes:
1. No security plugins were configured or ran
2. **No middleware made changes** (pass-through)

When middleware plugins are present but don't modify/complete:
- Request doesn't match middleware criteria
- Pipeline outcome remains NO_SECURITY_EVALUATION

**Note**: There is no separate `NO_MIDDLEWARE_EVALUATION` outcome. The `NO_SECURITY_EVALUATION` outcome indicates no security evaluation occurred, regardless of whether middleware was present.

### Audit Record Examples for Middleware

When middleware completes a request (e.g., hiding a tool), audit plugins capture the full context:

#### JSON Lines Format
```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "event_type": "REQUEST",
  "direction": "request",
  "server_name": "filesystem",
  "method": "tools/call",
  "id": "req-123",
  "params": {
    "name": "delete_all",
    "arguments": {}
  },
  "pipeline_outcome": "completed_by_middleware",
  "completed_by": "ToolManagerPlugin",
  "had_security_plugin": false,
  "pipeline": {
    "outcome": "completed_by_middleware",
    "total_time_ms": 0.45,
    "stages": [
      {
        "plugin": "ToolManagerPlugin",
        "plugin_type": "middleware",
        "outcome": "completed_by_middleware",
        "time_ms": 0.35,
        "reason": "Tool not in allowlist"
      }
    ]
  },
  "status": "blocked",
  "message": "Tool 'delete_all' is not available"
}
```

#### Human-Readable Line Format
```
2024-01-15 10:30:45 | REQUEST | filesystem | tools/call | req-123 | COMPLETED_BY_MIDDLEWARE | ToolManagerPlugin | Tool 'delete_all' not available (hidden by middleware)
```

Key differences from security blocks:
- `pipeline_outcome`: `"completed_by_middleware"` (not `"blocked"`)
- `completed_by`: Shows which middleware plugin handled it
- `status`: Still shows `"blocked"` for backward compatibility with monitoring
- `message`: User-friendly error message (not security-generic)
- Processing stops before security evaluation

## Content Clearing Rules

### When Content Gets Cleared

Content (`input_content`, `output_content`) and reasons are cleared from pipeline stages when:

1. **During Processing**: `capture_content` is set to `False` when:
   - Any SecurityPlugin returns `allowed = False` (blocked)
   - Any SecurityPlugin returns `modified_content` (redacted/modified)

2. **After Processing**: If `capture_content = False`:
   - All stage `input_content` → `None`
   - All stage `output_content` → `None`
   - All stage reasons → Generic like `"[allowed]"`, `"[blocked]"`, `"[error]"`
   - Content hashes are KEPT for lineage tracking

### Security Rationale
This prevents sensitive data (that triggered blocks or was redacted) from appearing in logs.

## Critical vs Non-Critical Plugin Handling

### Plugin Criticality Defaults
- **All plugins** default to `critical = True` (fail closed)
- Set `critical: false` explicitly to allow fail-open behavior for specific plugins

### Exception Handling Based on Criticality

When a plugin throws an exception:

```python
except Exception as e:
    outcome = StageOutcome.ERROR
    if plugin.is_critical():
        had_critical_error = True
        # Log as error
        # Stop processing after this stage
    else:
        # Log as warning  
        # Continue processing to next plugin
```

**Important**: Criticality ONLY affects exception handling. It does NOT affect security decisions (`allowed = False` always stops processing regardless of criticality).

## Reason Handling

### Individual Plugin Reasons
Each plugin can provide a custom reason in its `PluginResult`. These are preserved in each `PipelineStage.result.reason`.

### Pipeline-Level Reason (for audit logging)
As of v0.1.0, all plugin reasons are concatenated with ` | ` separator in the `BaseAuditingPlugin._combine_pipeline_reasons()` method, with each reason prefixed by the plugin name in brackets:

```python
# In BaseAuditingPlugin class
def _combine_pipeline_reasons(self, pipeline: ProcessingPipeline, modified_stage: Optional['PipelineStage']) -> str:
    """Combine reasons from all pipeline stages into a single string for logging."""
    # Collect all non-empty reasons from pipeline stages in execution order
    reasons = []
    for stage in pipeline.stages:
        if stage.result and stage.result.reason:
            # Include plugin name with each reason for better traceability
            reason_with_plugin = f"[{stage.plugin_name}] {stage.result.reason}"
            reasons.append(reason_with_plugin)
    
    # If we have plugin reasons, concatenate them with pipe separator
    if reasons:
        return " | ".join(reasons)
    
    # Fallback to generic pipeline outcome if no plugin reasons available
    return pipeline.pipeline_outcome.value
```

**Example**: `"[Tool Manager] Tool 'read_file' is in allowlist | [Basic PII Filter] No PII detected | [Basic Secrets Filter] No secrets detected"`

### Reason Clearing
When `capture_content = False`, reasons are replaced with generic values (still prefixed with plugin name):
- `"[plugin_name] [allowed]"` for ALLOWED stages
- `"[plugin_name] [blocked]"` for BLOCKED stages  
- `"[plugin_name] [error]"` for ERROR stages
- `"[plugin_name] [modified]"` for MODIFIED stages

---

### Edge Cases and Special Behaviors

#### Edge Case 1: Plugin Contract Violations

The system enforces strict contracts for each plugin type:

**MiddlewarePlugin Setting `allowed` (Contract Violation)**:
- When a MiddlewarePlugin sets `allowed` to any non-None value
- Raises `ValueError`: "Middleware plugin {name} illegally set allowed={value}"
- The exception is caught and creates `StageOutcome.ERROR`
- Processing stops if the plugin is critical (follows normal error handling)
- **Result**: MiddlewarePlugin cannot make security decisions - attempting to do so is an error

**SecurityPlugin Not Setting `allowed` (Contract Violation)**:
- When a SecurityPlugin returns `allowed=None`
- Raises `ValueError`: "Security plugin {name} failed to make a security decision"
- The exception is caught and creates `StageOutcome.ERROR`
- Processing stops if the plugin is critical (default for SecurityPlugin)
- **Result**: SecurityPlugin MUST make explicit security decisions

**Design Principle**: Only SecurityPlugin instances can make security decisions. MiddlewarePlugin instances that need to block requests must be implemented as SecurityPlugin subclasses.

#### Edge Case 2: Multiple Security Plugin Outcomes

When multiple security plugins evaluate a message, the pipeline outcome follows these rules:

1. **First `allowed=False` wins**: Processing stops immediately at the first security plugin that blocks
2. **All must allow**: For the message to proceed, ALL security plugins must return `allowed=True`
3. **Modification doesn't stop processing**: If a security plugin modifies content but returns `allowed=True`, processing continues with the modified content
4. **Pipeline outcome priority**: `BLOCKED` > `ALLOWED` > `NO_SECURITY_EVALUATION`

#### Edge Case 3: Pipeline Outcome Timing (Immediate vs Deferred)

Pipeline outcomes are set at different times based on their impact on processing flow:

**Immediate Outcomes** (set as soon as they occur):
1. **`BLOCKED`** - Set by `add_stage()` when any security plugin blocks (stops processing immediately)
2. **`COMPLETED_BY_MIDDLEWARE`** - Set by `add_stage()` when middleware completes response (stops processing immediately)  
3. **`ALLOWED`** - Set when first security plugin allows AND outcome is still `NO_SECURITY_EVALUATION` (processing continues but outcome is locked in)

**Deferred Outcomes** (set during finalization):
4. **`ERROR`** - Set during finalization if `had_critical_error` flag is true
   - Why deferred: Non-critical errors allow processing to continue, so we need the full context to know if any critical error occurred
5. **`MODIFIED`** - Set during finalization if any stage has `StageOutcome.MODIFIED`
   - Why deferred: Lower priority than BLOCKED/COMPLETED/ERROR, so we wait to see if a higher-priority outcome occurs
6. **`NO_SECURITY_EVALUATION`** - Remains if no security plugins ran and no other outcome was set

The finalization logic checks outcomes in priority order: ERROR > BLOCKED/COMPLETED (already set) > MODIFIED > ALLOWED (already set) > NO_SECURITY_EVALUATION

**Important**: Once set to `BLOCKED` or `COMPLETED_BY_MIDDLEWARE`, the outcome doesn't change (processing stops). `MODIFIED` is set during finalization and takes precedence over `ALLOWED`.

#### Edge Case 4: Content Clearing Triggers

Content gets cleared (`capture_content = False`) when:

1. **Security block**: Any SecurityPlugin returns `allowed=False`
2. **Security modification**: Any SecurityPlugin returns `modified_content`
3. **NOT for middleware modifications**: Middleware modifications don't trigger content clearing

This is a security feature - any security action (block or redact) triggers clearing to prevent sensitive data from appearing in logs.

---

### NO_SECURITY_EVALUATION Behavior

When the final pipeline outcome is `NO_SECURITY_EVALUATION`:
- **The message is allowed to proceed** (not blocked)
- **Audit logs show no security evaluation occurred** via the outcome value
- **Rationale**: Users may be working with dev data or debugging middleware without needing security enforcement

This is intentional - the proxy does not block by default when no security plugins are configured.

## Example Scenarios

### Scenario 1: Single Security Plugin - Allowed

**Setup**: One security plugin (Tool Manager) evaluates a request

```python
# Plugin execution
ToolManagerPlugin.process_request() → PluginResult(allowed=True, reason="Tool 'read_file' is in allowlist")
```

**Pipeline Result**:
- `pipeline_outcome = ALLOWED`
- `had_security_plugin = True`
- `capture_content = True` (no security action taken)
- Pipeline reason: `"[Tool Manager] Tool 'read_file' is in allowlist"`
- Content is fully captured in stages

### Scenario 2: Single Security Plugin - Blocked

**Setup**: One security plugin blocks a request

```python
# Plugin execution
ToolManagerPlugin.process_request() → PluginResult(allowed=False, reason="Tool 'dangerous_tool' not in allowlist")
```

**Pipeline Result**:
- `pipeline_outcome = BLOCKED`
- `had_security_plugin = True`
- `capture_content = False` (security block occurred)
- `blocked_at_stage = "Tool Manager"`
- Processing stops immediately
- Content cleared from stages, reasons become `"[Tool Manager] [blocked]"`
- Pipeline reason (after clearing): `"[Tool Manager] [blocked]"`

### Scenario 3: Multiple Security Plugins - Mixed Decisions

**Setup**: Three security plugins evaluate in sequence

```python
# Plugin execution order
1. ToolManagerPlugin.process_request() → PluginResult(allowed=True, reason="Tool 'read_file' is in allowlist")
2. BasicPIIFilterPlugin.process_request() → PluginResult(allowed=True, modified_content=..., reason="PII detected and redacted: email")
3. BasicSecretsFilterPlugin.process_request() → PluginResult(allowed=True, reason="No secrets detected")
```

**Pipeline Result**:
- `pipeline_outcome = MODIFIED` (content was modified)
- `had_security_plugin = True`
- `capture_content = False` (PII was modified - security action)
- All content cleared from stages
- All reasons become generic: `"[Tool Manager] [allowed]"`, `"[Basic PII Filter] [modified]"`, `"[Basic Secrets Filter] [allowed]"`
- Pipeline reason (concatenated after clearing): `"[Tool Manager] [allowed] | [Basic PII Filter] [modified] | [Basic Secrets Filter] [allowed]"`

### Scenario 4: Critical Plugin Error

**Setup**: A critical security plugin throws an exception

```python
# Plugin execution
CriticalSecurityPlugin.process_request() → throws Exception("Database connection failed")
# Plugin has critical=True (default for SecurityPlugin)
```

**Pipeline Result**:
- `pipeline_outcome = ERROR`
- `had_security_plugin = True`
- `had_critical_error = True`
- Processing stops immediately
- Stage created with `outcome = ERROR`, `error_type = "Exception"`
- Pipeline reason: `"[CriticalSecurityPlugin] Database connection failed"`

### Scenario 5: Non-Critical Plugin Error Continues

**Setup**: A non-critical plugin fails, then a critical plugin succeeds

```python
# Plugin execution order
1. NonCriticalMonitoringPlugin.process_request() → throws Exception("Metrics service unavailable")
   # Plugin has critical=False
2. CriticalSecurityPlugin.process_request() → PluginResult(allowed=True, reason="Request authorized")
```

**Pipeline Result**:
- `pipeline_outcome = ALLOWED` (not ERROR because non-critical)
- `had_security_plugin = True`
- Two stages created:
  - Stage 1: `outcome = ERROR`, plugin continues
  - Stage 2: `outcome = ALLOWED`
- Pipeline reason: `"[NonCriticalMonitoringPlugin] Metrics service unavailable | [CriticalSecurityPlugin] Request authorized"`
- Warning logged for non-critical failure, processing continued

### Scenario 6: Middleware Completion

**Setup**: Middleware provides a complete response

```python
# Plugin execution order
1. SecurityPlugin.process_request() → PluginResult(allowed=True, reason="Allowed")
2. CacheMiddleware.process_request() → PluginResult(
       allowed=None,
       completed_response=MCPResponse(...),
       reason="Served from cache"
   )
```

**Pipeline Result**:
- `pipeline_outcome = COMPLETED_BY_MIDDLEWARE`
- `had_security_plugin = True` (security evaluated before completion)
- `completed_by = "CacheMiddleware"`
- Processing stops after CacheMiddleware
- `final_content = completed_response`
- Pipeline reason: `"[SecurityPlugin] Allowed | [CacheMiddleware] Served from cache"`

### Scenario 7: No Security Plugins

**Setup**: Only middleware plugins configured

```python
# Plugin execution order
1. LoggingMiddleware.process_request() → PluginResult(allowed=None, reason="Request logged")
2. MetricsMiddleware.process_request() → PluginResult(allowed=None, reason="Metrics recorded")
```

**Pipeline Result**:
- `pipeline_outcome = NO_SECURITY_EVALUATION`
- `had_security_plugin = False` (no security decision made)
- Request proceeds to upstream
- Pipeline reason: `"[LoggingMiddleware] Request logged | [MetricsMiddleware] Metrics recorded"`
- Content fully captured (no security actions)

### Scenario 8: Security Plugin Modifies Content

**Setup**: Security plugin redacts sensitive data

```python
# Plugin execution
BasicSecretsFilterPlugin.process_response() → PluginResult(
    allowed=True,
    modified_content=MCPResponse(...),  # with secrets redacted
    reason="3 secrets redacted"
)
```

**Pipeline Result**:
- `pipeline_outcome = MODIFIED` (content was modified)
- `had_security_plugin = True`
- `capture_content = False` (security modification occurred)
- Content cleared from all stages
- Reason becomes generic: `"[Basic Secrets Filter] [modified]"`
- `final_content` contains the redacted version

### Scenario 9: Middleware Sets allowed=False (Contract Violation)

**Setup**: A middleware plugin incorrectly tries to make a security decision

```python
# Plugin execution
LoggingMiddleware.process_request() → PluginResult(allowed=False, reason="Suspicious activity")
# Note: LoggingMiddleware extends MiddlewarePlugin, not SecurityPlugin
# This raises ValueError during contract enforcement
```

**Pipeline Result**:
- `ValueError` raised: "Middleware plugin LoggingMiddleware illegally set allowed=False"
- Exception caught, creates `StageOutcome.ERROR`
- If middleware is critical → `pipeline_outcome = ERROR`, processing stops
- If middleware is non-critical → Warning logged, processing continues
- Stage created with `outcome = ERROR`, `error_type = "ValueError"`
- Pipeline reason includes error: `"[LoggingMiddleware] Middleware plugin LoggingMiddleware illegally set allowed=False"`

**Key Point**: Contract violations are errors. Middleware plugins attempting to make security decisions indicates incorrect plugin type usage.

---

## Summary

### Key Takeaways

1. **Security Plugins are Special**: Only SecurityPlugin subclasses can make security decisions that block messages
2. **Pipeline Outcomes are Final**: BLOCKED and COMPLETED_BY_MIDDLEWARE stop processing immediately
3. **Content Clearing is Security-Driven**: Only security actions (block/modify) trigger content clearing
4. **Criticality Affects Errors Only**: Critical vs non-critical only matters for exception handling, not for security decisions
5. **NO_SECURITY_EVALUATION is Permissive**: Messages pass through when no security plugins are configured
6. **Reasons are Concatenated**: All plugin reasons are joined with ` | ` for audit logging
7. **Contract Violations are Errors**: Both plugin types must follow their contracts or face exceptions


### Implementation Notes

This document reflects the actual behavior as of Gatekit v0.1.0. The implementation is in:
- `/gatekit/plugins/manager.py`: Main pipeline processing logic
- `/gatekit/plugins/interfaces.py`: Plugin base classes and enum definitions (StageOutcome, PipelineOutcome)
- `/gatekit/plugins/auditing/base.py`: Reason extraction and audit logging

---
