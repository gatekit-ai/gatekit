# ADR-011: Response Filtering Exception Handling - Fail-Closed Strategy

**Note**: The fail-closed strategy applies to all plugins via the `critical` flag (default: `true`). See ADR-006 for the unified critical plugin failure modes.

## Context

When implementing tools/list response filtering (see ADR-010), we needed to decide how to handle unexpected exceptions that occur during response processing. This decision has significant implications for reliability.

Two main categories of errors can occur during response filtering:

1. **Expected malformed responses**: Missing fields, wrong data types, empty arrays
2. **Unexpected exceptions**: Programming errors, memory issues, unforeseen data structures

The key question was whether to "fail open" (allow potentially unfiltered responses through) or "fail closed" (block responses when filtering encounters unexpected errors).

### Security Context

Tool allowlist filtering is a security control that prevents information disclosure. If filtering fails:

- **Fail Open**: Unfiltered response may expose blocked tools to clients
- **Fail Closed**: Filtering failure blocks the entire response

### Use Cases Affected

1. **Development environments**: Filtering bugs should be debuggable
2. **Production environments**: Security controls must be reliable
3. **High-availability systems**: Service availability vs. security trade-offs
4. **Compliance environments**: Audit requirements for security control failures

## Decision

We will implement a **fail-closed strategy for unexpected exceptions** while gracefully handling expected malformed response scenarios.

```python
async def process_response(self, response: MCPResponse) -> PluginResult:
    try:
        # Handle expected malformed response cases gracefully
        if not response.result or "tools" not in response.result:
            return PluginResult(
                allowed=False,
                reason="Malformed tools/list response: missing tools field"
            )
        
        # Perform filtering logic
        filtered_tools = self._filter_tools_by_policy(response.result["tools"])
        return create_filtered_response(response, filtered_tools)
        
    except Exception as e:
        # FAIL CLOSED: Block response on unexpected exceptions
        return PluginResult(
            allowed=False,
            reason=f"Error filtering tools/list response: {str(e)}",
            metadata={"error": str(e)}
        )
```

### Exception Handling Strategy

| Error Type | Handling | Rationale |
|------------|----------|-----------|
| Missing `tools` field | Fail closed with specific error | Expected malformed response |
| `tools` not an array | Fail closed with specific error | Expected malformed response |
| Tool missing `name` field | Skip tool, continue filtering | Expected malformed tool object |
| Unexpected exception | Fail closed with generic error | Unexpected error - preserve security |

## Alternatives Considered

### Alternative 1: Fail-Open Strategy

```python
except Exception as e:
    # FAIL OPEN: Allow original response through
    logger.error(f"Filter error: {e}")
    return PluginResult(
        allowed=True,
        reason="Filtering failed, allowing original response"
    )
```

**Rejected because**:
- **Security vulnerability**: Blocked tools could be exposed during filter failures
- **Inconsistent policy enforcement**: Security controls become unreliable
- **Attack vector**: Attackers might trigger filter failures to bypass restrictions
- **Compliance risk**: Audit failures in regulated environments

### Alternative 2: Configurable Failure Mode

This alternative was actually **adopted** as the `critical` flag on all plugins:

```yaml
plugins:
  middleware:
    _global:
      - handler: "tool_manager"
        config:
          enabled: true
          priority: 50
          tools:
            - tool: "read_file"
          critical: true  # Default - fail-closed on errors
```

The `critical` flag (default: `true`) provides configurable fail-closed/fail-open behavior while defaulting to the secure option. See ADR-006 for details.

### Alternative 3: Graceful Degradation with Warnings

```python
except Exception as e:
    # Allow through with warning in response
    modified_response = add_warning_to_response(response, f"Filter error: {e}")
    return PluginResult(
        allowed=True,
        modified_content=modified_response,
        reason="Filtering failed, added warning"
    )
```

