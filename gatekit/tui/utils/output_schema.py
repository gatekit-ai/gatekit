"""Output schema discovery and data reading utilities.

This module provides infrastructure for plugins to declare output display
capabilities via get_output_schema(). The TUI uses this to add dynamic
columns (like token counts) to the server list.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, Union

from gatekit.plugins.interfaces import PluginInterface
from gatekit.plugins.manager import PluginManager
from gatekit.utils.paths import expand_user_path

logger = logging.getLogger(__name__)


def humanize_number(value: Union[int, float]) -> str:
    """Format a number in human-readable form (e.g., 1.2K, 3.4M).

    Args:
        value: Numeric value to format

    Returns:
        Human-readable string representation
    """
    if value < 0:
        return f"-{humanize_number(-value)}"
    if value < 1000:
        return str(int(value))
    elif value < 1_000_000:
        num = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{num}K"
    elif value < 1_000_000_000:
        num = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{num}M"
    else:
        num = f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{num}G"


# Value formatters registry
def raw_number(value: Union[int, float]) -> str:
    """Format a number as a plain integer string.

    Truncates floats to int so animation intermediates don't show decimals.
    """
    return str(int(value))


VALUE_FORMATTERS: Dict[str, Callable[[Union[int, float]], str]] = {
    "humanized_number": humanize_number,
    "raw": raw_number,
}


class ServerColumnDefinition:
    """Definition of a single dynamic column for the server list."""

    def __init__(
        self,
        handler_name: str,
        plugin_class: Type[PluginInterface],
        key: str,
        column_id: str,
        value_format: str = "raw",
        label: str = "",
        tooltip: Optional[str] = None,
        width: int = 7,
        context_menu: Optional[List[Dict[str, str]]] = None,
        state_file_key: Optional[str] = None,
    ):
        """Initialize column definition.

        Args:
            handler_name: Plugin handler name (e.g., "token_usage")
            plugin_class: The plugin class (needed for parse_server_values)
            key: Column key within the plugin (e.g., "input", "output")
            column_id: Unique column ID: "{handler_name}__{key}"
            value_format: Format type for values (e.g., "humanized_number")
            label: Prefix label shown before value (e.g., "↑")
            tooltip: Optional hover text for the cell
            width: Total cell width in characters including label
            context_menu: List of context menu entries from the plugin schema
            state_file_key: Config key for state file path (default: "state_file")
        """
        self.handler_name = handler_name
        self.plugin_class = plugin_class
        self.key = key
        self.column_id = column_id
        self.value_format = value_format
        self.label = label
        self.tooltip = tooltip
        self.width = width
        self.context_menu = context_menu or []
        self.state_file_key = state_file_key or "state_file"
        self._formatter = VALUE_FORMATTERS.get(value_format, str)

    def format_value(self, value: Union[int, float]) -> str:
        """Format a single value for display.

        Args:
            value: Numeric value to format

        Returns:
            Formatted string like "3.4K"
        """
        return self._formatter(value)


class OutputSchemaDiscovery:
    """Discovers plugins with output display capabilities."""

    @classmethod
    def discover_server_columns(cls) -> List[ServerColumnDefinition]:
        """Find all plugins that provide server_columns output schemas.

        Returns:
            List of ServerColumnDefinition for plugins with server columns
        """
        columns = []
        seen_column_ids: set = set()
        pm = PluginManager({})

        # Discover all plugin handlers across categories
        for category in ["security", "middleware", "auditing"]:
            handlers = pm._discover_handlers(category)

            for handler_name, plugin_class in handlers.items():
                output_schema = plugin_class.get_output_schema()
                if not output_schema:
                    continue

                # Support new "server_columns" (list) format
                col_list = output_schema.get("server_columns")
                if not isinstance(col_list, list) or not col_list:
                    continue

                # Validate handler name doesn't contain separator
                if "__" in handler_name:
                    logger.warning(
                        "Plugin handler name '%s' contains '__' separator, skipping",
                        handler_name,
                    )
                    continue

                shared_state_file_key = output_schema.get("state_file_key", "state_file")
                shared_context_menu = output_schema.get("context_menu", [])

                # Validate context menu entries
                valid_menu = []
                for entry in shared_context_menu:
                    if not isinstance(entry, dict):
                        logger.warning(
                            "Plugin '%s': context_menu entry is not a dict, skipping",
                            handler_name,
                        )
                        continue
                    method = str(entry.get("method", ""))
                    label = str(entry.get("label", ""))
                    if not method or not method.isidentifier() or method.startswith("_"):
                        logger.warning(
                            "Plugin '%s': invalid context_menu method '%s', skipping entry",
                            handler_name, method,
                        )
                        continue
                    if not label:
                        logger.warning(
                            "Plugin '%s': context_menu entry missing label, skipping",
                            handler_name,
                        )
                        continue
                    # Validate scope if present
                    scope = entry.get("scope")
                    if scope is not None and scope not in ("server", "all_servers"):
                        logger.warning(
                            "Plugin '%s': context_menu entry has invalid scope '%s', skipping",
                            handler_name, scope,
                        )
                        continue
                    valid_menu.append(entry)

                for col_config in col_list:
                    if not isinstance(col_config, dict):
                        logger.warning(
                            "Plugin '%s': server_columns entry is not a dict, skipping",
                            handler_name,
                        )
                        continue
                    key = col_config.get("key")
                    value_format = col_config.get("value_format")

                    # Required fields
                    if not key or not value_format:
                        logger.warning(
                            "Plugin '%s': server_columns entry missing required "
                            "field 'key' or 'value_format', skipping",
                            handler_name,
                        )
                        continue

                    # Validate key doesn't contain separator
                    if "__" in key:
                        logger.warning(
                            "Plugin '%s': column key '%s' contains '__', skipping",
                            handler_name, key,
                        )
                        continue

                    column_id = f"{handler_name}__{key}"

                    # Check for duplicate column IDs
                    if column_id in seen_column_ids:
                        logger.warning(
                            "Duplicate column_id '%s', skipping", column_id,
                        )
                        continue
                    seen_column_ids.add(column_id)

                    # Validate value_format
                    if value_format not in VALUE_FORMATTERS:
                        logger.warning(
                            "Plugin '%s': unrecognized value_format '%s', "
                            "falling back to str",
                            handler_name, value_format,
                        )

                    # Clamp width
                    raw_width = col_config.get("width", 7)
                    if not isinstance(raw_width, int):
                        raw_width = 7
                    if raw_width < 3 or raw_width > 20:
                        logger.warning(
                            "Plugin '%s': width %d out of range 3-20, clamping",
                            handler_name, raw_width,
                        )
                        raw_width = max(3, min(20, raw_width))

                    column = ServerColumnDefinition(
                        handler_name=handler_name,
                        plugin_class=plugin_class,
                        key=key,
                        column_id=column_id,
                        value_format=value_format,
                        label=col_config.get("label", ""),
                        tooltip=col_config.get("tooltip"),
                        width=raw_width,
                        context_menu=valid_menu,
                        state_file_key=shared_state_file_key,
                    )
                    columns.append(column)

        return columns


class ServerColumnReader:
    """Reads server column data from plugin state files.

    This class is designed to work with the ConfigEditorScreen to read
    column data from plugin state files and update the server list display.
    """

    def __init__(
        self,
        columns: List[ServerColumnDefinition],
        config: Any,  # ProxyConfig
        config_directory: Optional[Path] = None,
    ):
        """Initialize reader with columns and config.

        Args:
            columns: List of column definitions
            config: The ProxyConfig object
            config_directory: Directory for resolving relative paths
        """
        self.columns = columns
        self.config = config
        self.config_directory = config_directory
        self._columns_by_id: Dict[str, ServerColumnDefinition] = {
            col.column_id: col for col in columns
        }
        # Group columns by handler for efficient state file reads
        self._columns_by_handler: Dict[str, List[ServerColumnDefinition]] = {}
        for col in columns:
            self._columns_by_handler.setdefault(col.handler_name, []).append(col)
        self._last_error: Optional[str] = None

    def _get_plugin_config(
        self, handler_name: str, server_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Get plugin configuration from the ProxyConfig.

        Follows the same resolution semantics as the gateway's
        ``_resolve_plugins_for_upstream``:
        1. If *server_name* is given, check per-server scope first.
           A match there **replaces** the global entry (no fallback).
           A disabled per-server entry returns ``None``.
        2. Fall through to ``_global`` scope.

        Args:
            handler_name: Plugin handler name
            server_name: Optional server name for per-server resolution

        Returns:
            Plugin config dict or None
        """
        if not self.config or not self.config.plugins:
            return None

        for category in ["security", "middleware", "auditing"]:
            category_dict = getattr(self.config.plugins, category, {})
            if not isinstance(category_dict, dict):
                continue

            # Check per-server scope first (if server_name provided)
            if server_name:
                server_plugins = category_dict.get(server_name, [])
                if isinstance(server_plugins, list):
                    for plugin in server_plugins:
                        if (
                            hasattr(plugin, "handler")
                            and plugin.handler == handler_name
                        ):
                            # Per-server override found — return config
                            # if enabled, None if disabled (no fallback)
                            if hasattr(plugin, "enabled") and not plugin.enabled:
                                logger.debug(
                                    "_get_plugin_config: per-server config disabled "
                                    "handler=%s server=%s",
                                    handler_name, server_name,
                                )
                                return None
                            result = getattr(plugin, "config", {})
                            logger.debug(
                                "_get_plugin_config: per-server config resolved "
                                "handler=%s server=%s config_keys=%s",
                                handler_name, server_name,
                                list(result.keys()) if isinstance(result, dict) else type(result).__name__,
                            )
                            return result

            # Fall through to _global
            global_plugins = category_dict.get("_global", [])
            if isinstance(global_plugins, list):
                for plugin in global_plugins:
                    if (
                        hasattr(plugin, "handler")
                        and plugin.handler == handler_name
                    ):
                        if hasattr(plugin, "enabled") and not plugin.enabled:
                            logger.debug(
                                "_get_plugin_config: global config disabled "
                                "handler=%s server=%s",
                                handler_name, server_name,
                            )
                            return None
                        result = getattr(plugin, "config", {})
                        logger.debug(
                            "_get_plugin_config: global config resolved "
                            "handler=%s server=%s config_keys=%s",
                            handler_name, server_name,
                            list(result.keys()) if isinstance(result, dict) else type(result).__name__,
                        )
                        return result

        logger.debug(
            "_get_plugin_config: no config found handler=%s server=%s",
            handler_name, server_name,
        )
        return None

    def _resolve_state_file_path(
        self, column: ServerColumnDefinition, plugin_config: Dict[str, Any]
    ) -> Optional[Path]:
        """Resolve the state file path from plugin config.

        Uses the same path resolution as the gateway (~ expansion, env vars,
        config-relative paths) to ensure TUI reads the same file.

        Args:
            column: The column definition
            plugin_config: Plugin configuration dict

        Returns:
            Resolved Path or None if not configured
        """
        state_file = plugin_config.get(column.state_file_key)
        if not state_file:
            # Use default from schema
            schema = column.plugin_class.get_config_schema()
            default = schema.get("properties", {}).get(column.state_file_key, {}).get("default")
            if default:
                state_file = default
            else:
                return None

        # Expand environment variables and ~ (same as gateway)
        state_file = os.path.expandvars(state_file)
        path = expand_user_path(state_file)

        # Handle relative paths (config-relative)
        if not path.is_absolute() and self.config_directory:
            path = self.config_directory / path

        return path

    def _read_state_file(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read and parse a state file.

        Args:
            path: Path to the state file

        Returns:
            Parsed state dict or None on error
        """
        try:
            if not path.exists():
                self._last_error = "State file not found"
                logger.debug(
                    "_read_state_file: file not found path=%s", path,
                )
                return None

            # Log file metadata before reading
            try:
                st = path.stat()
                logger.debug(
                    "_read_state_file: reading path=%s size=%d mtime=%.1f",
                    path, st.st_size, st.st_mtime,
                )
            except OSError:
                pass

            content = path.read_text(encoding="utf-8")
            data = json.loads(content)

            # Log parsed content summary
            server_keys = list(data.get("servers", {}).keys()) if isinstance(data, dict) else []
            logger.debug(
                "_read_state_file: parsed path=%s server_count=%d servers=%s",
                path, len(server_keys), server_keys,
            )

            return data

        except json.JSONDecodeError as e:
            self._last_error = f"JSON parse error: {e}"
            logger.debug("_read_state_file: JSON parse error path=%s: %s", path, e)
            return None
        except (OSError, IOError) as e:
            self._last_error = f"Read error: {e}"
            logger.debug("_read_state_file: read error path=%s: %s", path, e)
            return None

    def resolve_all_state_file_paths(
        self, handler_name: str
    ) -> List[Path]:
        """Resolve all unique state file paths for a handler across servers.

        Iterates all configured upstreams, resolves each server's plugin
        config, and returns de-duplicated paths.  Useful for global actions
        that must touch every state file (e.g. "reset all servers").

        Args:
            handler_name: Plugin handler name

        Returns:
            List of unique resolved Paths (order is stable, global-first)
        """
        handler_columns = self._columns_by_handler.get(handler_name)
        if not handler_columns or not self.config or not self.config.upstreams:
            return []

        col = handler_columns[0]
        seen: set = set()
        paths: List[Path] = []
        for upstream in self.config.upstreams:
            plugin_config = self._get_plugin_config(handler_name, upstream.name)
            if plugin_config is None:
                continue
            path = self._resolve_state_file_path(col, plugin_config)
            if path:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    paths.append(path)
        return paths

    def read_column_values(
        self, handler_name: str
    ) -> Dict[str, Optional[Dict[str, Union[int, float]]]]:
        """Read column values for all servers, grouped by handler.

        Resolves per-server plugin configs so each server may point at a
        different state file.  Unique files are read only once.

        Args:
            handler_name: The plugin handler name

        Returns:
            Dict mapping server_name to either:
            - ``None``  — plugin is not configured/available for this server
            - ``{}``    — plugin is configured but has no data (e.g. after reset)
            - ``{key: value, ...}`` — current column values
        """
        handler_columns = self._columns_by_handler.get(handler_name)
        if not handler_columns:
            return {}

        col = handler_columns[0]
        plugin_class = col.plugin_class
        result: Dict[str, Optional[Dict[str, Union[int, float]]]] = {}

        if not self.config or not self.config.upstreams:
            return {}

        # Group servers by resolved state file path (read each unique file once)
        servers_by_path: Dict[Optional[Path], List[str]] = {}
        for upstream in self.config.upstreams:
            plugin_config = self._get_plugin_config(handler_name, upstream.name)
            if plugin_config is None:
                result[upstream.name] = None  # Plugin not configured
                continue
            path = self._resolve_state_file_path(col, plugin_config)
            # Resolve to absolute for reliable grouping
            if path:
                path = path.resolve()
            servers_by_path.setdefault(path, []).append(upstream.name)

        logger.debug(
            "read_column_values: handler=%s paths_resolved=%s",
            handler_name,
            {str(p): names for p, names in servers_by_path.items()},
        )

        for path, server_names in servers_by_path.items():
            if not path:
                for name in server_names:
                    result[name] = None  # No state file path
                continue
            state = self._read_state_file(path)
            if state is None:
                for name in server_names:
                    result[name] = None  # State file unreadable
                continue

            # Log which state file we read and what servers are in it
            logger.debug(
                "read_column_values: file=%s, servers_in_state=%s, querying=%s",
                path, list(state.get("servers", {}).keys()), server_names,
            )

            for name in server_names:
                try:
                    values = plugin_class.parse_server_values(state, name)
                    if not isinstance(values, dict):
                        logger.warning(
                            "Plugin '%s'.parse_server_values returned non-dict for '%s'",
                            handler_name, name,
                        )
                        values = {}
                    logger.debug(
                        "parse_server_values('%s', '%s') -> %s",
                        handler_name, name, values,
                    )
                    result[name] = values
                except Exception as e:
                    logger.warning(
                        "Plugin '%s'.parse_server_values failed for '%s' (file: %s): %s",
                        handler_name, name, path, e,
                    )
                    result[name] = {}

        return result

    @property
    def last_error(self) -> Optional[str]:
        """Get the last error message, if any."""
        return self._last_error

    @property
    def column_id(self) -> str:
        """Get the primary column ID (first column)."""
        return self.columns[0].column_id if self.columns else ""


__all__ = [
    "humanize_number",
    "VALUE_FORMATTERS",
    "ServerColumnDefinition",
    "OutputSchemaDiscovery",
    "ServerColumnReader",
]
