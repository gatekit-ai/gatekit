# filepath: /Users/dbright/mcp/gatekit/gatekit/transport/__init__.py
"""Transport layer for MCP communication.

This module provides transport abstractions and implementations for communicating
with MCP servers. Supports stdio-based transport for process communication and
HTTP-based transport for remote server communication.
"""

from .base import Transport
from .stdio import StdioTransport
from .http import StreamableHttpTransport

__all__ = ["Transport", "StdioTransport", "StreamableHttpTransport"]
