"""Core proxy server for Gatekit MCP gateway.

This package contains the main proxy server implementation that integrates
with the plugin system and handles MCP client-server communications.
"""

from .server import MCPProxy

__all__ = ["MCPProxy"]
