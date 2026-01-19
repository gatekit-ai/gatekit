"""Auditing plugins for Gatekit MCP gateway.

This package contains auditing plugins that log request and response
information for security monitoring, compliance, and debugging.

Plugins are discovered dynamically by scanning Python files in this directory
for HANDLERS variables. All plugins (built-in and user-created) are treated
equally through the discovery system.
"""

from .base import BaseAuditingPlugin

__all__ = [
    "BaseAuditingPlugin",
]
