# ADR-016: Audit Log Content Clearing

## Status

Accepted

## Context

Gatekit's audit logging captures MCP traffic for debugging, compliance, and forensic analysis. When security plugins detect sensitive content (PII, secrets, prompt injection attempts), they block or redact it. A decision is needed about what appears in audit logs when this happens.

The challenge: audit logs need to provide visibility into what happened, but logging the sensitive content that triggered a security action defeats the purpose of the security plugin.

## Decision

When any security plugin blocks or modifies content, Gatekit clears the actual content from all pipeline stages before audit logging. Only metadata is preserved.

### What Gets Cleared

- `input_content` and `output_content` for all pipeline stages → `None`
- Plugin reasons → Generic placeholders (`[allowed]`, `[blocked]`, `[modified]`, `[error]`)

### What Gets Preserved

- Pipeline outcome (BLOCKED, MODIFIED, ALLOWED, etc.)
- Which plugin took action (`blocked_at_stage`, `completed_by`)
- Processing timestamps and durations
- Content hashes (for lineage tracking without exposing content)
- Plugin names and execution order

### Trigger Conditions

Content clearing is triggered when any SecurityPlugin:
- Returns `allowed = False` (blocked the request)
- Returns `modified_content` (redacted or transformed the content)

Middleware modifications do NOT trigger content clearing—only security plugin actions.

## Options Considered

### 1. Log Everything ❌

Log full content regardless of security decisions.

**Problems:**
- Sensitive data that triggered blocks ends up in logs
- Enables log replay attacks—attacker exfiltrates logs to extract secrets/PII
- Defeats the purpose of security plugins

### 2. Log Nothing When Security Acts ❌

Clear all audit data when security plugins act.

**Problems:**
- Loses visibility into security events
- Cannot detect attack patterns or tune security rules
- Compliance requirements often mandate security event logging

### 3. Encrypt Sensitive Content ❌

Encrypt flagged content in logs with a separate key.

**Problems:**
- Key management complexity
- Encrypted content is still exfiltratable
- Doesn't address the fundamental question of whether to retain the data

### 4. User-Configurable Retention ❌

Let users choose what to log via configuration.

**Problems:**
- Easy to misconfigure
- Default matters—wrong default causes breaches
- Complexity for marginal benefit

### 5. Metadata-Only Logging ✅

Clear content but preserve metadata about what happened.

**Benefits:**
- Security events are visible (who, when, which plugin, what outcome)
- Sensitive content never reaches logs
- Content hashes enable lineage tracking without exposure
- Simple, secure default with no configuration needed

## Consequences

### Benefits

1. **Log replay attacks mitigated**: Audit logs don't contain the sensitive data that triggered security actions. An attacker with log access cannot extract secrets or PII.

2. **Security visibility preserved**: Operators can see that security events occurred, which plugins acted, and the outcomes—without seeing the sensitive content.

3. **Compliance-friendly**: Logs demonstrate security controls are active without creating a secondary exposure vector.

4. **Simple mental model**: Security action → content cleared. No configuration or decision-making required.

### Trade-offs

1. **Reduced forensic detail**: When investigating a blocked request, operators see that it was blocked but not exactly what triggered it. This is intentional—if the content was sensitive enough to block, it shouldn't be in logs.

2. **Reason messages cleared**: Plugin reasons are replaced with generic placeholders. Detailed reasons might leak information about what was detected.

3. **All-or-nothing**: If any security plugin acts, all content is cleared—including from plugins that allowed the request. This prevents partial leakage through other stages.

## Implementation

Content clearing is implemented in the ProcessingPipeline class:

```python
# In ProcessingPipeline
capture_content: bool = True  # Set to False when security acts

# Triggers (in plugin manager)
if isinstance(plugin, SecurityPlugin):
    if result.allowed == False or result.modified_content:
        pipeline.capture_content = False

# After processing (in pipeline finalization)
if not pipeline.capture_content:
    for stage in pipeline.stages:
        stage.input_content = None
        stage.output_content = None
        stage.result.reason = f"[{stage.outcome.value}]"
```

See [Content Clearing Rules](../security-model.md#content-clearing-rules) in the Security Model for the complete specification.

## Related Decisions

- **ADR-006**: Critical Auditing Plugin Failure Modes (audit plugin error handling)
- **ADR-011**: Response Filtering Fail-Closed Strategy (security-first defaults)
- **ADR-022**: Unified Plugin Result (PluginResult structure)
