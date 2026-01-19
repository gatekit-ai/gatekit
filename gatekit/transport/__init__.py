# filepath: /Users/dbright/mcp/gatekit/gatekit/transport/__init__.py
"""Transport layer for MCP communication.

This module provides transport abstractions and implementations for communicating
with MCP servers. Currently supports stdio-based transport for process communication.
"""

from .base import Transport
from .stdio import StdioTransport

__all__ = ["Transport", "StdioTransport"]
