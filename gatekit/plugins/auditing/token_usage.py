"""Token Usage Estimator plugin for Gatekit MCP gateway.

This plugin estimates token usage from MCP messages using tiktoken (cl100k_base encoding)
and provides per-server token counts for display in the TUI.

Features:
- Estimates tokens using tiktoken (~88% accuracy across models)
- Tracks input and output tokens separately, per tool
- Live counter display with manual reset via context menu in TUI
- CSV log for historical analysis (load into Excel, pivot by server/tool)
- Persists counters across gateway restarts via state file

See the Token Usage Estimator implementation plan for architecture details.
"""

import csv
import json
import logging
import os
import stat
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from filelock import FileLock, Timeout

from gatekit.plugins.interfaces import (
    AuditingPlugin,
    PathResolvablePlugin,
    ProcessingPipeline,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.utils.paths import resolve_config_path, expand_user_path, validate_output_path

logger = logging.getLogger(__name__)

# Maximum content size to tokenize (10MB) - prevents DoS
MAX_CONTENT_SIZE = 10 * 1024 * 1024

# CSV buffer settings
CSV_BUFFER_MAX_ROWS = 50
CSV_BUFFER_MAX_SECONDS = 5.0

# State file flush interval
STATE_FLUSH_INTERVAL = 1.0

# Pending request TTL (5 minutes)
PENDING_REQUEST_TTL = 300


class TokenUsagePlugin(AuditingPlugin, PathResolvablePlugin):
    """Token usage estimator plugin for tracking MCP message token counts.

    Estimates token usage using tiktoken and maintains per-server, per-tool
    counters that can be displayed in the TUI and reset manually.
    """

    # TUI Display Metadata
    DISPLAY_NAME = "Token Usage Estimator"
    DESCRIPTION = "Estimates and tracks token usage per server using tiktoken."

    # Type annotations
    _encoder: Any  # tiktoken.Encoding
    _counters: Dict[str, Dict[str, Dict[str, int]]]  # server -> tool -> {input, output}
    _pending_requests: Dict[str, Dict[str, Any]]  # request_id -> {tool_name, input_tokens, timestamp}
    _reset_id: int
    _reset_timestamp: str
    _csv_buffer: List[Dict[str, Any]]
    _last_csv_flush: float
    _last_state_flush: float
    _lock: threading.Lock
    _tiktoken_available: bool
    _started_at: str  # ISO timestamp for PID reuse detection

    # TTL for cleaning up dead PID entries (seconds)
    INSTANCE_TTL = 300

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        """Generate status description from plugin configuration."""
        if not config or not config.get("enabled", False):
            return "Disabled"
        output_file = config.get("output_file")
        return output_file if output_file else "No output file configured"

    @classmethod
    def get_status_file_path(cls, config: Dict[str, Any]) -> Optional[str]:
        """Return CSV file path if status represents an openable file."""
        if not config or not config.get("enabled", False):
            return None
        return config.get("output_file")

    @classmethod
    def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
        """Return actions with log viewing capability."""
        if config and config.get("enabled", False):
            output_file = config.get("output_file", "")
            try:
                if output_file and os.path.exists(output_file):
                    return ["View Logs", "Configure"]
            except (OSError, IOError):
                pass
            return ["Configure"]
        return ["Setup"]

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for Token Usage plugin configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/token-usage.json",
            "type": "object",
            "description": "Token usage estimator plugin configuration",
            "properties": {
                "output_file": {
                    "type": "string",
                    "description": "Path to CSV log file for historical analysis",
                    "default": "logs/token_usage.csv",
                    "minLength": 1,
                    "x-widget": "file-path",
                },
                "state_file": {
                    "type": "string",
                    "description": "State file for live counter display",
                    "default": "logs/token_usage_state.json",
                    "minLength": 1,
                    "x-widget": "file-path",
                },
                "flush_interval_seconds": {
                    "type": "number",
                    "description": "How often to flush state to disk (seconds)",
                    "default": 1.0,
                    "minimum": 0.1,
                    "maximum": 60.0,
                },
                "critical": {
                    "type": "boolean",
                    "description": "If true, plugin failures block MCP traffic. Defaults to false for token counting.",
                    "default": False,
                },
            },
            "required": ["output_file", "state_file"],
            "additionalProperties": False,
        }

    @classmethod
    def get_config_warnings(cls) -> List[str]:
        """Return warnings about missing tiktoken dependency."""
        import sys

        try:
            import tiktoken  # noqa: F401
            return []
        except Exception:
            if sys.platform == "win32":
                return [
                    "tiktoken is not installed on Windows to avoid WDAC conflicts. "
                    "Token estimates use a less accurate heuristic. "
                    "See docs/reference/plugins/token_usage.md for details."
                ]
            return [
                "tiktoken not found — using heuristic estimation. "
                "Install tiktoken for better accuracy: pip install tiktoken"
            ]

    @classmethod
    def get_output_schema(cls) -> Optional[Dict[str, Any]]:
        """Return output display schema for TUI server columns."""
        return {
            "server_columns": [
                {
                    "key": "input",
                    "label": "↑",
                    "value_format": "humanized_number",
                    "tooltip": "Input tokens (server responses into LLM)",
                    "width": 8,
                },
                {
                    "key": "output",
                    "label": "↓",
                    "value_format": "humanized_number",
                    "tooltip": "Output tokens (tool call requests from LLM)",
                    "width": 8,
                },
            ],
            "state_file_key": "state_file",
            "context_menu": [
                {
                    "label": "Reset '{server_name}'",
                    "method": "reset_counters",
                    "scope": "server",
                    "confirm_title": "Reset token counters for '{server_name}'?",
                    "confirm_message": "This will reset token counters for this server only. This cannot be undone.",
                },
                {
                    "label": "Reset all servers",
                    "method": "reset_counters",
                    "scope": "all_servers",
                    "confirm_title": "Reset all token counters?",
                    "confirm_message": "This will reset token counters for all servers. This cannot be undone.",
                },
            ],
        }

    @classmethod
    def parse_server_values(cls, state_data: Dict[str, Any], server_name: str) -> Dict[str, int]:
        """Parse state file data to extract per-server column values.

        Aggregates counters across all instances for the requested server.

        Args:
            state_data: Parsed JSON content of the state file.
            server_name: Name of the server to extract values for.

        Returns:
            Dict mapping column key to value, e.g. {"input": 150, "output": 320}.
        """
        total_input = 0
        total_output = 0
        found = False

        instances = state_data.get("instances", {})
        for instance_data in instances.values():
            servers = instance_data.get("servers", {})
            server_data = servers.get(server_name, {})
            if server_data is not None:
                tools = server_data.get("tools", {})
                if tools or server_name in servers:
                    found = True
                total_input += sum(t.get("input", 0) for t in tools.values())
                total_output += sum(t.get("output", 0) for t in tools.values())

        # Fallback: legacy top-level servers format (pre-instances migration)
        if not found:
            legacy_servers = state_data.get("servers", {})
            server_data = legacy_servers.get(server_name, {})
            if server_data:
                tools = server_data.get("tools", {})
                found = True
                total_input = sum(t.get("input", 0) for t in tools.values())
                total_output = sum(t.get("output", 0) for t in tools.values())
            elif server_name in legacy_servers:
                found = True

        if not found:
            return {}
        return {"input": total_input, "output": total_output}

    @classmethod
    def reset_counters(cls, state_file_path: Path, server_name: Optional[str] = None) -> str:
        """Reset token counters by incrementing reset IDs in the state file.

        Args:
            state_file_path: Path to the state file.
            server_name: If None, reset all servers. If specified, reset only that server.

        Returns:
            Human-readable confirmation message.

        Raises:
            RuntimeError: If the reset operation fails.
        """
        import json as _json
        from filelock import FileLock, Timeout

        try:
            lock_path = str(state_file_path) + ".lock"
            lock = FileLock(lock_path, timeout=2)

            with lock:
                current_state = {}
                if state_file_path.exists():
                    try:
                        content = state_file_path.read_text(encoding="utf-8")
                        current_state = _json.loads(content)
                    except Exception:
                        current_state = {}  # Start fresh if unreadable

                timestamp = datetime.utcnow().isoformat() + "Z"
                instances = current_state.get("instances", {})

                # Clean up dead PID entries while we hold the lock
                live_instances = {}
                for pid_str, inst_data in instances.items():
                    try:
                        pid = int(pid_str)
                    except (ValueError, TypeError):
                        continue
                    if cls._is_pid_alive(pid):
                        live_instances[pid_str] = inst_data
                    else:
                        # Fall back to TTL check
                        last_update = inst_data.get("last_update", "")
                        if last_update:
                            try:
                                lu_time = datetime.fromisoformat(last_update.rstrip("Z"))
                                age = (datetime.utcnow() - lu_time).total_seconds()
                                if age <= cls.INSTANCE_TTL:
                                    live_instances[pid_str] = inst_data
                            except (ValueError, TypeError):
                                pass

                if server_name is None:
                    # Global reset: zero all instances' server entries
                    current_reset_id = current_state.get("reset_id", 0)
                    zeroed_instances = {}
                    for pid_str, inst_data in live_instances.items():
                        zeroed_inst = dict(inst_data)
                        zeroed_inst["servers"] = {
                            name: {"tools": {}}
                            for name in inst_data.get("servers", {})
                        }
                        zeroed_instances[pid_str] = zeroed_inst

                    new_state = {
                        "reset_id": current_reset_id + 1,
                        "reset_timestamp": timestamp,
                        "server_reset_ids": current_state.get("server_reset_ids", {}),
                        "instances": zeroed_instances,
                    }
                    msg = "Resetting token counters for all servers..."
                else:
                    server_reset_ids = current_state.get("server_reset_ids", {})
                    current_server_reset_id = server_reset_ids.get(server_name, 0)
                    server_reset_ids[server_name] = current_server_reset_id + 1

                    # Zero the specific server in all instances
                    zeroed_instances = {}
                    for pid_str, inst_data in live_instances.items():
                        zeroed_inst = dict(inst_data)
                        servers = dict(inst_data.get("servers", {}))
                        if server_name in servers:
                            servers[server_name] = {"tools": {}}
                        zeroed_inst["servers"] = servers
                        zeroed_instances[pid_str] = zeroed_inst

                    new_state = {
                        "reset_id": current_state.get("reset_id", 0),
                        "reset_timestamp": current_state.get("reset_timestamp", timestamp),
                        "server_reset_ids": server_reset_ids,
                        "instances": zeroed_instances,
                    }
                    msg = f"Resetting token counters for '{server_name}'..."

                state_file_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = state_file_path.with_suffix(".tmp")
                temp_path.write_text(_json.dumps(new_state, indent=2), encoding="utf-8")
                temp_path.replace(state_file_path)

            return msg

        except Timeout:
            raise RuntimeError("Could not acquire file lock")
        except Exception as e:
            raise RuntimeError(f"Failed to reset counters: {e}")

    def __init__(self, config: Dict[str, Any]):
        """Initialize Token Usage plugin with configuration.

        Args:
            config: Plugin configuration dictionary

        Raises:
            ValueError: If required configuration is missing
        """
        if not isinstance(config, dict):
            raise TypeError("Configuration must be a dictionary")

        super().__init__(config)

        # Token counting is observability - default to non-critical (fail-open)
        # so MCP traffic continues even if token estimation fails
        self.critical = config.get("critical", False)

        # Store raw paths for later resolution
        self.raw_output_file = config.get("output_file", "logs/token_usage.csv")
        self.raw_state_file = config.get("state_file", "logs/token_usage_state.json")
        self.flush_interval = config.get("flush_interval_seconds", STATE_FLUSH_INTERVAL)
        self.config_directory: Optional[Path] = None

        # Validate required fields
        if not self.raw_output_file:
            raise ValueError("output_file is required for Token Usage plugin")
        if not self.raw_state_file:
            raise ValueError("state_file is required for Token Usage plugin")

        # Initialize resolved paths (will be updated by set_config_directory)
        self.output_file = self.raw_output_file
        self.state_file = self.raw_state_file

        # Initialize tiktoken encoder
        self._tiktoken_available = False
        self._encoder = None
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
            self._tiktoken_available = True
            logger.debug("Token Usage plugin: tiktoken initialized successfully")
        except Exception as e:
            logger.info(f"Token Usage plugin: tiktoken unavailable, using heuristic estimation: {e}")

        # Initialize counters and state
        self._lock = threading.Lock()
        self._counters: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._pending_requests: Dict[str, Dict[str, Any]] = {}
        self._reset_id = 0
        self._server_reset_ids: Dict[str, int] = {}  # Per-server reset tracking
        self._reset_timestamp = datetime.utcnow().isoformat() + "Z"
        self._started_at = datetime.utcnow().isoformat() + "Z"

        # CSV buffering
        self._csv_buffer: List[Dict[str, Any]] = []
        self._last_csv_flush = time.time()
        self._csv_header_written = False

        # State file flushing
        self._last_state_flush = time.time()
        self._periodic_flush_timer: Optional[threading.Timer] = None
        self._flush_timer_stopped = False
        self._has_traffic = False  # True once any MCP traffic has been counted

        # Attempt to expand home directory paths
        try:
            self.output_file = str(expand_user_path(os.path.expandvars(self.raw_output_file)))
            self.state_file = str(expand_user_path(os.path.expandvars(self.raw_state_file)))
        except Exception as e:
            logger.debug(f"Path expansion deferred until config directory is set: {e}")

        logger.info(
            "Token Usage plugin [%x]: CREATED instance raw_output=%s raw_state=%s flush_interval=%.1f",
            id(self), self.raw_output_file, self.raw_state_file, self.flush_interval,
        )

    def set_config_directory(self, config_directory) -> None:
        """Set the configuration directory for path resolution."""
        from pathlib import Path as PathLib
        self.config_directory = PathLib(config_directory)
        logger.info(
            "Token Usage plugin [%x]: set_config_directory called config_dir=%s",
            id(self), config_directory,
        )

        # Resolve paths
        try:
            expanded_output = os.path.expandvars(self.raw_output_file)
            self.output_file = str(resolve_config_path(expanded_output, self.config_directory))
        except Exception as e:
            logger.warning(f"Failed to resolve output_file path: {e}")

        try:
            expanded_state = os.path.expandvars(self.raw_state_file)
            self.state_file = str(resolve_config_path(expanded_state, self.config_directory))
        except Exception as e:
            logger.warning(f"Failed to resolve state_file path: {e}")

        logger.debug(
            "Token Usage plugin: paths resolved config_dir=%s output_file=%s state_file=%s flush_interval=%.1f",
            self.config_directory, self.output_file, self.state_file, self.flush_interval,
        )

        # Create directories and restore state
        self._ensure_directories()
        self._restore_state()

        # Start periodic flush timer so state file stays fresh even without traffic
        self._start_periodic_flush()

    def _start_periodic_flush(self) -> None:
        """Start a recurring timer to flush state to disk."""
        if self._flush_timer_stopped:
            return
        interval = max(self.flush_interval, 1.0)
        self._periodic_flush_timer = threading.Timer(interval, self._periodic_flush_callback)
        self._periodic_flush_timer.daemon = True
        self._periodic_flush_timer.start()
        logger.debug(
            "Token Usage plugin [%x]: periodic flush timer scheduled interval=%.1f state_file=%s",
            id(self), interval, self.state_file,
        )

    def _periodic_flush_callback(self) -> None:
        """Timer callback: force-flush state and reschedule."""
        if self._flush_timer_stopped:
            return
        try:
            with self._lock:
                counter_snapshot = {
                    sn: {tn: dict(tc) for tn, tc in tools.items()}
                    for sn, tools in self._counters.items()
                }
            logger.debug(
                "Token Usage plugin [%x]: periodic flush fired server_count=%d counters=%s",
                id(self), len(self._counters), counter_snapshot,
            )
            # Bypass the rate-limit guard by resetting the last flush time
            self._last_state_flush = 0
            self._flush_state(caller="periodic_flush")
        except Exception as e:
            logger.debug(f"Token Usage plugin [%x]: Periodic flush failed: {e}", id(self))
        # Reschedule
        if not self._flush_timer_stopped:
            self._start_periodic_flush()

    def validate_paths(self) -> List[str]:
        """Validate all paths used by this plugin.

        Returns:
            List of validation error messages, empty if no errors
        """
        errors = []
        errors.extend(validate_output_path(Path(self.output_file)))
        errors.extend(validate_output_path(Path(self.state_file)))
        return errors

    @classmethod
    def resolve_and_validate_paths(
        cls, config: Dict[str, Any], config_directory: Optional[Path]
    ) -> List[str]:
        """Validate paths WITHOUT instantiation. Returns error messages.

        Resolves both ``output_file`` and ``state_file`` config values
        relative to *config_directory* and checks writability.

        Args:
            config: Plugin configuration dictionary
            config_directory: Directory containing the configuration file

        Returns:
            List of validation error messages. Empty list means all paths valid.
        """
        errors: List[str] = []

        for key in ("output_file", "state_file"):
            raw_path = config.get(key)
            if not raw_path:
                continue
            try:
                expanded = os.path.expandvars(raw_path)
                if config_directory:
                    resolved = resolve_config_path(expanded, config_directory)
                else:
                    resolved = Path(expand_user_path(expanded))
                errors.extend(validate_output_path(resolved))
            except Exception as e:
                errors.append(f"Error resolving {key} path '{raw_path}': {e}")

        return errors

    def _ensure_directories(self) -> None:
        """Create parent directories for output and state files."""
        for file_path in [self.output_file, self.state_file]:
            try:
                parent = Path(file_path).parent
                parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            except Exception as e:
                logger.warning(f"Failed to create directory for {file_path}: {e}")

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process with the given PID is still running.

        On POSIX, os.kill(pid, 0) raises ProcessLookupError for dead PIDs and
        PermissionError for alive-but-unprivileged PIDs.  On Windows, os.kill
        has no proper signal-0 semantics and can raise OSError, SystemError, or
        other exceptions depending on the CPython version.  We catch broadly:
        PermissionError means alive, anything else means not confirmed alive.
        """
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True  # Process exists but we can't signal it
        except Exception:
            return False

    def _restore_state(self) -> None:
        """Restore counters from own PID's instance in state file on startup."""
        state_path = Path(self.state_file)
        if not state_path.exists():
            logger.debug("Token Usage plugin: No state file found, starting fresh")
            return

        # Log file metadata before reading
        try:
            st = state_path.stat()
            logger.debug(
                "Token Usage plugin: restoring state path=%s size=%d mtime=%.1f",
                state_path, st.st_size, st.st_mtime,
            )
        except OSError as e:
            logger.debug("Token Usage plugin: could not stat state file: %s", e)

        try:
            lock_path = self.state_file + ".lock"
            lock = FileLock(lock_path, timeout=5)
            with lock:
                content = state_path.read_text(encoding="utf-8")
                state = json.loads(content)

                self._reset_id = state.get("reset_id", 0)
                self._server_reset_ids = state.get("server_reset_ids", {})
                self._reset_timestamp = state.get("reset_timestamp", datetime.utcnow().isoformat() + "Z")

                # Restore counters from own PID's instance
                pid_key = str(os.getpid())
                instances = state.get("instances", {})
                instance_data = instances.get(pid_key, {})

                if instance_data:
                    servers = instance_data.get("servers", {})
                    for server_name, server_data in servers.items():
                        self._counters[server_name] = {}
                        tools = server_data.get("tools", {})
                        for tool_name, tool_data in tools.items():
                            self._counters[server_name][tool_name] = {
                                "input": tool_data.get("input", 0),
                                "output": tool_data.get("output", 0),
                            }
                    if servers:
                        self._has_traffic = True
                else:
                    # No instance for our PID — check for legacy top-level servers
                    # from pre-instances state files (backward compat migration)
                    legacy_servers = state.get("servers", {})
                    for server_name, server_data in legacy_servers.items():
                        self._counters[server_name] = {}
                        tools = server_data.get("tools", {})
                        for tool_name, tool_data in tools.items():
                            self._counters[server_name][tool_name] = {
                                "input": tool_data.get("input", 0),
                                "output": tool_data.get("output", 0),
                            }
                    if legacy_servers:
                        self._has_traffic = True
                        logger.info(
                            "Token Usage plugin: Migrated %d servers from legacy state format",
                            len(legacy_servers),
                        )

                # Log restored counter summary
                total_by_server = {}
                for sn, tools in self._counters.items():
                    total_in = sum(t.get("input", 0) for t in tools.values())
                    total_out = sum(t.get("output", 0) for t in tools.values())
                    total_by_server[sn] = {"input": total_in, "output": total_out}
                logger.info(
                    "Token Usage plugin: Restored state reset_id=%d servers=%d totals=%s",
                    self._reset_id, len(self._counters), total_by_server,
                )

        except Timeout:
            logger.warning("Token Usage plugin: Could not acquire lock for state file restore")
        except json.JSONDecodeError as e:
            logger.warning(f"Token Usage plugin: Corrupt state file, starting fresh: {e}")
        except Exception as e:
            logger.warning(f"Token Usage plugin: Failed to restore state: {e}")

    def _estimate_tokens_heuristic(self, content: Any) -> int:
        """Estimate token count using a pure-Python heuristic.

        Uses max(chars//4, words*1.33) as a rough approximation.
        Less accurate than tiktoken but requires no native dependencies.

        Args:
            content: Content to estimate tokens for

        Returns:
            Estimated token count, or 0 on error
        """
        if content is None:
            return 0
        try:
            text = content if isinstance(content, str) else json.dumps(content, default=str)
            if len(text) > MAX_CONTENT_SIZE:
                text = text[:MAX_CONTENT_SIZE]
            return max(len(text) // 4, int(len(text.split()) * 1.33))
        except Exception:
            return 0

    def _estimate_tokens(self, content: Any) -> int:
        """Estimate token count for content using tiktoken.

        Falls back to a heuristic when tiktoken is unavailable.

        Args:
            content: Content to tokenize (will be JSON-serialized if not string)

        Returns:
            Estimated token count, or 0 on error
        """
        if not self._tiktoken_available or self._encoder is None:
            return self._estimate_tokens_heuristic(content)

        if content is None:
            return 0

        try:
            # Convert to string
            if isinstance(content, str):
                text = content
            else:
                text = json.dumps(content, default=str)

            # Check size limit
            if len(text) > MAX_CONTENT_SIZE:
                text = text[:MAX_CONTENT_SIZE]
                logger.debug("Token Usage plugin: Content truncated for tokenization")

            # Encode and count
            tokens = self._encoder.encode(text)
            return len(tokens)

        except Exception as e:
            logger.debug(f"Token Usage plugin: Token estimation failed: {e}")
            return 0

    def _get_tool_name(self, request: MCPRequest) -> str:
        """Extract tool name from request, or return '_other' for non-tool traffic."""
        if (
            hasattr(request, "method")
            and request.method == "tools/call"
            and hasattr(request, "params")
            and request.params
            and "name" in request.params
        ):
            return request.params["name"]
        return "_other"

    def _increment_counter(self, server_name: str, tool_name: str, input_tokens: int, output_tokens: int) -> None:
        """Increment token counters for a server/tool."""
        with self._lock:
            if server_name not in self._counters:
                self._counters[server_name] = {}
            if tool_name not in self._counters[server_name]:
                self._counters[server_name][tool_name] = {"input": 0, "output": 0}

            self._counters[server_name][tool_name]["input"] += input_tokens
            self._counters[server_name][tool_name]["output"] += output_tokens
            self._has_traffic = True

    def _add_csv_row(self, server_name: str, method: str, tool_name: str, input_tokens: int, output_tokens: int) -> None:
        """Add a row to the CSV buffer and flush if needed."""
        row = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "server": server_name,
            "method": method or "",
            "tool": tool_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

        with self._lock:
            self._csv_buffer.append(row)

            # Check if we should flush
            now = time.time()
            should_flush = (
                len(self._csv_buffer) >= CSV_BUFFER_MAX_ROWS or
                (now - self._last_csv_flush) >= CSV_BUFFER_MAX_SECONDS
            )

            if should_flush:
                self._flush_csv_buffer()

    def _flush_csv_buffer(self) -> None:
        """Flush CSV buffer to disk. Must be called with lock held."""
        if not self._csv_buffer:
            return

        try:
            output_path = Path(self.output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if we need to write header
            write_header = not output_path.exists() or output_path.stat().st_size == 0

            with open(self.output_file, "a", encoding="utf-8", newline="") as f:
                fieldnames = ["timestamp", "server", "method", "tool", "input_tokens", "output_tokens"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)

                if write_header:
                    writer.writeheader()

                for row in self._csv_buffer:
                    # Sanitize tool name for CSV injection
                    sanitized_row = row.copy()
                    for key in ["server", "method", "tool"]:
                        val = sanitized_row.get(key, "")
                        if val and isinstance(val, str) and val[0] in ("=", "+", "-", "@", "\t"):
                            sanitized_row[key] = "'" + val
                    writer.writerow(sanitized_row)

            self._csv_buffer = []
            self._last_csv_flush = time.time()

        except Exception as e:
            logger.warning(f"Token Usage plugin: Failed to flush CSV buffer: {e}")

    def _flush_state(self, caller: str = "unknown") -> None:
        """Flush state to disk with file locking.

        Writes own counters under instances[own_pid], preserves other instances,
        and cleans up dead PID entries.
        """
        # Skip flush entirely if this instance has never seen MCP traffic.
        # This prevents non-gateway processes (e.g. the TUI) that instantiate
        # the plugin for config introspection from writing empty entries to
        # the shared state file.
        if not self._has_traffic:
            logger.debug(
                "Token Usage plugin [%x]: flush SKIPPED (no traffic) caller=%s state_file=%s",
                id(self), caller, self.state_file,
            )
            return

        now = time.time()
        elapsed = now - self._last_state_flush
        if elapsed < self.flush_interval:
            logger.debug(
                "Token Usage plugin [%x]: flush SKIPPED caller=%s elapsed=%.3f interval=%.1f state_file=%s",
                id(self), caller, elapsed, self.flush_interval, self.state_file,
            )
            return

        logger.debug(
            "Token Usage plugin [%x]: flush STARTING caller=%s elapsed=%.3f state_file=%s",
            id(self), caller, elapsed, self.state_file,
        )

        try:
            lock_path = self.state_file + ".lock"
            lock = FileLock(lock_path, timeout=2)

            with lock:
                # Read current state to check for reset and preserve other instances
                state_path = Path(self.state_file)
                existing_state = {}
                existing_server_reset_ids = {}
                if state_path.exists():
                    try:
                        content = state_path.read_text(encoding="utf-8")
                        existing_state = json.loads(content)
                        existing_reset_id = existing_state.get("reset_id", 0)
                        existing_server_reset_ids = existing_state.get("server_reset_ids", {})

                        logger.debug(
                            "Token Usage plugin [%x]: flush READ existing state caller=%s "
                            "file_reset_id=%d our_reset_id=%d file_server_reset_ids=%s "
                            "our_server_reset_ids=%s instance_count=%d",
                            id(self), caller,
                            existing_reset_id, self._reset_id,
                            existing_server_reset_ids, self._server_reset_ids,
                            len(existing_state.get("instances", {})),
                        )

                        # Check for global reset (zeroes all servers)
                        if existing_reset_id > self._reset_id:
                            logger.warning(
                                "Token Usage plugin [%x]: GLOBAL RESET DETECTED caller=%s "
                                "file_reset_id=%d > our_reset_id=%d — ZEROING ALL COUNTERS",
                                id(self), caller, existing_reset_id, self._reset_id,
                            )
                            self._reset_id = existing_reset_id
                            self._server_reset_ids = existing_server_reset_ids
                            self._reset_timestamp = existing_state.get("reset_timestamp", datetime.utcnow().isoformat() + "Z")
                            with self._lock:
                                # Zero out all servers (keep keys so TUI shows 0, not "—")
                                self._counters = {name: {} for name in self._counters}
                                self._pending_requests = {}
                            # Fall through to write the zeroed state

                        # Check for per-server resets
                        servers_to_clear = []
                        for server_name, file_reset_id in existing_server_reset_ids.items():
                            our_reset_id = self._server_reset_ids.get(server_name, 0)
                            if file_reset_id > our_reset_id:
                                servers_to_clear.append(server_name)
                                self._server_reset_ids[server_name] = file_reset_id

                        if servers_to_clear:
                            logger.warning(
                                "Token Usage plugin [%x]: PER-SERVER RESET DETECTED caller=%s servers=%s",
                                id(self), caller, servers_to_clear,
                            )
                            with self._lock:
                                for server_name in servers_to_clear:
                                    self._counters[server_name] = {}
                                    to_remove = [k for k, v in self._pending_requests.items() if v.get("server_name") == server_name]
                                    for k in to_remove:
                                        del self._pending_requests[k]

                    except Exception as e:
                        logger.debug(f"Token Usage plugin [%x]: Could not read state file for reset check: {e}", id(self))

                # Build own instance data
                pid_key = str(os.getpid())
                own_servers: Dict[str, Any] = {}
                with self._lock:
                    for server_name, tools in self._counters.items():
                        own_servers[server_name] = {"tools": {}}
                        for tool_name, counts in tools.items():
                            own_servers[server_name]["tools"][tool_name] = {
                                "input": counts["input"],
                                "output": counts["output"],
                            }

                own_instance = {
                    "started_at": self._started_at,
                    "last_update": datetime.utcnow().isoformat() + "Z",
                    "servers": own_servers,
                }

                # Preserve all other instances — counter data persists until
                # the user explicitly resets via the TUI.  Dead PID entries are
                # cleaned up only during reset_counters().
                other_instances: Dict[str, Any] = {
                    k: v for k, v in existing_state.get("instances", {}).items()
                    if k != pid_key
                }
                other_instances[pid_key] = own_instance

                # Build state object
                state = {
                    "reset_id": self._reset_id,
                    "reset_timestamp": self._reset_timestamp,
                    "server_reset_ids": self._server_reset_ids,
                    "instances": other_instances,
                }

                # Log what we're about to write
                write_summary = {}
                for sn, sdata in own_servers.items():
                    tools = sdata.get("tools", {})
                    total_in = sum(t.get("input", 0) for t in tools.values())
                    total_out = sum(t.get("output", 0) for t in tools.values())
                    write_summary[sn] = {"input": total_in, "output": total_out}
                logger.debug(
                    "Token Usage plugin [%x]: flush WRITING caller=%s reset_id=%d "
                    "own_server_count=%d own_summary=%s total_instances=%d state_file=%s",
                    id(self), caller, state["reset_id"],
                    len(own_servers), write_summary, len(other_instances), self.state_file,
                )

                # Atomic write: temp file + rename
                state_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = state_path.with_suffix(".tmp")

                # Create with secure permissions (0600)
                fd = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state, f, indent=2)
                except Exception:
                    os.close(fd)
                    raise

                # Atomic rename
                temp_path.replace(state_path)
                self._last_state_flush = now

                logger.debug(
                    "Token Usage plugin [%x]: flush COMPLETED caller=%s state_file=%s",
                    id(self), caller, self.state_file,
                )

        except Timeout:
            logger.warning(
                "Token Usage plugin [%x]: flush LOCK TIMEOUT caller=%s state_file=%s",
                id(self), caller, self.state_file,
            )
        except Exception as e:
            logger.warning(
                "Token Usage plugin [%x]: flush FAILED caller=%s error=%s state_file=%s",
                id(self), caller, e, self.state_file,
            )

    def _cleanup_pending_requests(self) -> None:
        """Remove pending requests older than TTL."""
        now = time.time()
        cutoff = now - PENDING_REQUEST_TTL

        with self._lock:
            expired = [
                req_id for req_id, data in self._pending_requests.items()
                if data.get("timestamp", 0) < cutoff
            ]
            for req_id in expired:
                del self._pending_requests[req_id]

    async def log_request(
        self, request: MCPRequest, pipeline: ProcessingPipeline, server_name: str
    ) -> None:
        """Log request and track output tokens (tool calls from LLM)."""
        # Flush state first to detect any pending resets before adding new data.
        # This prevents the race where counters are incremented then immediately
        # cleared by reset detection, losing both the data and response correlation.
        self._flush_state(caller=f"log_request:{server_name}:{getattr(request, 'method', '?')}")

        # Estimate output tokens (request = LLM output)
        output_tokens = self._estimate_tokens(request.to_dict() if hasattr(request, "to_dict") else request)

        # Get tool name
        tool_name = self._get_tool_name(request)

        # Store pending request for response correlation
        # Use 'is not None' to allow valid JSON-RPC id=0
        if request.id is not None:
            with self._lock:
                self._pending_requests[str(request.id)] = {
                    "tool_name": tool_name,
                    "output_tokens": output_tokens,
                    "timestamp": time.time(),
                    "method": getattr(request, "method", None),
                    "server_name": server_name,
                }

        # Increment output counter (request = LLM output)
        self._increment_counter(server_name, tool_name, 0, output_tokens)

        # Periodic cleanup
        self._cleanup_pending_requests()

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        """Log response and track input tokens (server responses into LLM)."""
        # Flush state first to detect any pending resets before adding new data
        self._flush_state(caller=f"log_response:{server_name}:{getattr(request, 'method', '?') if request else '?'}")

        # Estimate input tokens (response = LLM input)
        input_tokens = self._estimate_tokens(response.to_dict() if hasattr(response, "to_dict") else response)

        # Look up pending request for tool name and output tokens
        # Use 'is not None' to allow valid JSON-RPC id=0
        request_id = str(response.id) if response.id is not None else None
        tool_name = "_other"
        output_tokens = 0
        method = getattr(request, "method", None) if request else None

        if request_id:
            with self._lock:
                pending = self._pending_requests.pop(request_id, None)
                if pending:
                    tool_name = pending.get("tool_name", "_other")
                    output_tokens = pending.get("output_tokens", 0)
                    method = pending.get("method", method)

        # Increment input counter (response = LLM input)
        self._increment_counter(server_name, tool_name, input_tokens, 0)

        # Add CSV row (includes both input and output from this request/response pair)
        self._add_csv_row(server_name, method, tool_name, input_tokens, output_tokens)

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        """Log notification tokens (counted as _other)."""
        # Skip notifications without a server (e.g. notifications/initialized broadcasts)
        if server_name is None:
            return

        # Flush state first to detect any pending resets before adding new data
        self._flush_state(caller=f"log_notification:{server_name}:{getattr(notification, 'method', '?')}")

        # Estimate tokens
        tokens = self._estimate_tokens(notification.to_dict() if hasattr(notification, "to_dict") else notification)

        # Notifications go to _other category
        tool_name = "_other"
        method = getattr(notification, "method", "notification")

        # Increment input counter (notifications are from server, into LLM)
        self._increment_counter(server_name, tool_name, tokens, 0)

        # Add CSV row (notifications are input tokens)
        self._add_csv_row(server_name, method, tool_name, tokens, 0)

    def cleanup(self) -> None:
        """Clean up resources on shutdown.

        Performs a final flush, then removes own PID entry from the state file
        while preserving other instances and reset signals.
        """
        logger.info(
            "Token Usage plugin [%x]: CLEANUP called state_file=%s",
            id(self), self.state_file,
        )
        # Stop periodic flush timer
        self._flush_timer_stopped = True
        if self._periodic_flush_timer is not None:
            self._periodic_flush_timer.cancel()
            self._periodic_flush_timer = None

        # Flush any remaining CSV buffer
        with self._lock:
            self._flush_csv_buffer()

        # Flush state one last time
        self._last_state_flush = 0  # Force flush
        self._flush_state(caller="cleanup")

        # Remove own PID entry from state file
        try:
            lock_path = self.state_file + ".lock"
            lock = FileLock(lock_path, timeout=2)
            pid_key = str(os.getpid())

            with lock:
                state_path = Path(self.state_file)
                if state_path.exists():
                    try:
                        content = state_path.read_text(encoding="utf-8")
                        state = json.loads(content)
                        instances = state.get("instances", {})
                        if pid_key in instances:
                            del instances[pid_key]
                            state["instances"] = instances
                            temp_path = state_path.with_suffix(".tmp")
                            temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                            temp_path.replace(state_path)
                            logger.debug(
                                "Token Usage plugin [%x]: removed own PID %s from state file",
                                id(self), pid_key,
                            )
                    except Exception as e:
                        logger.debug(
                            "Token Usage plugin [%x]: failed to remove PID entry: %s",
                            id(self), e,
                        )
        except Exception as e:
            logger.debug(
                "Token Usage plugin [%x]: cleanup PID removal failed: %s",
                id(self), e,
            )

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.cleanup()
        except Exception:  # noqa: S110
            pass  # Suppress all errors during GC - __del__ must not raise


# Handler manifest for handler-based plugin discovery
HANDLERS = {"token_usage": TokenUsagePlugin}
