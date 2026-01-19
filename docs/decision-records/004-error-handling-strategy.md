# ADR-004: Error Handling Strategy

## Context

Gatekit operates as a security proxy in the MCP ecosystem, requiring robust error handling for:

1. **Protocol Compliance**: Must return proper JSON-RPC 2.0 error responses
2. **Security Isolation**: Errors from upstream servers must be sanitized
3. **Debugging Support**: Developers need actionable error information
4. **Reliability**: System should gracefully handle various failure modes
5. **Monitoring**: Operations teams need visibility into error patterns

The error handling strategy will impact security, usability, and maintainability throughout the system.

## Decision

We will implement a **structured error handling strategy** using JSON-RPC 2.0 error codes with Gatekit-specific extensions:

```python
# Gatekit-specific error codes (see gatekit/protocol/errors.py)
# Uses IntEnum for type safety
class MCPErrorCodes(IntEnum):
    # Standard JSON-RPC error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Gatekit-specific error codes (-32099 to -32000 per JSON-RPC spec)
    SECURITY_VIOLATION = -32000
    CONFIGURATION_ERROR = -32001
    PLUGIN_LOADING_ERROR = -32002
    PERMISSION_ERROR = -32003
    UPSTREAM_UNAVAILABLE = -32004
    AUDITING_FAILURE = -32005
```

### Key Principles

1. **Protocol Compliance**: All errors follow JSON-RPC 2.0 specification
2. **Security-First**: Never leak sensitive information in error messages
3. **Structured Data**: Consistent error format with codes and details
4. **Contextual Information**: Include relevant context for debugging
5. **Graceful Degradation**: System continues operating despite errors

## Alternatives Considered

### Alternative 1: Simple Exception Propagation
```python
# Just let Python exceptions bubble up
try:
    result = await server.request(message)
except Exception as e:
    raise e  # Raw exception propagation
```
- **Pros**: Simple, preserves full error details
- **Cons**: Breaks JSON-RPC compliance, potential security leaks

### Alternative 2: Generic Error Responses
```python
# Always return same generic error
def handle_error(e):
    return {"error": {"code": -1, "message": "An error occurred"}}
```
- **Pros**: Maximum security, simple implementation
- **Cons**: Poor debugging experience, no actionable information

### Alternative 3: HTTP-Style Status Codes
```python
# Use HTTP status codes instead of JSON-RPC
class GatekitError:
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    INTERNAL_ERROR = 500
```
- **Pros**: Familiar to web developers
- **Cons**: Doesn't follow JSON-RPC 2.0 specification

## Consequences

### Positive
- **Protocol Compliance**: Follows JSON-RPC 2.0 error specification exactly
- **Security**: Controlled error information prevents information leakage
- **Debugging**: Structured errors with codes enable targeted debugging
- **Monitoring**: Error codes allow for meaningful metrics and alerting
- **Client Support**: Clients can handle errors programmatically

### Negative
- **Complexity**: More code to handle error categorization and formatting
- **Maintenance**: Error codes must be documented and maintained
- **Potential Over-Engineering**: May be more structure than needed initially

## Implementation Notes

### Error Response Format
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32003,
    "message": "Validation failed",
    "data": {
      "details": "Request missing required 'method' field",
      "request_id": "req_123",
      "timestamp": "YYYY-MM-DDTHH:MM:SSZ"
    }
  },
  "id": null
}
```

### Error Response Creation
```python
# Error responses are created via create_error_response() helper
# Error handling is distributed throughout the codebase rather than centralized
def create_error_response(
    request_id: Optional[Union[str, int]],
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> MCPResponse:
    """Create a JSON-RPC error response."""
    error_dict = {"code": code, "message": message}
    if data is not None:
        error_dict["data"] = data
    return MCPResponse(jsonrpc="2.0", id=request_id, error=error_dict)

# Example usage (always use named parameters for clarity):
response = create_error_response(
    request_id=request.id,
    code=MCPErrorCodes.INVALID_PARAMS,
    message="Tool call missing required 'name' parameter",
)
```

### Security Considerations
- **Information Filtering**: Remove stack traces and internal paths from client responses
- **Error Logging**: Full error details logged internally for debugging
- **Rate Limiting**: Prevent error-based enumeration attacks
- **Context Sanitization**: Remove sensitive data from error context

### Error Categories

#### Transport Errors
- Connection failures to upstream servers
- Timeout errors
- Protocol-level communication issues

#### Validation Errors
- Malformed JSON-RPC requests
- Missing required fields
- Invalid parameter types

#### Security Errors
- Blocked requests due to security policies
- Authentication failures
- Authorization violations

#### Internal Errors
- Unexpected system failures
- Configuration errors
- Resource exhaustion

### Monitoring and Observability

Error tracking is handled through:
- **Auditing plugins**: Log all requests/responses including errors (see `gatekit/plugins/auditing/`)
- **Processing pipeline**: Full visibility into plugin decisions and transformations
- **Structured logging**: Errors logged with context for debugging

Note: Prometheus-style metrics are not currently implemented but could be added as a future enhancement.

## Review

This decision will be reviewed when:
- JSON-RPC specification changes significantly
- Security requirements become more stringent
- Debugging needs change substantially
- Monitoring requirements evolve
