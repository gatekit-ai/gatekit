# ADR-003: Test-Driven Development Approach

## Context

Gatekit is a security-critical component that sits between MCP clients and servers. It must:

1. Reliably validate and filter potentially malicious requests
2. Maintain protocol compliance with MCP specifications
3. Handle edge cases and error conditions gracefully
4. Support future protocol evolution without regression
5. Provide confidence in security guarantees

Given the security-critical nature and the need for robust protocol handling, we need a development approach that ensures comprehensive testing and high code quality.

## Decision

We will follow a **Test-Driven Development (TDD)** approach throughout the project:

```python
# Example TDD cycle for message validation
class TestMessageValidation:
    @pytest.mark.asyncio
    async def test_valid_request_passes_validation(self):
        # Red: Write failing test first
        request = {"jsonrpc": "2.0", "method": "ping", "id": 1}
        validator = MessageValidator()

        result = validator.validate(request)  # Validation is synchronous
        assert result.is_valid
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_missing_jsonrpc_fails_validation(self):
        # Red: Write failing test
        request = {"method": "ping", "id": 1}  # Missing jsonrpc
        validator = MessageValidator()

        result = validator.validate(request)  # Validation is synchronous
        assert not result.is_valid
        assert "jsonrpc field required" in result.errors
```

### Key Principles

1. **Red-Green-Refactor Cycle**: Write test → Make it pass → Improve code
2. **Test First**: No production code without a failing test
3. **Comprehensive Coverage**: Test happy path, edge cases, and error conditions
4. **Fast Feedback**: Tests run quickly and provide immediate feedback
5. **Living Documentation**: Tests serve as executable specifications

## Alternatives Considered

### Alternative 1: Traditional Test-After Development
```python
# Write implementation first, then add tests
def implement_feature():
    # Build the feature
    pass

def test_feature():
    # Test the built feature
    pass
```
- **Pros**: Faster initial development, familiar approach
- **Cons**: Often leads to untestable code, missing edge cases, lower coverage

### Alternative 2: Behavior-Driven Development (BDD)
```python
# Feature: Message Validation
# Scenario: Valid message passes validation
# Given a valid JSON-RPC message
# When validation is performed
# Then the message should be accepted
```
- **Pros**: Business-readable specifications, stakeholder involvement
- **Cons**: Additional tooling complexity, overkill for technical components

### Alternative 3: Property-Based Testing Only
```python
@given(st.dictionaries(st.text(), st.text()))
def test_message_validation(message):
    # Generate random inputs and test properties
    result = validate(message)
    assert isinstance(result, ValidationResult)
```
- **Pros**: Discovers edge cases automatically
- **Cons**: Harder to understand failures, doesn't replace example-based tests

## Consequences

### Positive
- **High Confidence**: Comprehensive test coverage provides confidence in changes
- **Better Design**: TDD drives towards more testable, modular code
- **Regression Prevention**: Tests catch breaking changes immediately
- **Documentation**: Tests serve as living examples of how code should work
- **Faster Debugging**: Failing tests pinpoint exact issues
- **Refactoring Safety**: Can improve code structure without fear

### Negative
- **Initial Overhead**: Writing tests first slows initial development
- **Learning Curve**: Team must be disciplined about TDD practices
- **Test Maintenance**: Tests require ongoing maintenance as code evolves
- **Over-Testing Risk**: May write tests for trivial functionality

## Implementation Notes

### Current Test Structure
```
tests/
├── unit/                    # Fast, isolated unit tests
│   ├── test_plugin_manager.py
│   ├── test_config_loader.py
│   └── ...
├── integration/             # Component integration tests
│   ├── test_pii_integration.py
│   └── ...
├── validation/              # Manual validation scripts with third-party tools
│   └── test-files/
├── mocks/                   # Mock utilities
├── utils/                   # Test utilities
└── fixtures/                # Fixture definitions
```

### Testing Tools and Patterns
- **pytest**: Test framework with excellent async support
- **pytest-asyncio**: Async test execution (tests require `@pytest.mark.asyncio` decorator)
- **pytest-xdist**: Parallel test execution (`pytest tests/ -n auto`)
- **unittest.mock**: Mocking for isolation (standard library)
- **pytest-cov**: Test coverage reporting

### TDD Workflow
1. **Write failing test** describing desired behavior
2. **Run test** to confirm it fails for the right reason
3. **Write minimal code** to make test pass
4. **Run all tests** to ensure no regression
5. **Refactor** code and tests for clarity
6. **Repeat** for next requirement

### Example TDD Implementation
```python
# Red: Test for transport connection
async def test_stdio_transport_connects_successfully(self):
    transport = StdioTransport(command=["echo", "test"])
    await transport.connect()
    assert transport.is_connected

# Green: Minimal implementation
class StdioTransport:
    async def connect(self):
        self.process = await asyncio.create_subprocess_exec(...)
        self.is_connected = True

# Refactor: Improve error handling and resource management
class StdioTransport:
    async def connect(self):
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            self.is_connected = True
        except Exception as e:
            raise TransportConnectionError(f"Failed to connect: {e}")
```

## Review

This decision will be reviewed when:
- Development velocity significantly decreases due to test overhead
- Test maintenance burden becomes excessive
- Team composition changes significantly
- Project requirements shift away from security-critical operations
