# ADR-001: Transport Layer Architecture

## Context

Gatekit needs to communicate with MCP servers using different transport mechanisms. The MCP protocol supports multiple transports (stdio, SSE/HTTP, WebSocket), and we need a flexible architecture that:

1. Supports multiple transport types without duplicating protocol logic
2. Allows easy addition of new transports in the future
3. Maintains clean separation between transport concerns and protocol concerns
4. Provides consistent error handling across all transports

## Decision

We will implement an abstract `Transport` interface with concrete implementations for each transport type:

```python
# Abstract base class (simplified view - see gatekit/transport/base.py for full interface)
class Transport(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def send_message(self, message: MCPRequest) -> None: ...

    @abstractmethod
    async def receive_message(self) -> MCPResponse: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    # Additional methods in actual implementation:
    # - send_notification(), get_next_notification() for MCP notifications
    # - send_and_receive() for request/response correlation (ADR-013)
    # - is_connected() for connection state checking

# Concrete implementations
class StdioTransport(Transport): ...
class HttpTransport(Transport): ...  # Future
class WebSocketTransport(Transport): ...  # Future
```

### Key Design Principles

1. **Transport Abstraction**: Protocol logic is transport-agnostic
2. **Async-First**: All transport operations are asynchronous
3. **Clean Interface**: Core contract with connect/send_message/receive_message/disconnect operations
4. **Error Propagation**: Transport errors bubble up as specific exceptions (see `gatekit/transport/errors.py`)
5. **Resource Management**: Proper cleanup through async context managers
6. **Request Correlation**: Support for concurrent request handling via `send_and_receive()` (see ADR-013)

## Alternatives Considered

### Alternative 1: Transport-Specific Protocol Handlers
```python
class StdioProtocolHandler:
    def handle_request(self, request): ...
    
class HttpProtocolHandler:
    def handle_request(self, request): ...
```
- **Pros**: Simple, direct implementation
- **Cons**: Code duplication, harder to maintain protocol consistency

### Alternative 2: Single Transport Class with Type Parameter
```python
class Transport:
    def __init__(self, transport_type: str): ...
```
- **Pros**: Single class to maintain
- **Cons**: Complex internal branching, violates single responsibility

### Alternative 3: Plugin-Based Architecture
```python
class TransportRegistry:
    def register_transport(self, name: str, transport_class): ...
```
- **Pros**: Maximum flexibility, runtime registration
- **Cons**: Over-engineering for current needs, more complex

## Consequences

### Positive
- Clean separation of concerns between transport and protocol layers
- Easy to add new transport types (HTTP, WebSocket, etc.)
- Consistent error handling across all transports
- Testable transport implementations in isolation
- Type-safe interfaces with proper async support

### Negative
- Additional abstraction layer adds some complexity
- Need to maintain consistency across multiple implementations
- Slightly more code than monolithic approach

## Implementation Notes

Current implementation includes:
- `gatekit/transport/base.py`: Abstract `Transport` interface with 8 abstract methods
- `gatekit/transport/stdio.py`: Stdio transport implementation with request correlation
- `gatekit/transport/errors.py`: Transport-specific error hierarchy
- Comprehensive test coverage for both abstract interface and concrete implementation
- Integration tests validating transport behavior

Future transports (HTTP, WebSocket) will follow the same pattern, implementing the `Transport` interface while handling transport-specific details internally.

## Review

This decision will be reviewed when:
- Adding the second transport implementation (HTTP or WebSocket)
- Performance requirements change significantly
- MCP protocol transport requirements evolve
