"""Utility helpers for exercising the gateway pipeline in integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

from gatekit.config.loader import ConfigLoader
from gatekit.config.models import ProxyConfig
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPNotification, MCPRequest, MCPResponse

from tests.utils.golden import GoldenScenario, load_golden_config

DEFAULT_UPSTREAM_COMMAND = [
    "python",
    "-c",
    "import sys; sys.stdout.write('gatekit test upstream')",
]


PluginRef = Union[Tuple[str, str], Tuple[str, str, str]]


def compose_proxy_config(
    plugin_refs: Sequence[PluginRef],
    *,
    upstream_name: str = "test-upstream",
    transport_command: Optional[Sequence[str]] = None,
    suppress_upstream_errors: bool = True,
) -> Dict[str, Any]:
    """Build a proxy config for harness tests using golden plugin data.

    Each entry in ``plugin_refs`` is either ``(<handler>, <scenario>)`` for
    global plugins or ``(<handler>, <scenario>, <scope>)`` for server-scoped
    plugins (e.g. ``("tool_manager", "typical", "my-upstream")``).

    Example:

    >>> compose_proxy_config([
    ...     ("basic_pii_filter", "edge"),
    ...     ("tool_manager", "typical", "test-upstream"),
    ... ])
    {"proxy": {...}, "plugins": {...}}
    """

    command = list(transport_command or DEFAULT_UPSTREAM_COMMAND)
    upstream_entry: Dict[str, Any] = {
        "name": upstream_name,
        "transport": "stdio",
        "command": command,
    }
    if suppress_upstream_errors:
        upstream_entry["restart_on_failure"] = False
        upstream_entry["max_restart_attempts"] = 0

    proxy_section: Dict[str, Any] = {
        "transport": "stdio",
        "upstreams": [upstream_entry],
        "timeouts": {"connection_timeout": 5, "request_timeout": 5},
    }

    plugin_sections: MutableMapping[str, Dict[str, List[Dict[str, Any]]]] = {}
    for ref in plugin_refs:
        if len(ref) == 3:
            handler, scenario, scope = ref  # type: ignore[misc]
        else:
            handler, scenario = ref  # type: ignore[misc]
            scope = "_global"
        golden = load_golden_config(handler, scenario)
        category = golden.category
        section = plugin_sections.setdefault(category, {})
        section.setdefault(scope, []).append(
            {"handler": golden.handler, "config": golden.config}
        )

    plugins_block = {
        cat: sections for cat, sections in plugin_sections.items() if sections
    }

    config: Dict[str, Any] = {"proxy": proxy_section}
    if plugins_block:
        config["plugins"] = plugins_block

    return config


@dataclass
class GatewayHarness:
    """In-process wrapper around PluginManager for behavior tests."""

    plugin_manager: PluginManager
    default_server: str
    _loaded: bool = False

    @classmethod
    def from_config_dict(
        cls,
        config_dict: Dict[str, Any],
        *,
        config_directory: Path,
        server_name: Optional[str] = None,
    ) -> "GatewayHarness":
        loader = ConfigLoader()
        proxy_config = loader.load_from_dict(config_dict, config_directory)
        return cls.from_proxy_config(
            proxy_config,
            config_directory=config_directory,
            server_name=server_name,
        )

    @classmethod
    def from_proxy_config(
        cls,
        proxy_config: ProxyConfig,
        *,
        config_directory: Optional[Path] = None,
        server_name: Optional[str] = None,
    ) -> "GatewayHarness":
        plugin_dict = proxy_config.plugins.to_dict() if proxy_config.plugins else {}
        manager = PluginManager(plugin_dict, config_directory)
        upstream_name = proxy_config.upstreams[0].name if proxy_config.upstreams else "test-upstream"
        return cls(manager, server_name or upstream_name)

    async def _ensure_loaded(self) -> None:
        if not self._loaded:
            await self.plugin_manager.load_plugins()
            self._loaded = True

    async def process_request(
        self, request: MCPRequest, server_name: Optional[str] = None
    ):  # -> ProcessingPipeline
        await self._ensure_loaded()
        return await self.plugin_manager.process_request(
            request, server_name or self.default_server
        )

    async def process_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        server_name: Optional[str] = None,
    ):
        await self._ensure_loaded()
        return await self.plugin_manager.process_response(
            request, response, server_name or self.default_server
        )

    async def process_notification(
        self, notification: MCPNotification, server_name: Optional[str] = None
    ):
        await self._ensure_loaded()
        return await self.plugin_manager.process_notification(
            notification, server_name or self.default_server
        )

    async def log_request(
        self,
        request: MCPRequest,
        pipeline,
        server_name: Optional[str] = None,
    ) -> None:
        await self._ensure_loaded()
        await self.plugin_manager.log_request(
            request, pipeline, server_name or self.default_server
        )

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        pipeline,
        server_name: Optional[str] = None,
    ) -> None:
        await self._ensure_loaded()
        await self.plugin_manager.log_response(
            request, response, pipeline, server_name or self.default_server
        )

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline,
        server_name: Optional[str] = None,
    ) -> None:
        await self._ensure_loaded()
        await self.plugin_manager.log_notification(
            notification, pipeline, server_name or self.default_server
        )


__all__ = ["GatewayHarness", "compose_proxy_config", "load_golden_config"]
