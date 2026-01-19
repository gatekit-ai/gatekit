"""Transport-specific error types for better error handling and observability.

This module defines a hierarchy of transport errors that provide clear
semantics for different failure modes.
"""

from typing import Optional, Any


class TransportError(Exception):
    """Base class for all transport-related errors.

    This provides a common base for catching all transport errors
    while still allowing specific error types to be handled individually.
    """

    def __init__(self, message: str, cause: Optional[Exception] = None):
        """Initialize transport error.

        Args:
            message: Human-readable error message
            cause: Original exception that caused this error (if any)
        """
        super().__init__(message)
        self.cause = cause
        # Preserve the original exception chain
        if cause:
            self.__cause__ = cause


class TransportConnectionError(TransportError):
    """Raised when connection-related operations fail.

    This includes connection establishment, disconnection,
    and connection state issues.
    """

    pass


class TransportDisconnectedError(TransportConnectionError):
    """Raised when attempting operations on a disconnected transport."""

    def __init__(self, operation: str = "operation"):
        """Initialize disconnected error.

        Args:
            operation: The operation that was attempted
        """
        super().__init__(f"Cannot perform {operation}: transport is not connected")
        self.operation = operation


class TransportTimeoutError(TransportError):
    """Raised when a transport operation times out.

    This wraps asyncio.TimeoutError with transport-specific context.
    """

    def __init__(self, message: str, timeout: float, operation: str = "operation"):
        """Initialize timeout error.

        Args:
            message: Human-readable error message
            timeout: The timeout value in seconds
            operation: The operation that timed out
        """
        super().__init__(message)
        self.timeout = timeout
        self.operation = operation


class TransportProtocolError(TransportError):
    """Raised when protocol-level errors occur.

    This includes JSON parsing errors, invalid messages,
    and protocol violations.
    """

    def __init__(self, message: str, data: Optional[Any] = None):
        """Initialize protocol error.

        Args:
            message: Human-readable error message
            data: The data that caused the error (if any)
        """
        super().__init__(message)
        self.data = data


class TransportValidationError(TransportProtocolError):
    """Raised when message validation fails."""

    pass


class TransportRequestError(TransportError):
    """Raised for request-specific errors.

    This includes duplicate IDs, concurrent request limits,
    and request tracking issues.
    """

    def __init__(self, message: str, request_id: Optional[Any] = None):
        """Initialize request error.

        Args:
            message: Human-readable error message
            request_id: The request ID involved (if any)
        """
        super().__init__(message)
        self.request_id = request_id


class TransportDuplicateRequestError(TransportRequestError):
    """Raised when a duplicate request ID is detected."""

    def __init__(self, request_id: Any):
        """Initialize duplicate request error.

        Args:
            request_id: The duplicate request ID
        """
        super().__init__(f"Request ID {request_id} is already in use", request_id)


class TransportConcurrencyLimitError(TransportRequestError):
    """Raised when concurrent request limit is exceeded."""

    def __init__(self, limit: int, current: int):
        """Initialize concurrency limit error.

        Args:
            limit: The maximum allowed concurrent requests
            current: The current number of concurrent requests
        """
        super().__init__(
            f"Maximum concurrent requests ({limit}) exceeded (current: {current})"
        )
        self.limit = limit
        self.current = current


class TransportProcessError(TransportError):
    """Raised for subprocess-related errors."""

    def __init__(self, message: str, exit_code: Optional[int] = None):
        """Initialize process error.

        Args:
            message: Human-readable error message
            exit_code: Process exit code (if available)
        """
        super().__init__(message)
        self.exit_code = exit_code
