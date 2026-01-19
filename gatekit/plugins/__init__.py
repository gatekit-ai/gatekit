"""Plugin system for Gatekit MCP gateway."""

from .interfaces import (
    PluginInterface,
    PathResolvablePlugin,
    MiddlewarePlugin,
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    PipelineStage,
    ProcessingPipeline,
)
from .manager import PluginManager

__all__ = [
    "PluginInterface",
    "PathResolvablePlugin",
    "MiddlewarePlugin",
    "SecurityPlugin",
    "AuditingPlugin",
    "PluginResult",
    "PipelineStage",
    "ProcessingPipeline",
    "PluginManager",
]