**Rejected because**:
- **Information disclosure**: Still exposes potentially blocked tools
- **Client confusion**: Clients may not understand warning semantics
- **Response modification complexity**: Need to modify response structure
- **Limited security value**: Warning doesn't prevent information exposure

### Alternative 4: Retry with Fallback

```python
except Exception as e:
    # Retry filtering once, then fail closed
    try:
        return self._retry_filtering(response)
    except Exception:
        return PluginResult(allowed=False, reason="Filter retry failed")
```

**Rejected because**:
- **Complexity**: Retry logic is complex and error-prone
- **Performance impact**: Doubles processing time on failures
- **Limited value**: Most exceptions are not transient
- **Still needs fail-closed fallback**: Doesn't eliminate the core decision

## Consequences

### Positive

- **Security-First**: Preserves security control integrity under all conditions
- **Predictable Behavior**: Consistent failure mode across all error scenarios
- **Audit Compliance**: Failed security controls are clearly logged and blocked
- **Attack Resistance**: Attackers cannot bypass filtering by triggering exceptions
- **Clear Error Messages**: Specific error reasons aid debugging

### Negative

- **Availability Impact**: Filter bugs can block legitimate tool discovery
- **Debugging Complexity**: Failed responses may be harder to troubleshoot
- **Development Friction**: Filter implementation bugs cause immediate failures
- **False Positives**: Legitimate responses blocked due to filter bugs

### Mitigation Strategies

1. **Comprehensive Testing**: Extensive test coverage for filtering logic
2. **Detailed Error Logging**: Include exception details for debugging
3. **Allow-All Escape Hatch**: Development mode to bypass filtering
4. **Monitoring**: Alert on filtering failure rates
5. **Graceful Expected Error Handling**: Handle known malformed response patterns

## Implementation Details

### Exception Handling Hierarchy

```python
async def process_response(self, response: MCPResponse) -> PluginResult:
    """Filter tools/list responses with fail-closed exception handling."""
    
    # Early validation for expected malformed responses
    if not self._is_tools_list_response(response):
        return PluginResult(
            allowed=True,
            reason="Not a tools/list response, no filtering needed"
        )
    
    try:
        # Validate response structure (expected errors)
        self._validate_tools_list_structure(response)
        
        # Perform filtering (unexpected errors caught below)
        filtered_tools = self._filter_tools_by_policy(response.result["tools"])
        
        # Create and return filtered response
        return self._create_filtered_response(response, filtered_tools)
        
    except ValidationError as e:
        # Expected malformed response - fail closed with specific reason
        return PluginResult(
            allowed=False,
            reason=f"Malformed tools/list response: {str(e)}",
            metadata={"error_type": "validation", "error": str(e)}
        )
        
    except Exception as e:
        # Unexpected exception - fail closed with generic reason
        self.logger.error(
            f"Unexpected error filtering tools/list response: {str(e)}",
            exc_info=True
        )
        return PluginResult(
            allowed=False,
            reason=f"Error filtering tools/list response: {str(e)}",
            metadata={"error_type": "unexpected", "error": str(e)}
        )
```

### Validation Helper Methods

```python
def _validate_tools_list_structure(self, response: MCPResponse) -> None:
    """Validate tools/list response structure, raise ValidationError if invalid."""
    if not response.result:
        raise ValidationError("Missing result field")
    
    if "tools" not in response.result:
        raise ValidationError("Missing tools field in result")
    
    tools_list = response.result["tools"]
    if not isinstance(tools_list, list):
        raise ValidationError("tools field is not an array")
```

### Error Monitoring

Error monitoring is handled through:
- **Auditing plugins**: Log all pipeline stages including errors
- **Processing pipeline**: Full visibility into plugin decisions via `ProcessingPipeline`
- **Structured logging**: Errors logged with context for debugging

Note: Prometheus-style metrics are not currently implemented.

This fail-closed strategy ensures that Gatekit's plugins remain reliable even when facing unexpected errors, while providing clear debugging information for resolution. The `critical` flag (see ADR-006) allows opt-out for development scenarios.
