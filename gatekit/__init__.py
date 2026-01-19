"""An extensible MCP Gateway for Developers with Terminal User Interface"""

from ._version import __version__

# Main exports
from .config.loader import ConfigLoader
from .config.models import ProxyConfig
from .plugins.manager import PluginManager

__all__ = [
    "ConfigLoader",
    "ProxyConfig",
    "PluginManager",
    "__version__",
]
