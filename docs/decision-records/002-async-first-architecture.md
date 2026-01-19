# ADR-002: Async-First Architecture

## Context

Gatekit acts as a proxy between MCP clients and servers, requiring:

1. Concurrent handling of multiple client connections
2. Non-blocking I/O operations for server communication
3. Efficient resource utilization
4. Responsive user experience
5. Integration with Python ecosystem's async patterns

The choice of synchronous vs asynchronous architecture will fundamentally impact performance, scalability, and development patterns throughout the codebase.

## Decision

We will implement an **async-first architecture** using Python's `asyncio` throughout the entire codebase:

```python
# All core operations are async
async def handle_request(self, request: dict) -> dict:
    # Validate request
    validated = await self.validate_request(request)
    
    # Forward to server
    response = await self.transport.send_and_receive(validated)
    
    # Apply security filters
    filtered = await self.filter_response(response)
    
    return filtered
```

### Key Design Principles

1. **Async by Default**: All I/O operations use `async`/`await`
2. **No Blocking Calls**: Avoid any synchronous I/O in the main path
3. **Concurrent Operations**: Use `asyncio.gather()` for parallel tasks
4. **Proper Resource Management**: Use `async with` for cleanup
5. **Error Propagation**: Async-aware exception handling
6. **Concurrent Request Handling**: Support multiple simultaneous requests with proper correlation

## Alternatives Considered

### Alternative 1: Synchronous with Threading
```python
import threading
import queue

class SyncHandler:
    def handle_request(self, request):
        with ThreadPoolExecutor() as executor:
            future = executor.submit(self.process, request)
            return future.result()
```
- **Pros**: Simpler mental model, familiar patterns
- **Cons**: GIL limitations, thread overhead, complex resource management

### Alternative 2: Mixed Sync/Async Architecture
```python
# Sync public API with async internals
def handle_request(self, request):
    return asyncio.run(self._async_handle_request(request))
```
- **Pros**: Familiar external API
- **Cons**: Inefficient event loop management, harder to compose

### Alternative 3: Callback-Based Architecture
```python
def handle_request(self, request, callback):
    self.transport.send(request, lambda response: callback(self.filter(response)))
```
- **Pros**: No async/await complexity
- **Cons**: Callback hell, harder error handling, less readable

## Consequences

### Positive
- **High Concurrency**: Handle many simultaneous connections efficiently
- **Responsive**: Non-blocking operations keep system responsive
- **Scalable**: Better resource utilization than threading
- **Modern**: Aligns with Python ecosystem trends
- **Testable**: Easy to mock async operations for testing
- **Composable**: Async functions compose naturally

### Negative
- **Learning Curve**: Team must understand async/await patterns
- **Debugging Complexity**: Async stack traces can be harder to follow
- **Dependency Constraints**: Must use async-compatible libraries
- **Test Complexity**: Tests require async test frameworks

## Implementation Notes

### Current Implementation
- All transport operations are async: `connect()`, `send_message()`, `receive_message()`, `disconnect()`
- Request handling pipeline is fully async
- Test suite uses `pytest-asyncio` for async test support
- Error handling preserves async context
- Note: Validation operations are synchronous (fast, CPU-bound) while I/O operations are async

### Async Patterns Used
```python
# Concurrent operations
async def validate_parallel(self, requests):
    tasks = [self.validate_single(req) for req in requests]
    return await asyncio.gather(*tasks)

# Resource management
async def with_connection(self):
    async with self.transport.connect() as conn:
        yield conn

# Timeout handling
async def send_with_timeout(self, message, timeout=30):
    return await asyncio.wait_for(
        self.transport.send(message), 
        timeout=timeout
    )
```

### Performance Considerations
- Use `asyncio.gather()` for parallel operations
- Implement connection pooling for HTTP transports
- Consider `asyncio.Queue` for buffering
- Monitor event loop health in production

## Review

This decision will be reviewed when:
- Performance bottlenecks indicate async overhead
- Team productivity suffers from async complexity
- Python ecosystem significantly changes async patterns
- Integration requirements favor synchronous patterns
