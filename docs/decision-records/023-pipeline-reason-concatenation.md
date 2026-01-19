# ADR-023: Pipeline Reason Concatenation for Audit Logging

## Context

With the introduction of ProcessingPipeline, Gatekit now supports multiple plugins processing each message (requests, responses, notifications). Each plugin can provide its own custom reason in the PluginResult:

```python
# Individual plugin results, each with custom reasons
PluginResult(allowed=True, reason="Tool 'read_file' is in allowlist for server 'filesystem'")
PluginResult(allowed=True, reason="No PII detected")  
PluginResult(allowed=True, reason="No secrets detected")
```

However, the auditing system needs to extract **one single reason** for the pipeline-level logging. The previous implementation used a complex lambda expression with priority-based reason selection:

```python
"reason": (lambda: (
    (modified_stage.result.reason if modified_stage and modified_stage.result and modified_stage.result.reason else None)
    or (next((s.result.reason for s in pipeline.stages if s.plugin_name == pipeline.blocked_at_stage and s.result and s.result.reason), None))
    or (next((s.result.reason for s in pipeline.stages if s.result and s.result.reason), None))  # Any stage with a reason
    or pipeline.pipeline_outcome.value
))(),
```

This approach had several problems:

### Issues with Previous Approach

1. **Unpredictable Results**: The "first custom reason found" was essentially random, determined by plugin execution order
2. **Information Loss**: Only one plugin's reason was preserved, losing visibility into other security decisions  
3. **Poor User Experience**: Users would see generic reasons like "No PII detected" even when more specific policy decisions were made
4. **Hard to Maintain**: The complex lambda was difficult to understand and modify
5. **Inconsistent Semantics**: What does "the pipeline reason" mean when multiple plugins provide different reasons?

### Example Problems

```
# What users would see (random based on execution order):
"No PII detected"  # Even though tool was explicitly allowed by allowlist

# What they should see:
"[tool_manager] Tool 'read_file' is in allowlist | [pii] No PII detected | [secrets] No secrets detected"
```

## Decision

**We will concatenate all plugin reasons using a pipe separator (` | `) for pipeline-level audit logging.**

### Implementation

Replace the complex reason selection logic with simple concatenation:

```python
def _combine_pipeline_reasons(self, pipeline: ProcessingPipeline) -> str:
    """Combine reasons from all pipeline stages into a single string for logging."""

    # Collect all non-empty reasons from pipeline stages in execution order
    # Each reason is prefixed with the plugin name in brackets
    reasons = []
    for stage in pipeline.stages:
        if stage.result and stage.result.reason:
            reasons.append(f"[{stage.plugin_name}] {stage.result.reason}")

    # If we have plugin reasons, concatenate them with pipe separator
    if reasons:
        return " | ".join(reasons)

    # Fallback to generic pipeline outcome if no plugin reasons available
    return pipeline.pipeline_outcome.value
```

### Separator Choice

We chose ` | ` (pipe with spaces) because:
- **Visual Clarity**: More distinct than commas in log analysis
- **Technical Convention**: Common separator in logs and technical contexts
- **Programmatic Parsing**: Easy to split on ` | ` if needed for structured analysis
- **Readability**: Clear separation without being overly verbose

## Consequences

### Positive

1. **Complete Transparency**: Users see all security decisions made during processing
2. **Deterministic**: Same pipeline configuration produces same reason strings
3. **No Information Loss**: Every plugin's custom reason is preserved  
4. **Simple to Understand**: Clear concatenation logic that users can predict
5. **Better Debugging**: Full visibility into security pipeline processing
6. **Maintainable**: Simple, readable code replacing complex lambda

### Negative

1. **Longer Log Lines**: Concatenated reasons can be verbose
2. **Some Redundancy**: May include generic "No X detected" messages alongside specific decisions
3. **Not Optimized**: Doesn't prioritize more important reasons over generic ones

### Examples

```
# Single plugin decision:
"[tool_manager] Tool 'read_file' is in allowlist for server 'filesystem'"

# Multiple plugins, all clean:
"[tool_manager] Tool 'read_file' is in allowlist for server 'filesystem' | [pii] No PII detected | [secrets] No secrets detected"

# Content modification with multiple checks:
"[pii] PII detected and redacted from request: ssn | [tool_manager] Tool allowed | [secrets] No secrets detected"

# Blocked request:
"[tool_manager] Tool 'dangerous_tool' is not in allowlist for server 'filesystem'"
```

## Future Considerations

This is intended as a **v0.1.0 solution** that prioritizes transparency and correctness over optimization. Future versions may implement:

1. **Reason Prioritization**: Filter out generic reasons, prioritize content modifications and specific policy decisions
2. **Structured Logging**: Separate fields for different types of reasons (security decisions, content modifications, etc.)
3. **Configurable Verbosity**: Allow users to choose between concise vs. verbose reason reporting
4. **Reason Categories**: Group reasons by importance (critical, informational, etc.)

## Alternatives Considered

1. **Priority-Based Selection**: Continue with single reason but improve priority logic
   - Rejected: Still loses information and requires complex priority rules
   
2. **Structured JSON Reasons**: Include all reasons as structured data
   - Rejected: Too complex for v0.1.0, breaks existing log parsing

3. **Most Important Reason Only**: Select blocking > modification > policy > generic
   - Rejected: Information loss, complex to define "importance" rules

4. **Summary + Detail**: Short pipeline reason + detailed stage list
   - Rejected: Adds complexity without clear benefit for initial release

## Notes

- This change affects all auditing plugins (JSON Lines, CSV, Human Readable)
- Existing log parsers may need updates to handle longer reason strings
- The pipe separator can be easily changed if needed without affecting the core logic
- Individual stage reasons remain available in the ProcessingPipeline for any advanced analysis needs