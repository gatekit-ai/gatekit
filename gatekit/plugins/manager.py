"""Plugin manager for Gatekit MCP gateway.

This module provides the central orchestration of the plugin system,
including plugin discovery, loading, lifecycle management, and request/response
processing through the plugin pipeline.
"""

from typing import List, Dict, Any, Optional, Union
import logging
import importlib
import sys
from gatekit.utils.exceptions import PluginValidationError
import importlib.util
from pathlib import Path
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    PathResolvablePlugin,
    MiddlewarePlugin,
    ProcessingPipeline,
    PipelineStage,
    StageOutcome,
    PipelineOutcome,
)
import time
import hashlib
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.protocol.errors import AuditingFailureError

logger = logging.getLogger(__name__)


class PluginManager:
    """Central orchestration of plugin system.

    The PluginManager handles loading plugins from configuration, managing their
    lifecycle, and orchestrating request/response flow through the plugin pipeline.
    It ensures proper error isolation so plugin failures don't crash the system.
    """

    def __init__(
        self, plugins_config: Dict[str, Any], config_directory: Optional[Path] = None
    ):
        """Initialize with plugin configuration from YAML.

        Args:
            plugins_config: Dictionary containing 'security', 'middleware', and 'auditing' plugin configs
                          Expected format (upstream-scoped, consolidated):
                          {
                              "security": {
                                  "_global": [{"handler": "plugin_name", "config": {"enabled": True, ...}}],
                                  "upstream_name": [{"handler": "plugin_name", "config": {"enabled": True, ...}}]
                              },
                              "middleware": {
                                  "_global": [{"handler": "plugin_name", "config": {"enabled": True, ...}}],
                                  "upstream_name": [{"handler": "plugin_name", "config": {"enabled": True, ...}}]
                              },
                              "auditing": {
                                  "_global": [{"handler": "plugin_name", "config": {"enabled": True, ...}}],
                                  "upstream_name": [{"handler": "plugin_name", "config": {"enabled": True, ...}}]
                              }
                          }
                          Note: enabled, priority, and critical are stored inside the config dict.
            config_directory: Directory containing the configuration file (for path resolution)
        """
        self.plugins_config = plugins_config
        self.config_directory = config_directory

        # Upstream-scoped plugin storage: upstream_name -> [plugins]
        self.upstream_security_plugins: Dict[str, List[SecurityPlugin]] = {}
        self.upstream_auditing_plugins: Dict[str, List[AuditingPlugin]] = {}
        self.upstream_middleware_plugins: Dict[str, List[MiddlewarePlugin]] = {}

        # Cache discovered handler classes by category to avoid repeated filesystem scans
        self._handler_cache: Dict[str, Dict[str, type]] = {}

        self._initialized = False
        self._load_failures: List[Dict[str, str]] = []  # Track plugin load failures

    @property
    def security_plugins(self) -> List[SecurityPlugin]:
        """Get global security plugins for compatibility."""
        return self.upstream_security_plugins.get("_global", [])

    @security_plugins.setter
    def security_plugins(self, plugins: List[SecurityPlugin]) -> None:
        """Set global security plugins for compatibility."""
        self.upstream_security_plugins["_global"] = plugins

    @property
    def auditing_plugins(self) -> List[AuditingPlugin]:
        """Get global auditing plugins for compatibility."""
        return self.upstream_auditing_plugins.get("_global", [])

    @auditing_plugins.setter
    def auditing_plugins(self, plugins: List[AuditingPlugin]) -> None:
        """Set global auditing plugins for compatibility."""
        self.upstream_auditing_plugins["_global"] = plugins

    async def load_plugins(self) -> None:
        """Discover and load configured plugins.

        Loads security and auditing plugins from configuration. Plugin loading
        failures are logged but don't prevent other plugins from loading or
        crash the system.

        Raises:
            Exception: Only if no plugins can be loaded and configuration requires them
        """
        if self._initialized:
            logger.warning("Plugin manager already initialized, skipping reload")
            return

        logger.info("Loading plugins from configuration")

        # Load plugins - dictionary format only
        middleware_config = self.plugins_config.get("middleware", {})
        security_config = self.plugins_config.get("security", {})
        auditing_config = self.plugins_config.get("auditing", {})

        # Load all plugin types - execution order determined by priority, not load order
        self._load_upstream_scoped_middleware_plugins(middleware_config)

        # Then security and auditing as before
        self._load_upstream_scoped_security_plugins(security_config)
        self._load_upstream_scoped_auditing_plugins(auditing_config)

        self._initialized = True

        # Count total plugins across all upstreams
        total_security = sum(
            len(plugins) for plugins in self.upstream_security_plugins.values()
        )
        total_auditing = sum(
            len(plugins) for plugins in self.upstream_auditing_plugins.values()
        )
        total_middleware = sum(
            len(plugins) for plugins in self.upstream_middleware_plugins.values()
        )

        logger.info(
            f"Plugin loading complete: {total_middleware} middleware, {total_security} security, "
            f"{total_auditing} auditing plugins loaded across {len(self.upstream_security_plugins)} upstreams"
        )

    def has_load_failures(self) -> bool:
        """Check if there were any plugin load failures.

        Returns:
            bool: True if any plugins failed to load, False otherwise
        """
        return len(self._load_failures) > 0

    def get_load_failures(self) -> List[Dict[str, str]]:
        """Get details of plugin load failures.

        Returns:
            List[Dict[str, str]]: List of failure details with 'type', 'handler', and 'error' keys
        """
        return self._load_failures.copy()

    def get_plugins_for_upstream(self, upstream_name: str) -> Dict[str, List]:
        """Get plugins for a specific upstream with global fallback.

        Returns plugins for the specified upstream, combining global handlers
        with upstream-specific handlers. Upstream-specific handlers override
        global handlers with the same name.

        Args:
            upstream_name: Name of the upstream to get plugins for

        Returns:
            Dict with 'middleware', 'security' and 'auditing' keys containing plugin lists
        """
        if not self._initialized:
            logger.warning(
                "Plugin manager not initialized, returning empty plugin sets"
            )
            return {"middleware": [], "security": [], "auditing": []}

        # Get middleware plugins for upstream
        middleware_plugins = self._resolve_plugins_for_upstream(
            self.upstream_middleware_plugins, upstream_name
        )

        # Get security plugins for upstream
        security_plugins = self._resolve_plugins_for_upstream(
            self.upstream_security_plugins, upstream_name
        )

        # Get auditing plugins for upstream
        auditing_plugins = self._resolve_plugins_for_upstream(
            self.upstream_auditing_plugins, upstream_name
        )

        return {
            "middleware": middleware_plugins,
            "security": security_plugins,
            "auditing": auditing_plugins,
        }

    def _resolve_plugins_for_upstream(
        self, upstream_plugins_dict: Dict[str, List], upstream_name: str
    ) -> List:
        """Resolve plugins for an upstream with global fallback and handler override.

        Args:
            upstream_plugins_dict: Dictionary of upstream -> plugin lists
            upstream_name: Name of the upstream to resolve plugins for

        Returns:
            List of plugins for the upstream (security/middleware sorted by priority,
            auditing unsorted)
        """
        resolved_plugins = []
        plugin_names_added = set()

        # Start with global plugins if they exist
        global_plugins = upstream_plugins_dict.get("_global", [])
        for plugin in global_plugins:
            plugin_handler = getattr(plugin, "handler", plugin.__class__.__name__)
            resolved_plugins.append(plugin)
            plugin_names_added.add(plugin_handler)

        # Add upstream-specific plugins, overriding global ones with same handler name
        upstream_plugins = upstream_plugins_dict.get(upstream_name, [])
        for plugin in upstream_plugins:
            plugin_handler = getattr(plugin, "handler", plugin.__class__.__name__)

            if plugin_handler in plugin_names_added:
                # Override: remove global plugin with same handler name
                resolved_plugins = [
                    p
                    for p in resolved_plugins
                    if getattr(p, "handler", p.__class__.__name__) != plugin_handler
                ]

            resolved_plugins.append(plugin)
            plugin_names_added.add(plugin_handler)

        # Only sort security plugins by priority
        # Auditing plugins execute in definition order and don't have priority
        if resolved_plugins:
            from gatekit.plugins.interfaces import SecurityPlugin, AuditingPlugin

            # Defensive assert: plugins should not inherit from both SecurityPlugin and AuditingPlugin
            for plugin in resolved_plugins:
                assert not (
                    isinstance(plugin, SecurityPlugin)
                    and isinstance(plugin, AuditingPlugin)
                ), f"Plugin {plugin.__class__.__name__} incorrectly inherits from both SecurityPlugin and AuditingPlugin"

            # Check plugin types
            if any(isinstance(p, AuditingPlugin) for p in resolved_plugins):
                # Don't sort auditing plugins - they execute in definition order
                pass
            elif all(isinstance(p, SecurityPlugin) for p in resolved_plugins):
                # All security plugins - sort by priority
                resolved_plugins.sort(key=lambda p: p.priority)
            elif all(hasattr(p, "priority") for p in resolved_plugins):
                # All have priority attribute (mock security plugins) - sort them
                resolved_plugins.sort(key=lambda p: p.priority)
            elif any(hasattr(p, "priority") for p in resolved_plugins):
                # Mixed - some have priority, some don't - warning but don't crash
                logger.warning(
                    "Mixed plugins detected for upstream '%s' - some have priority, some don't. "
                    "This configuration may lead to unexpected behavior.",
                    upstream_name,
                )

        return resolved_plugins

    def _get_processing_pipeline(
        self, upstream_name: str
    ) -> List[Union[MiddlewarePlugin, SecurityPlugin]]:
        """Get all middleware and security plugins for an upstream, sorted by priority.

        Args:
            upstream_name: Name of the upstream server

        Returns:
            List of plugins sorted by priority (lower number runs first)
        """
        all_plugins = []

        # Get middleware plugins
        middleware_plugins = self._resolve_plugins_for_upstream(
            self.upstream_middleware_plugins, upstream_name
        )
        all_plugins.extend(middleware_plugins)

        # Get security plugins
        security_plugins = self._resolve_plugins_for_upstream(
            self.upstream_security_plugins, upstream_name
        )
        all_plugins.extend(security_plugins)

        # Sort by priority (lower number = higher priority = runs first)
        all_plugins.sort(key=lambda p: getattr(p, "priority", 50))

        return all_plugins

    async def _execute_plugin_check(
        self, plugin, check_method_name: str, *args, **kwargs
    ) -> PluginResult:
        """Execute a plugin check method with automatic metadata injection.

        Args:
            plugin: The plugin instance to execute
            check_method_name: Name of the method to call ('process_request', 'process_response', 'process_notification')
            *args: Arguments to pass to the check method
            **kwargs: Keyword arguments to pass to the check method

        Returns:
            PluginResult: Result with plugin name automatically added to metadata
        """
        plugin_name = getattr(plugin, "plugin_id", plugin.__class__.__name__)
        logger.debug(
            f"Executing plugin {plugin_name} with priority {getattr(plugin, 'priority', 50)}"
        )

        check_method = getattr(plugin, check_method_name)
        decision = await check_method(*args, **kwargs)

        # Automatically add plugin name to metadata
        if decision.metadata is None:
            decision.metadata = {}
        decision.metadata["plugin"] = plugin_name

        return decision

    def _enforce_plugin_contracts(self, plugin, result: PluginResult) -> PluginResult:
        """Enforce plugin type contracts on the result.

        Args:
            plugin: The plugin instance that produced the result
            result: The PluginResult to validate and potentially modify

        Returns:
            The validated/modified PluginResult

        Raises:
            ValueError: If a SecurityPlugin fails to make a security decision
        """
        plugin_name = getattr(plugin, "plugin_id", plugin.__class__.__name__)

        # Enforce SecurityPlugin contract - must make a security decision
        if isinstance(plugin, SecurityPlugin) and result.allowed is None:
            raise PluginValidationError(
                f"Security plugin {plugin_name} failed to make a security decision. "
                f"Must return PluginResult with allowed=True or allowed=False"
            )

        # Enforce MiddlewarePlugin contract - cannot make security decisions
        if (
            isinstance(plugin, MiddlewarePlugin)
            and not isinstance(plugin, SecurityPlugin)
            and result.allowed is not None
        ):
            raise PluginValidationError(
                f"Middleware plugin {plugin_name} illegally set allowed={result.allowed}. "
                f"Only SecurityPlugin can make security decisions. "
                f"To make security decisions, implement SecurityPlugin instead of MiddlewarePlugin."
            )

        return result

    async def process_request(
        self, request: MCPRequest, server_name: Optional[str] = None
    ) -> ProcessingPipeline:
        """Process request through middleware and security plugins.

        Args:
            request: The MCP request to evaluate
            server_name: Name of the target upstream server

        Returns:
            PluginResult: Combined decision from plugins
        """
        if not self._initialized:
            await self.load_plugins()

        plugins = self._get_processing_pipeline(server_name or "unknown")
        pipeline = ProcessingPipeline(
            original_content=request,
            stages=[],
            final_content=None,
            total_time_ms=0.0,
            pipeline_outcome=PipelineOutcome.NO_SECURITY_EVALUATION,
            blocked_at_stage=None,
            completed_by=None,
            had_security_plugin=False,
            capture_content=True,
        )
        had_critical_error = False
        if not plugins:
            pipeline.final_content = request
            return pipeline

        # Request is already clean from the boundary layer
        current_request = request
        start_time = time.monotonic()
        for plugin in plugins:
            stage_start = time.monotonic()
            plugin_name = getattr(plugin, "plugin_id", plugin.__class__.__name__)
            input_content = current_request
            outcome = StageOutcome.ALLOWED
            error_type = None
            try:
                result = await self._execute_plugin_check(
                    plugin, "process_request", current_request, server_name=server_name
                )
                result = self._enforce_plugin_contracts(plugin, result)
                if isinstance(plugin, SecurityPlugin):
                    pipeline.had_security_plugin = True
                    if result.allowed is False:
                        outcome = StageOutcome.BLOCKED
                    elif (
                        result.allowed is True
                        and pipeline.pipeline_outcome
                        == PipelineOutcome.NO_SECURITY_EVALUATION
                    ):
                        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
                # Determine modifications / completion
                if result.completed_response:
                    outcome = StageOutcome.COMPLETED_BY_MIDDLEWARE
                elif result.modified_content:
                    outcome = StageOutcome.MODIFIED
            except Exception as e:
                error_type = type(e).__name__
                outcome = StageOutcome.ERROR
                result = PluginResult(
                    allowed=False, reason=str(e), metadata={"plugin": plugin_name}
                )
                if isinstance(plugin, SecurityPlugin):
                    pipeline.had_security_plugin = True

                # Check if plugin is critical to determine handling
                if hasattr(plugin, "is_critical") and not plugin.is_critical():
                    # Non-critical plugin failure: log warning but continue processing
                    logger.warning(
                        f"Non-critical plugin {plugin_name} failed during request processing: {e}"
                    )
                else:
                    # Critical plugin failure: ensure processing stops
                    logger.error(
                        f"Critical plugin {plugin_name} failed during request processing: {e}",
                        exc_info=True,
                    )
                    had_critical_error = True
            stage_end = time.monotonic()
            elapsed_ms = (stage_end - stage_start) * 1000
            output_content = None
            if result.modified_content and isinstance(
                result.modified_content, MCPRequest
            ):
                output_content = result.modified_content
                current_request = result.modified_content
            elif result.completed_response:
                output_content = result.completed_response
            # Content hash (low overhead)
            content_hash = hashlib.blake2s(
                str(input_content).encode(), digest_size=8
            ).hexdigest()
            stage = PipelineStage(
                plugin_name=plugin_name,
                plugin_type=(
                    "security" if isinstance(plugin, SecurityPlugin) else "middleware"
                ),
                input_content=input_content,
                output_content=output_content,
                content_hash=content_hash,
                result=result,
                processing_time_ms=elapsed_ms,
                outcome=outcome,
                error_type=error_type,
                security_evaluated=isinstance(plugin, SecurityPlugin),
            )
            pipeline.add_stage(stage)
            # Capture content handler update
            if isinstance(plugin, SecurityPlugin):
                if result.allowed is False or result.modified_content is not None:
                    pipeline.capture_content = False
            if outcome == StageOutcome.BLOCKED:
                pipeline.final_content = current_request
                break
            if outcome == StageOutcome.COMPLETED_BY_MIDDLEWARE:
                pipeline.final_content = result.completed_response
                break
            if outcome == StageOutcome.ERROR:
                pipeline.final_content = current_request
                # Only break for critical plugin errors
                if not hasattr(plugin, "is_critical") or plugin.is_critical():
                    break
        # Finalize
        end_time = time.monotonic()
        pipeline.total_time_ms = (end_time - start_time) * 1000
        if pipeline.final_content is None:
            pipeline.final_content = current_request
        # Set final pipeline outcome (for deferred outcomes)
        if had_critical_error:
            pipeline.pipeline_outcome = PipelineOutcome.ERROR
        elif pipeline.pipeline_outcome not in (
            PipelineOutcome.BLOCKED,
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
        ):
            # Only set deferred outcomes if no immediate outcome was already set
            # Check if any stage modified content
            has_modifications = any(
                stage.outcome == StageOutcome.MODIFIED for stage in pipeline.stages
            )
            if has_modifications:
                pipeline.pipeline_outcome = PipelineOutcome.MODIFIED
            elif (
                pipeline.had_security_plugin
                and pipeline.pipeline_outcome != PipelineOutcome.ALLOWED
            ):
                # This shouldn't happen as ALLOWED is set immediately, but keep for safety
                pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        # Apply content clearing if capture_content False
        if not pipeline.capture_content:
            for s in pipeline.stages:
                s.input_content = None
                s.output_content = None
                if s.result and s.result.reason:
                    s.result.reason = f"[{s.outcome.value}]"
        return pipeline

    async def process_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        server_name: Optional[str] = None,
    ) -> ProcessingPipeline:
        """Run response through upstream-scoped security plugins.

        Processes the response through security plugins for the specified upstream.
        Combines global (_global) plugins with upstream-specific plugins, where
        upstream-specific plugins override global ones with the same handler name.

        Args:
            request: The original MCP request for correlation
            response: The MCP response to evaluate
            server_name: Optional name of the source server

        Returns:
            PluginResult: Combined decision from plugins for the upstream
        """
        if not self._initialized:
            await self.load_plugins()

        # For aggregated tools/list responses (server_name=None), we need special handling
        # to provide proper server context to plugins for each tool
        if server_name is None and request.method == "tools/list":
            # Process aggregated response - returns a complete ProcessingPipeline with stages
            return await self._process_aggregated_tools_list_response(request, response)

        # For other responses, process normally
        return await self._process_single_server_response(
            request, response, server_name
        )

    async def _process_single_server_response(
        self, request: MCPRequest, response: MCPResponse, server_name: Optional[str]
    ) -> ProcessingPipeline:
        """Process response from a single server through upstream-scoped security plugins.

        Args:
            request: The original MCP request
            response: The MCP response from specific server
            server_name: Name of the source server (None for non-aggregated responses)

        Returns:
            PluginResult: Decision from processing the response
        """
        # Get combined pipeline of middleware and security plugins
        plugins = self._get_processing_pipeline(server_name or "unknown")
        pipeline = ProcessingPipeline(
            original_content=response,
            stages=[],
            final_content=None,
            total_time_ms=0.0,
            pipeline_outcome=PipelineOutcome.NO_SECURITY_EVALUATION,
            blocked_at_stage=None,
            completed_by=None,
            had_security_plugin=False,
            capture_content=True,
        )
        had_critical_error = False
        if not plugins:
            pipeline.final_content = response
            return pipeline

        server_label = server_name if server_name else "unknown"
        logger.debug(
            f"Direct server response filtering for server '{server_label}': {[(getattr(p, 'plugin_id', p.__class__.__name__), getattr(p, 'priority', 50)) for p in plugins]}"
        )

        # For tools/list responses, ensure plugins see clean tools even if response is pre-namespaced
        if (
            request.method == "tools/list"
            and server_name
            and response.result
            and "tools" in response.result
        ):
            from gatekit.utils.namespacing import (
                denamespace_tools_response,
                namespace_tools_response,
            )

            tools_list = response.result["tools"]
            # Check if tools are already namespaced (from broadcast aggregation)
            if any(
                isinstance(tool, dict)
                and "name" in tool
                and isinstance(tool["name"], str)
                and "__" in tool["name"]
                for tool in tools_list
            ):
                logger.debug(f"De-namespacing tools for server {server_name}")
                # Tools are namespaced, need to extract just this server's tools
                tools_by_server = denamespace_tools_response(tools_list)
                clean_tools = tools_by_server.get(server_name, [])

                # Create clean response for plugin processing
                current_response = MCPResponse(
                    jsonrpc=response.jsonrpc,
                    id=response.id,
                    result={**response.result, "tools": clean_tools},
                    error=response.error,
                    sender_context=response.sender_context,
                )
                # Mark as denamespaced so we can re-namespace the result
                current_response._was_denamespaced = True
            else:
                # Tools are already clean
                current_response = response
        else:
            # Process through all security plugins in priority order
            current_response = response
        current_response = current_response
        start_time = time.monotonic()
        for plugin in plugins:
            stage_start = time.monotonic()
            plugin_name = getattr(plugin, "plugin_id", plugin.__class__.__name__)
            input_content = current_response
            outcome = StageOutcome.ALLOWED
            error_type = None
            try:
                result = await self._execute_plugin_check(
                    plugin,
                    "process_response",
                    request,
                    current_response,
                    server_name=server_name,
                )
                result = self._enforce_plugin_contracts(plugin, result)
                if isinstance(plugin, SecurityPlugin):
                    pipeline.had_security_plugin = True
                    if result.allowed is False:
                        outcome = StageOutcome.BLOCKED
                    elif (
                        result.allowed is True
                        and pipeline.pipeline_outcome
                        == PipelineOutcome.NO_SECURITY_EVALUATION
                    ):
                        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
                if result.completed_response:
                    outcome = StageOutcome.COMPLETED_BY_MIDDLEWARE
                elif result.modified_content:
                    outcome = StageOutcome.MODIFIED
            except Exception as e:
                error_type = type(e).__name__
                outcome = StageOutcome.ERROR
                result = PluginResult(
                    allowed=False, reason=str(e), metadata={"plugin": plugin_name}
                )
                if isinstance(plugin, SecurityPlugin):
                    pipeline.had_security_plugin = True

                # Check if plugin is critical to determine handling
                if hasattr(plugin, "is_critical") and not plugin.is_critical():
                    # Non-critical plugin failure: log warning but continue processing
                    logger.warning(
                        f"Non-critical plugin {plugin_name} failed during response processing: {e}"
                    )
                else:
                    # Critical plugin failure: ensure processing stops
                    logger.error(
                        f"Critical plugin {plugin_name} failed during response processing: {e}",
                        exc_info=True,
                    )
                    had_critical_error = True
            stage_end = time.monotonic()
            elapsed_ms = (stage_end - stage_start) * 1000
            output_content = None
            if result.modified_content and isinstance(
                result.modified_content, MCPResponse
            ):
                output_content = result.modified_content
                current_response = result.modified_content
            elif result.completed_response:
                output_content = result.completed_response
            content_hash = hashlib.blake2s(
                str(input_content).encode(), digest_size=8
            ).hexdigest()
            stage = PipelineStage(
                plugin_name=plugin_name,
                plugin_type=(
                    "security" if isinstance(plugin, SecurityPlugin) else "middleware"
                ),
                input_content=input_content,
                output_content=output_content,
                content_hash=content_hash,
                result=result,
                processing_time_ms=elapsed_ms,
                outcome=outcome,
                error_type=error_type,
                security_evaluated=isinstance(plugin, SecurityPlugin),
            )
            pipeline.add_stage(stage)
            if isinstance(plugin, SecurityPlugin):
                if result.allowed is False or result.modified_content is not None:
                    pipeline.capture_content = False
            if outcome == StageOutcome.BLOCKED:
                pipeline.final_content = (
                    current_response
                    if not result.completed_response
                    else result.completed_response
                )
                break
            if outcome == StageOutcome.COMPLETED_BY_MIDDLEWARE:
                pipeline.final_content = result.completed_response
                break
            if outcome == StageOutcome.ERROR:
                pipeline.final_content = (
                    current_response
                    if not result.completed_response
                    else result.completed_response
                )
                # Only break for critical plugin errors
                if not hasattr(plugin, "is_critical") or plugin.is_critical():
                    break
        if pipeline.final_content is None:
            pipeline.final_content = current_response
        end_time = time.monotonic()
        pipeline.total_time_ms = (end_time - start_time) * 1000
        # Set final pipeline outcome (for deferred outcomes)
        if had_critical_error:
            pipeline.pipeline_outcome = PipelineOutcome.ERROR
        elif pipeline.pipeline_outcome not in (
            PipelineOutcome.BLOCKED,
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
        ):
            # Only set deferred outcomes if no immediate outcome was already set
            # Check if any stage modified content
            has_modifications = any(
                stage.outcome == StageOutcome.MODIFIED for stage in pipeline.stages
            )
            if has_modifications:
                pipeline.pipeline_outcome = PipelineOutcome.MODIFIED
            elif (
                pipeline.had_security_plugin
                and pipeline.pipeline_outcome != PipelineOutcome.ALLOWED
            ):
                # This shouldn't happen as ALLOWED is set immediately, but keep for safety
                pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        if not pipeline.capture_content:
            for s in pipeline.stages:
                s.input_content = None
                s.output_content = None
                if s.result and s.result.reason:
                    s.result.reason = f"[{s.outcome.value}]"
        # Re-namespace tools if needed (mirror original logic)
        if (
            request.method == "tools/list"
            and server_name
            and hasattr(current_response, "_was_denamespaced")
            and current_response._was_denamespaced
        ):
            from gatekit.utils.namespacing import namespace_tools_response

            if (
                isinstance(pipeline.final_content, MCPResponse)
                and pipeline.final_content.result
                and "tools" in pipeline.final_content.result
            ):
                clean_tools = pipeline.final_content.result["tools"]
                namespaced_tools = namespace_tools_response(server_name, clean_tools)
                pipeline.final_content = MCPResponse(
                    jsonrpc=pipeline.final_content.jsonrpc,
                    id=pipeline.final_content.id,
                    result={**pipeline.final_content.result, "tools": namespaced_tools},
                    error=pipeline.final_content.error,
                    sender_context=pipeline.final_content.sender_context,
                )
        return pipeline

    async def _process_aggregated_tools_list_response(
        self, request: MCPRequest, response: MCPResponse
    ) -> ProcessingPipeline:
        """Process aggregated tools/list response by grouping tools by server and processing each group.

        This method handles tools/list responses that contain namespaced tools from multiple servers
        (or a single named server). It groups tools by server and processes each group with the
        appropriate server context.

        Args:
            request: The original MCP request
            response: The aggregated MCP response with namespaced tools

        Returns:
            ProcessingPipeline: Complete pipeline with stages from processing all tool groups
        """
        from gatekit.utils.namespacing import (
            denamespace_tools_response,
            namespace_tools_response,
        )

        # Create main pipeline for aggregated processing
        main_pipeline = ProcessingPipeline(
            original_content=response,
            stages=[],
            final_content=response,  # Start with original, will update if modified
            total_time_ms=0.0,
            pipeline_outcome=PipelineOutcome.NO_SECURITY_EVALUATION,
            blocked_at_stage=None,
            completed_by=None,
            had_security_plugin=False,
            capture_content=True,
        )

        # Validate response structure
        if not response.result or "tools" not in response.result:
            # No tools to process - return pipeline as-is
            return main_pipeline

        tools_list = response.result["tools"]
        if not isinstance(tools_list, list):
            # Malformed response - create error stage and return
            main_pipeline.pipeline_outcome = PipelineOutcome.ERROR
            error_stage = PipelineStage(
                plugin_name="aggregated_validation",
                plugin_type="internal",
                input_content=response,
                output_content=response,
                content_hash="",
                result=PluginResult(
                    allowed=False,
                    reason="Malformed tools/list response: tools field is not an array",
                ),
                processing_time_ms=0.0,
                outcome=StageOutcome.ERROR,
                security_evaluated=False,
            )
            main_pipeline.add_stage(error_stage)
            return main_pipeline

        # Group tools by server using utility function
        tools_by_server = denamespace_tools_response(tools_list)

        # Process each server's tools through plugins
        final_tools = []
        start_time = time.monotonic()

        # Track outcomes from all servers
        blocked_servers = []
        servers_with_modifications = []
        servers_with_security = []
        total_servers = len(tools_by_server)

        for server_name, clean_tools in tools_by_server.items():
            # Create a temporary response for this server's tools
            temp_response = MCPResponse(
                jsonrpc=response.jsonrpc,
                id=response.id,
                result={"tools": clean_tools},
                error=response.error,
                sender_context=response.sender_context,
            )

            # Process through normal single-server path to get proper stages
            server_pipeline = await self._process_single_server_response(
                request, temp_response, server_name
            )

            # Merge server pipeline into main pipeline
            main_pipeline.stages.extend(server_pipeline.stages)
            main_pipeline.total_time_ms += server_pipeline.total_time_ms

            # Update had_security_plugin flag
            if server_pipeline.had_security_plugin:
                main_pipeline.had_security_plugin = True

            # Handle different pipeline outcomes
            if server_pipeline.pipeline_outcome == PipelineOutcome.BLOCKED:
                # This server is blocked - skip its tools but continue with other servers
                blocked_servers.append(server_name)
                logger.info(
                    f"Server {server_name} blocked - skipping its tools but continuing with other servers"
                )
                continue  # Don't break! Process other servers

            elif (
                server_pipeline.pipeline_outcome
                == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
            ):
                # Middleware completed - this is a global action, stop everything
                main_pipeline.pipeline_outcome = PipelineOutcome.COMPLETED_BY_MIDDLEWARE
                main_pipeline.completed_by = server_pipeline.completed_by
                main_pipeline.final_content = server_pipeline.final_content
                logger.info(
                    f"Aggregated response completed by middleware for server {server_name}"
                )
                return main_pipeline

            elif server_pipeline.pipeline_outcome == PipelineOutcome.ERROR:
                # Critical error for this server - log but continue with others
                # (unless we want to be strict about errors)
                logger.error(
                    f"Critical error processing server {server_name} - continuing with other servers"
                )
                blocked_servers.append(server_name)  # Treat as blocked for safety
                continue

            elif server_pipeline.pipeline_outcome == PipelineOutcome.MODIFIED:
                servers_with_modifications.append(server_name)
                if server_pipeline.had_security_plugin:
                    servers_with_security.append(server_name)

            elif server_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED:
                if server_pipeline.had_security_plugin:
                    servers_with_security.append(server_name)

            # Collect the filtered tools from non-blocked servers
            if (
                server_pipeline.final_content
                and server_pipeline.final_content.result
                and "tools" in server_pipeline.final_content.result
            ):
                filtered_clean_tools = server_pipeline.final_content.result["tools"]
                if server_name:
                    # Re-namespace the tools for the final response
                    namespaced_tools = namespace_tools_response(
                        server_name, filtered_clean_tools
                    )
                    final_tools.extend(namespaced_tools)
                else:
                    # No namespacing needed for tools without server context
                    final_tools.extend(filtered_clean_tools)

        # Determine aggregate pipeline outcome based on all servers
        if total_servers > 0 and len(blocked_servers) == total_servers:
            # All servers blocked - this is a full block
            main_pipeline.pipeline_outcome = PipelineOutcome.BLOCKED
            # Set blocked_at_stage to the first blocking plugin found in stages
            for stage in main_pipeline.stages:
                if stage.outcome == StageOutcome.BLOCKED:
                    main_pipeline.blocked_at_stage = stage.plugin_name
                    break
            logger.warning("All servers blocked in aggregated response")
        elif blocked_servers or servers_with_modifications:
            # Some servers blocked or modified - mark as modified
            main_pipeline.pipeline_outcome = PipelineOutcome.MODIFIED
            if blocked_servers:
                logger.info(
                    f"Blocked servers: {blocked_servers}, continuing with tools from other servers"
                )
        elif servers_with_security:
            # Had security evaluation and all allowed
            main_pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        else:
            # No security evaluation
            main_pipeline.pipeline_outcome = PipelineOutcome.NO_SECURITY_EVALUATION

        # Create final response with combined tools from non-blocked servers
        main_pipeline.final_content = MCPResponse(
            jsonrpc=response.jsonrpc,
            id=response.id,
            result={**response.result, "tools": final_tools},
            error=response.error,
            sender_context=response.sender_context,
        )

        # Update total processing time
        main_pipeline.total_time_ms = (time.monotonic() - start_time) * 1000

        return main_pipeline

    async def process_notification(
        self, notification: MCPNotification, server_name: Optional[str] = None
    ) -> ProcessingPipeline:
        """Run notification through upstream-scoped security plugins.

        Processes the notification through security plugins for the specified upstream.
        Combines global (_global) plugins with upstream-specific plugins, where
        upstream-specific plugins override global ones with the same handler name.

        Args:
            notification: The MCP notification to evaluate
            server_name: Optional name of the source server

        Returns:
            PluginResult: Combined decision from plugins for the upstream
        """
        if not self._initialized:
            await self.load_plugins()

        # Get combined pipeline of middleware and security plugins
        plugins = self._get_processing_pipeline(server_name or "unknown")
        pipeline = ProcessingPipeline(
            original_content=notification,
            stages=[],
            final_content=None,
            total_time_ms=0.0,
            pipeline_outcome=PipelineOutcome.NO_SECURITY_EVALUATION,
            blocked_at_stage=None,
            completed_by=None,
            had_security_plugin=False,
            capture_content=True,
        )
        had_critical_error = False
        if not plugins:
            pipeline.final_content = notification
            return pipeline

        # Log the plugin execution order at debug level
        plugin_info = [
            (getattr(p, "plugin_id", p.__class__.__name__), getattr(p, "priority", 50))
            for p in plugins
        ]
        logger.debug(
            f"Notification plugin execution order for upstream '{server_name}': {plugin_info}"
        )

        # Process through all security plugins in priority order
        # Track notification modifications
        current_notification = notification
        start_time = time.monotonic()
        for plugin in plugins:
            stage_start = time.monotonic()
            plugin_name = getattr(plugin, "plugin_id", plugin.__class__.__name__)
            input_content = current_notification
            outcome = StageOutcome.ALLOWED
            error_type = None
            try:
                result = await self._execute_plugin_check(
                    plugin,
                    "process_notification",
                    current_notification,
                    server_name=server_name,
                )
                result = self._enforce_plugin_contracts(plugin, result)
                if isinstance(plugin, SecurityPlugin):
                    pipeline.had_security_plugin = True
                    if result.allowed is False:
                        outcome = StageOutcome.BLOCKED
                    elif (
                        result.allowed is True
                        and pipeline.pipeline_outcome
                        == PipelineOutcome.NO_SECURITY_EVALUATION
                    ):
                        pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
                if result.completed_response:
                    outcome = StageOutcome.COMPLETED_BY_MIDDLEWARE
                elif result.modified_content:
                    outcome = StageOutcome.MODIFIED
            except Exception as e:
                error_type = type(e).__name__
                outcome = StageOutcome.ERROR
                result = PluginResult(
                    allowed=False, reason=str(e), metadata={"plugin": plugin_name}
                )
                if isinstance(plugin, SecurityPlugin):
                    pipeline.had_security_plugin = True

                # Check if plugin is critical to determine handling
                if hasattr(plugin, "is_critical") and not plugin.is_critical():
                    # Non-critical plugin failure: log warning but continue processing
                    logger.warning(
                        f"Non-critical plugin {plugin_name} failed during notification processing: {e}"
                    )
                else:
                    # Critical plugin failure: ensure processing stops
                    logger.error(
                        f"Critical plugin {plugin_name} failed during notification processing: {e}",
                        exc_info=True,
                    )
                    had_critical_error = True
            stage_end = time.monotonic()
            elapsed_ms = (stage_end - stage_start) * 1000
            output_content = None
            if result.modified_content and isinstance(
                result.modified_content, MCPNotification
            ):
                output_content = result.modified_content
                current_notification = result.modified_content
            elif result.completed_response:
                output_content = result.completed_response
            content_hash = hashlib.blake2s(
                str(input_content).encode(), digest_size=8
            ).hexdigest()
            stage = PipelineStage(
                plugin_name=plugin_name,
                plugin_type=(
                    "security" if isinstance(plugin, SecurityPlugin) else "middleware"
                ),
                input_content=input_content,
                output_content=output_content,
                content_hash=content_hash,
                result=result,
                processing_time_ms=elapsed_ms,
                outcome=outcome,
                error_type=error_type,
                security_evaluated=isinstance(plugin, SecurityPlugin),
            )
            pipeline.add_stage(stage)
            if isinstance(plugin, SecurityPlugin):
                if result.allowed is False or result.modified_content is not None:
                    pipeline.capture_content = False
            if outcome == StageOutcome.BLOCKED:
                pipeline.final_content = (
                    current_notification
                    if not result.completed_response
                    else result.completed_response
                )
                break
            if outcome == StageOutcome.COMPLETED_BY_MIDDLEWARE:
                pipeline.final_content = result.completed_response
                break
            if outcome == StageOutcome.ERROR:
                pipeline.final_content = (
                    current_notification
                    if not result.completed_response
                    else result.completed_response
                )
                # Only break for critical plugin errors
                if not hasattr(plugin, "is_critical") or plugin.is_critical():
                    break
        end_time = time.monotonic()
        pipeline.total_time_ms = (end_time - start_time) * 1000
        if pipeline.final_content is None:
            pipeline.final_content = current_notification
        # Set final pipeline outcome (for deferred outcomes)
        if had_critical_error:
            pipeline.pipeline_outcome = PipelineOutcome.ERROR
        elif pipeline.pipeline_outcome not in (
            PipelineOutcome.BLOCKED,
            PipelineOutcome.COMPLETED_BY_MIDDLEWARE,
        ):
            # Only set deferred outcomes if no immediate outcome was already set
            # Check if any stage modified content
            has_modifications = any(
                stage.outcome == StageOutcome.MODIFIED for stage in pipeline.stages
            )
            if has_modifications:
                pipeline.pipeline_outcome = PipelineOutcome.MODIFIED
            elif (
                pipeline.had_security_plugin
                and pipeline.pipeline_outcome != PipelineOutcome.ALLOWED
            ):
                # This shouldn't happen as ALLOWED is set immediately, but keep for safety
                pipeline.pipeline_outcome = PipelineOutcome.ALLOWED
        if not pipeline.capture_content:
            for s in pipeline.stages:
                s.input_content = None
                s.output_content = None
                if s.result and s.result.reason:
                    s.result.reason = f"[{s.outcome.value}]"
        return pipeline

    async def log_request(
        self,
        request: MCPRequest,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        """Send request to upstream-scoped auditing plugins sequentially.

        Audit plugins execute in the order they're defined (not by priority).
        Failures are logged but don't block processing or other audit plugins.

        Args:
            request: The MCP request being processed
            decision: The security handler decision for this request
            server_name: Name of the target upstream server
        """
        if not self._initialized:
            await self.load_plugins()

        # Get upstream-specific auditing plugins (no sorting needed)
        upstream_plugins = self.get_plugins_for_upstream(server_name or "unknown")
        auditing_plugins = upstream_plugins["auditing"]

        # Add upstream context to decision metadata
        # (Backward compat metadata no longer needed; pipeline carries data)

        # Execute sequentially in definition order
        for plugin in auditing_plugins:
            try:
                await plugin.log_request(request, pipeline, server_name=server_name)
                logger.debug(
                    f"Auditing plugin {plugin.plugin_id} logged request for upstream '{server_name}'"
                )
            except Exception as e:
                # Check if this is a critical audit plugin
                if plugin.is_critical():
                    # Critical audit failures should halt processing
                    logger.error(
                        f"Critical auditing plugin {plugin.plugin_id} failed to log request for upstream '{server_name}': {e}",
                        exc_info=True,
                        extra={
                            "event_type": "critical_audit_failure",
                            "audit_plugin": plugin.plugin_id,
                            "upstream": server_name,
                            "operation": "log_request",
                        },
                    )
                    raise AuditingFailureError(
                        f"Critical auditing plugin {plugin.plugin_id} failed: {str(e)}"
                    )
                else:
                    # Non-critical auditing failures are logged but don't block processing
                    logger.error(
                        f"Auditing plugin {plugin.plugin_id} failed to log request for upstream '{server_name}': {e}",
                        exc_info=True,
                    )

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        """Send response to upstream-scoped auditing plugins in definition order.

        Sends the request, response, and security decision to auditing plugins
        configured for the specified upstream. Plugins execute in the order they
        are defined (not by priority).

        Args:
            request: The original MCP request for correlation
            response: The MCP response from the upstream server
            decision: The handler decision made by security plugins for this response
            server_name: Name of the source upstream server
        """
        if not self._initialized:
            await self.load_plugins()

        # Get upstream-specific auditing plugins
        upstream_plugins = self.get_plugins_for_upstream(server_name or "unknown")
        auditing_plugins = upstream_plugins["auditing"]

        # Add upstream context to decision metadata
        # Upstream context in pipeline only

        # Send to all auditing plugins for this upstream in definition order
        for plugin in auditing_plugins:
            try:
                await plugin.log_response(
                    request, response, pipeline, server_name=server_name
                )
                logger.debug(
                    f"Auditing plugin {plugin.plugin_id} logged response for upstream '{server_name}'"
                )
            except Exception as e:
                # Check if this is a critical audit plugin
                if plugin.is_critical():
                    # Critical audit failures should halt processing
                    logger.error(
                        f"Critical auditing plugin {plugin.plugin_id} failed to log response for upstream '{server_name}': {e}",
                        exc_info=True,
                        extra={
                            "event_type": "critical_audit_failure",
                            "audit_plugin": plugin.plugin_id,
                            "upstream": server_name,
                            "operation": "log_response",
                        },
                    )
                    raise AuditingFailureError(
                        f"Critical auditing plugin {plugin.plugin_id} failed: {str(e)}"
                    )
                else:
                    # Non-critical auditing failures are logged but don't block processing
                    logger.error(
                        f"Auditing plugin {plugin.plugin_id} failed to log response for upstream '{server_name}': {e}",
                        exc_info=True,
                    )

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        """Send notification to upstream-scoped auditing plugins in definition order.

        Sends the notification and handler decision to auditing plugins configured
        for the specified upstream. Plugins execute in the order they are defined
        (not by priority).

        Args:
            notification: The MCP notification being processed
            decision: The handler decision from security plugins
            server_name: Optional name of the source server
        """
        if not self._initialized:
            await self.load_plugins()

        # Get upstream-specific auditing plugins
        upstream_plugins = self.get_plugins_for_upstream(server_name or "unknown")
        auditing_plugins = upstream_plugins["auditing"]

        # Add upstream context to decision metadata
        # Upstream context in pipeline only

        # Send to all auditing plugins for this upstream in definition order
        for plugin in auditing_plugins:
            try:
                await plugin.log_notification(
                    notification, pipeline, server_name=server_name
                )
                logger.debug(
                    f"Auditing plugin {plugin.plugin_id} logged notification for upstream '{server_name}'"
                )
            except Exception as e:
                # Check if this is a critical audit plugin
                if plugin.is_critical():
                    # Critical audit failures should halt processing
                    plugin_id = getattr(plugin, "plugin_id", plugin.__class__.__name__)
                    logger.error(
                        f"Critical auditing plugin {plugin_id} failed to log notification for upstream '{server_name}': {e}",
                        exc_info=True,
                        extra={
                            "event_type": "critical_audit_failure",
                            "audit_plugin": plugin_id,
                            "upstream": server_name,
                            "operation": "log_notification",
                        },
                    )
                    raise AuditingFailureError(
                        f"Critical auditing plugin {plugin_id} failed: {str(e)}"
                    )
                else:
                    # Non-critical auditing failures are logged but don't block processing
                    logger.error(
                        f"Auditing plugin {getattr(plugin, 'plugin_id', plugin.__class__.__name__)} failed to log notification for upstream '{server_name}': {e}",
                        exc_info=True,
                    )

    def _create_plugin_instance(
        self,
        plugin_class,
        plugin_config: Dict[str, Any],
        handler_name: str,
        plugin_type: str,
    ):
        """Create a plugin instance with proper configuration and validation.

        Args:
            plugin_class: The plugin class to instantiate
            plugin_config: Plugin configuration dictionary
            handler_name: Name of the handler
            plugin_type: Type of plugin ("security", "auditing", or "middleware")

        Returns:
            Plugin instance or None if creation failed
        """
        # Validate plugin interface
        self._validate_plugin_interface(plugin_type, plugin_class, handler_name)

        # Create plugin instance with original config (no config_directory injection)
        plugin_config_dict = plugin_config.get("config", {}).copy()

        # Include priority in the config passed to security and middleware plugins
        # Read from nested config dict (consolidated format)
        config_dict = plugin_config.get("config", {})
        if "priority" in config_dict:
            if plugin_type == "auditing":
                # Log warning once per handler if priority specified for audit plugin
                if handler_name not in getattr(self, "_audit_priority_warned", set()):
                    logger.warning(
                        f"Priority field ignored for audit plugin '{handler_name}' - "
                        "audit plugins execute in definition order"
                    )
                    if not hasattr(self, "_audit_priority_warned"):
                        self._audit_priority_warned = set()
                    self._audit_priority_warned.add(handler_name)
            else:
                # Security and middleware plugins use priority
                plugin_config_dict["priority"] = config_dict["priority"]

        # Include critical setting for both security and auditing plugins
        # Read from nested config dict (consolidated format)
        if "critical" in config_dict:
            plugin_config_dict["critical"] = config_dict["critical"]

        plugin_instance = plugin_class(plugin_config_dict)

        # Set handler name for tracking
        plugin_instance.handler = handler_name

        # For auditing plugins, ensure no priority attribute exists
        # (even if a badly written plugin sets it internally)
        if plugin_type == "auditing" and hasattr(plugin_instance, "priority"):
            delattr(plugin_instance, "priority")
            logger.debug(
                f"Removed priority attribute from auditing plugin '{handler_name}'."
            )

        # Handle PathResolvablePlugin interface
        if isinstance(plugin_instance, PathResolvablePlugin):
            # Set config directory if available
            if self.config_directory is not None:
                plugin_instance.set_config_directory(self.config_directory)
                logger.debug(
                    f"Set config directory for {plugin_type} plugin {handler_name}: {self.config_directory}"
                )

            # Always validate paths, even without config_directory
            # (plugin may use absolute paths)
            path_errors = plugin_instance.validate_paths()
            if path_errors:
                # Check if plugin is critical to determine error handling
                is_critical = plugin_config_dict.get("critical", True)
                if is_critical:
                    raise ValueError(
                        f"{plugin_type.capitalize()} plugin '{handler_name}' path validation failed: "
                        + "; ".join(path_errors)
                    )
                else:
                    # For non-critical plugins, log warning but continue
                    logger.warning(
                        f"Non-critical {plugin_type} plugin '{handler_name}' has path validation errors: {'; '.join(path_errors)}"
                    )

        return plugin_instance

    def _load_upstream_scoped_security_plugins(
        self, security_config: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Load security plugins from upstream-scoped configuration.

        Args:
            security_config: Dictionary mapping upstream names to lists of security plugin configurations
        """
        # Clear existing plugins
        self.upstream_security_plugins.clear()

        if not security_config:
            logger.info("No security plugin configuration found")
            return

        # Discover available security handlers
        available_handlers = self._discover_handlers("security")

        for upstream_name, plugin_configs in security_config.items():
            logger.debug(f"Loading security plugins for upstream '{upstream_name}'")
            upstream_plugins = []

            for plugin_config in plugin_configs:
                # Read enabled from nested config dict (consolidated format)
                if not plugin_config.get("config", {}).get("enabled", True):
                    logger.debug(
                        f"Skipping disabled security plugin: {plugin_config.get('handler', 'unknown')}"
                    )
                    continue

                handler_name = plugin_config.get("handler")
                if not handler_name:
                    logger.error(
                        f"Security plugin configuration missing 'handler' field for upstream '{upstream_name}'"
                    )
                    continue

                if handler_name not in available_handlers:
                    available_names = ", ".join(available_handlers.keys())
                    raise ValueError(
                        f"Handler '{handler_name}' not found. Available handlers: {available_names}"
                    )

                try:
                    plugin_class = available_handlers[handler_name]
                    plugin_instance = self._create_plugin_instance(
                        plugin_class, plugin_config, handler_name, "security"
                    )
                    if plugin_instance:
                        upstream_plugins.append(plugin_instance)
                        logger.debug(
                            f"Loaded security plugin '{handler_name}' for upstream '{upstream_name}'"
                        )
                except Exception as e:
                    # Check if this is a critical security plugin (read from nested config dict)
                    # All plugins default to critical=True (fail closed)
                    is_critical = plugin_config.get("config", {}).get("critical", True)
                    if is_critical:
                        # Critical security plugin initialization failure should halt the system
                        logger.exception(
                            f"Critical security plugin '{handler_name}' failed to initialize for upstream '{upstream_name}': {e}"
                        )
                        raise
                    else:
                        # Non-critical security plugin failure: log error and continue
                        logger.exception(
                            f"Failed to load security plugin '{handler_name}' for upstream '{upstream_name}': {e}"
                        )
                        self._load_failures.append(
                            {
                                "type": "security",
                                "handler": handler_name,
                                "upstream": upstream_name,
                                "error": str(e),
                            }
                        )

            # Sort plugins by priority (lower number = higher priority)
            upstream_plugins.sort(key=lambda p: getattr(p, "priority", 50))
            self.upstream_security_plugins[upstream_name] = upstream_plugins

            logger.info(
                f"Loaded {len(upstream_plugins)} security plugins for upstream '{upstream_name}'"
            )

    def _load_upstream_scoped_auditing_plugins(
        self, auditing_config: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Load auditing plugins from upstream-scoped configuration.

        Args:
            auditing_config: Dictionary mapping upstream names to lists of auditing plugin configurations
        """
        # Clear existing plugins
        self.upstream_auditing_plugins.clear()

        if not auditing_config:
            logger.info("No auditing plugin configuration found")
            return

        # Discover available auditing handlers
        available_handlers = self._discover_handlers("auditing")

        for upstream_name, plugin_configs in auditing_config.items():
            logger.debug(f"Loading auditing plugins for upstream '{upstream_name}'")
            upstream_plugins = []

            for plugin_config in plugin_configs:
                # Read enabled from nested config dict (consolidated format)
                if not plugin_config.get("config", {}).get("enabled", True):
                    logger.debug(
                        f"Skipping disabled auditing plugin: {plugin_config.get('handler', 'unknown')}"
                    )
                    continue

                handler_name = plugin_config.get("handler")
                if not handler_name:
                    logger.error(
                        f"Auditing plugin configuration missing 'handler' field for upstream '{upstream_name}'"
                    )
                    continue

                if handler_name not in available_handlers:
                    available_names = ", ".join(available_handlers.keys())
                    raise ValueError(
                        f"Handler '{handler_name}' not found. Available handlers: {available_names}"
                    )

                try:
                    plugin_class = available_handlers[handler_name]
                    plugin_instance = self._create_plugin_instance(
                        plugin_class, plugin_config, handler_name, "auditing"
                    )
                    if plugin_instance:
                        upstream_plugins.append(plugin_instance)
                        logger.debug(
                            f"Loaded auditing plugin '{handler_name}' for upstream '{upstream_name}'"
                        )
                except Exception as e:
                    # Check if this is a critical audit plugin (read from nested config dict)
                    # All plugins default to critical=True (fail closed)
                    is_critical = plugin_config.get("config", {}).get("critical", True)
                    if is_critical:
                        # Critical audit plugin initialization failure should halt the system
                        logger.exception(
                            f"Critical auditing plugin '{handler_name}' failed to initialize for upstream '{upstream_name}': {e}"
                        )
                        raise
                    else:
                        # Non-critical audit plugin failure: log error and continue
                        logger.exception(
                            f"Failed to load auditing plugin '{handler_name}' for upstream '{upstream_name}': {e}"
                        )
                        self._load_failures.append(
                            {
                                "type": "auditing",
                                "handler": handler_name,
                                "upstream": upstream_name,
                                "error": str(e),
                            }
                        )

            # Note: Auditing plugins are NOT sorted by priority as their order doesn't matter
            # They execute in the order they are defined
            self.upstream_auditing_plugins[upstream_name] = upstream_plugins

            logger.info(
                f"Loaded {len(upstream_plugins)} auditing plugins for upstream '{upstream_name}'"
            )

    def _load_upstream_scoped_middleware_plugins(
        self, middleware_config: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """Load middleware plugins from upstream-scoped configuration.

        Args:
            middleware_config: Dictionary mapping upstream names to middleware plugin configs
        """
        self.upstream_middleware_plugins.clear()

        if not middleware_config:
            logger.info("No middleware plugin configuration found")
            return

        # Discover available middleware handlers
        available_handlers = self._discover_handlers("middleware")

        for upstream_name, plugin_configs in middleware_config.items():
            logger.debug(f"Loading middleware plugins for upstream '{upstream_name}'")
            upstream_plugins = []

            for plugin_config in plugin_configs:
                # Read enabled from nested config dict (consolidated format)
                if not plugin_config.get("config", {}).get("enabled", True):
                    logger.debug(
                        f"Skipping disabled middleware plugin: {plugin_config.get('handler', 'unknown')}"
                    )
                    continue

                handler_name = plugin_config.get("handler")
                if not handler_name and "policy" in plugin_config:
                    # Check for old format and provide helpful error
                    raise ValueError(
                        f"Configuration uses deprecated 'policy' field. "
                        f"Please update to 'handler': {plugin_config.get('policy')}"
                    )
                if not handler_name:
                    logger.error(
                        f"Middleware plugin configuration missing 'handler' field for upstream '{upstream_name}'"
                    )
                    continue

                if handler_name not in available_handlers:
                    available_names = ", ".join(available_handlers.keys())
                    raise ValueError(
                        f"Handler '{handler_name}' not found. Available handlers: {available_names}"
                    )

                try:
                    plugin_class = available_handlers[handler_name]
                    plugin_instance = self._create_plugin_instance(
                        plugin_class, plugin_config, handler_name, "middleware"
                    )
                    if plugin_instance:
                        upstream_plugins.append(plugin_instance)
                        logger.debug(
                            f"Loaded middleware plugin '{handler_name}' for upstream '{upstream_name}'"
                        )
                except Exception as e:
                    # Check if this is a critical middleware plugin (read from nested config dict)
                    # All plugins default to critical=True (fail closed)
                    is_critical = plugin_config.get("config", {}).get("critical", True)
                    if is_critical:
                        # Critical middleware plugin initialization failure should halt the system
                        logger.exception(
                            f"Critical middleware plugin '{handler_name}' failed to initialize for upstream '{upstream_name}': {e}"
                        )
                        raise
                    else:
                        # Non-critical middleware plugin failure: log error and continue
                        logger.exception(
                            f"Failed to load middleware plugin '{handler_name}' for upstream '{upstream_name}': {e}"
                        )
                        self._load_failures.append(
                            {
                                "type": "middleware",
                                "handler": handler_name,
                                "upstream": upstream_name,
                                "error": str(e),
                            }
                        )

            # Sort by priority (lower number = higher priority = runs first)
            upstream_plugins.sort(key=lambda p: getattr(p, "priority", 50))
            self.upstream_middleware_plugins[upstream_name] = upstream_plugins

            logger.info(
                f"Loaded {len(upstream_plugins)} middleware plugins for upstream '{upstream_name}'"
            )

    def _validate_plugin_interface(
        self, plugin_type: str, plugin_class: type, plugin_identifier: str
    ):
        """Validate that plugin class implements the correct interface.

        Args:
            plugin_type: Type of plugin ('security', 'auditing', or 'middleware')
            plugin_class: Plugin class to validate
            plugin_identifier: Plugin path for error messages
        """
        if plugin_type == "security" and not issubclass(plugin_class, SecurityPlugin):
            raise TypeError(
                f"Security plugin '{plugin_identifier}' must inherit from SecurityPlugin"
            )
        elif plugin_type == "auditing" and not issubclass(plugin_class, AuditingPlugin):
            raise TypeError(
                f"Auditing plugin '{plugin_identifier}' must inherit from AuditingPlugin"
            )
        elif plugin_type == "middleware" and not issubclass(
            plugin_class, MiddlewarePlugin
        ):
            raise TypeError(
                f"Middleware plugin '{plugin_identifier}' must inherit from MiddlewarePlugin"
            )

    def get_available_handlers(
        self,
        category: str,
        scope: Optional[str] = None,
        *,
        server_identity: Optional[str] = None,
        server_alias: Optional[str] = None,
    ) -> Dict[str, type]:
        """Get available handlers for a plugin category, with optional context filtering.

        Args:
            category: Plugin category ('security', 'auditing', or 'middleware')
            scope: Target scope requesting handlers. Use "_global" for global context,
                a specific server alias for server-level context, or ``None`` to
                retrieve all handlers without filtering.
            server_identity: MCP server name reported during initialize handshake.
                Used for server-specific compatibility checks when scope targets a
                particular server.
            server_alias: Friendly alias from configuration for the upstream server.
                Used as a fallback identifier when no handshake identity is known.

        Returns:
            Dict mapping handler names to plugin classes filtered for the context.
        """

        handlers = self._discover_handlers(category)

        # If no scope provided, return full discovery results (shallow copy)
        if scope is None:
            return handlers.copy()

        # Auditing handlers do not participate in scope filtering; return all
        if category == "auditing":
            return handlers.copy()

        filtered: Dict[str, type] = {}
        for handler_name, handler_class in handlers.items():
            if self._handler_is_available_for_scope(
                handler_class,
                scope=scope,
                server_identity=server_identity,
                server_alias=server_alias,
            ):
                filtered[handler_name] = handler_class

        return filtered

    def _handler_is_available_for_scope(
        self,
        handler_class: type,
        *,
        scope: str,
        server_identity: Optional[str],
        server_alias: Optional[str],
    ) -> bool:
        """Determine if a handler can be displayed/configured in the given scope."""

        display_scope = getattr(handler_class, "DISPLAY_SCOPE", "global")

        # Global scope only shows plugins explicitly marked as global
        if scope == "_global":
            return display_scope == "global"

        # For server-level scopes allow "global" (inherited) and "server_aware"
        if display_scope in {"global", "server_aware"}:
            return True

        if display_scope == "server_specific":
            compatible_servers = getattr(handler_class, "COMPATIBLE_SERVERS", None)
            if not compatible_servers:
                return False

            identity = server_identity or server_alias
            if not identity:
                return False

            return identity in compatible_servers

        # Unknown display scope values default to hidden for safety
        return False

    def _discover_handlers(self, category: str) -> Dict[str, type]:
        """Discover all handlers available in a plugin category.

        Internal method for handler discovery.

        Args:
            category: Plugin category ('security', 'auditing', or 'middleware')

        Returns:
            Dict mapping handler names to plugin classes
        """
        if category in self._handler_cache:
            return self._handler_cache[category].copy()

        handlers = {}

        # Determine the plugin directory to scan
        base_dir = Path(__file__).parent
        plugin_dir = base_dir / category

        if not plugin_dir.exists():
            logger.debug(f"Plugin directory not found: {plugin_dir}")
            return handlers

        # Scan all Python files in the category directory
        for py_file in plugin_dir.glob("**/*.py"):
            if not py_file.is_file() or py_file.name.startswith("__"):
                continue

            try:
                # Compute proper namespaced module name to avoid collisions
                # e.g., middleware/call_trace.py -> gatekit._plugins.middleware.call_trace
                relative_path = py_file.relative_to(base_dir)
                module_parts = relative_path.with_suffix('').parts
                module_name = f"gatekit._plugins.{'.'.join(module_parts)}"

                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                # Register in sys.modules before exec so inspect.getfile() works
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Check for HANDLERS manifest
                if hasattr(module, "HANDLERS") and isinstance(module.HANDLERS, dict):
                    for handler_name, handler_class in module.HANDLERS.items():
                        if not isinstance(handler_name, str):
                            logger.warning(
                                f"Invalid handler name type in {py_file}: {type(handler_name)}"
                            )
                            continue

                        if not callable(handler_class):
                            logger.warning(
                                f"Invalid handler class in {py_file}: {handler_class}"
                            )
                            continue

                        # Check for duplicate handler names
                        if handler_name in handlers:
                            logger.warning(
                                f"Duplicate handler name '{handler_name}' found in {py_file}"
                            )
                            continue

                        handlers[handler_name] = handler_class
                        logger.debug(
                            f"Discovered handler '{handler_name}' in {py_file}"
                        )

            except Exception as e:
                logger.debug(f"Failed to load module {py_file}: {e}")
                continue

        logger.info(f"Discovered {len(handlers)} handlers in {category} category")
        self._handler_cache[category] = handlers
        return handlers.copy()

    async def cleanup(self) -> None:
        """Cleanup plugin resources.

        This method safely cleans up all loaded plugins. Plugin cleanup failures
        are logged but don't prevent other plugins from being cleaned up.
        """
        logger.info("Cleaning up plugin manager")

        # Cleanup upstream-scoped plugins
        for upstream_name, plugins in self.upstream_security_plugins.items():
            for plugin in plugins:
                try:
                    if hasattr(plugin, "cleanup") and callable(
                        plugin.cleanup
                    ):
                        await plugin.cleanup()
                except Exception as e:
                    logger.warning(
                        f"Error cleaning up security plugin {plugin.__class__.__name__} for upstream {upstream_name}: {e}"
                    )

        for upstream_name, plugins in self.upstream_auditing_plugins.items():
            for plugin in plugins:
                try:
                    if hasattr(plugin, "cleanup") and callable(
                        plugin.cleanup
                    ):
                        plugin.cleanup()
                except Exception as e:
                    logger.warning(
                        f"Error cleaning up auditing plugin {plugin.__class__.__name__} for upstream {upstream_name}: {e}"
                    )

        logger.info("Plugin manager cleanup completed")

    def register_security_plugin(self, plugin: SecurityPlugin) -> None:
        """Register a security plugin with validation."""
        self._validate_plugin_priority(plugin)
        if "_global" not in self.upstream_security_plugins:
            self.upstream_security_plugins["_global"] = []
        self.upstream_security_plugins["_global"].append(plugin)
        # Sort immediately after adding to maintain priority order
        self.upstream_security_plugins["_global"].sort(
            key=lambda p: getattr(p, "priority", 50)
        )
        logger.info(
            f"Registered security plugin: {plugin.plugin_id} with priority {plugin.priority}"
        )

    def register_auditing_plugin(self, plugin: AuditingPlugin) -> None:
        """Register an auditing plugin (no priority validation needed)."""
        # Audit plugins don't have priority - they execute in definition order

        if "_global" not in self.upstream_auditing_plugins:
            self.upstream_auditing_plugins["_global"] = []
        self.upstream_auditing_plugins["_global"].append(plugin)
        # No sorting - audit plugins maintain registration order
        logger.info(f"Registered auditing plugin: {plugin.plugin_id}")

    def _validate_plugin_priority(self, plugin) -> None:
        """Validate plugin priority is in valid range.

        Args:
            plugin: The plugin to validate

        Raises:
            ValueError: If priority is not in 0-100 range
        """
        if not hasattr(plugin, "priority") or not isinstance(plugin.priority, int):
            raise PluginValidationError(
                f"Plugin {plugin.plugin_id} must have an integer priority attribute"
            )

        if not 0 <= plugin.priority <= 100:
            raise ValueError(
                f"Plugin {plugin.plugin_id} priority {plugin.priority} must be between 0 and 100"
            )

    def _sort_plugins_by_priority(self, plugins: List) -> List:
        """Sort plugins by priority (0-100, lower numbers = higher priority).

        Args:
            plugins: List of plugins to sort

        Returns:
            List of plugins sorted by priority (ascending - lower numbers first)
        """
        return sorted(plugins, key=lambda p: getattr(p, "priority", 50))

    def get_plugin_enablement_summary(
        self, plugin_handler: str, plugin_type: str = "security"
    ) -> Dict[str, Any]:
        """Get enablement summary for a plugin across all upstream servers.

        This is useful for TUI display to show which servers a plugin is enabled on.

        Args:
            plugin_handler: The handler name (e.g., "basic_pii_filter", "tool_manager")
            plugin_type: Plugin type - "security" or "auditing"

        Returns:
            Dict containing:
            - total_servers: Total number of configured upstream servers
            - enabled_servers: List of server names where plugin is enabled
            - disabled_servers: List of server names where plugin is disabled
            - global_enabled: Whether plugin is enabled in _global section
            - server_overrides: Dict of server_name -> config for servers with overrides
            - effective_config: Summary of effective configuration per server
        """
        if not self._initialized:
            return {
                "total_servers": 0,
                "enabled_servers": [],
                "disabled_servers": [],
                "global_enabled": False,
                "server_overrides": {},
                "effective_config": {},
            }

        # Get the appropriate plugins dict
        if plugin_type == "security":
            plugins_dict = self.upstream_security_plugins
        elif plugin_type == "auditing":
            plugins_dict = self.upstream_auditing_plugins
        else:
            raise PluginValidationError("plugin_type must be 'security' or 'auditing'")

        # Get all configured upstream server names (excluding _global)
        all_servers = set()
        for upstream_name in plugins_dict.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        # Also consider servers that might be in the config but not have plugins yet
        # We need to get this from the original config
        security_config = self.plugins_config.get("security", {})
        auditing_config = self.plugins_config.get("auditing", {})

        for upstream_name in security_config.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        for upstream_name in auditing_config.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        # Check global configuration
        global_enabled = False
        global_plugins = plugins_dict.get("_global", [])
        for plugin in global_plugins:
            plugin_name = getattr(plugin, "handler", plugin.__class__.__name__)
            if plugin_name == plugin_handler:
                global_enabled = getattr(plugin, "enabled", True)
                getattr(plugin, "config", {})
                break

        # Check each server's effective configuration
        enabled_servers = []
        disabled_servers = []
        server_overrides = {}
        effective_config = {}

        for server_name in all_servers:
            # Get effective plugins for this server
            server_plugins = self._resolve_plugins_for_upstream(
                plugins_dict, server_name
            )

            # Find our plugin in the effective configuration
            plugin_found = False
            for plugin in server_plugins:
                plugin_name = getattr(plugin, "handler", plugin.__class__.__name__)
                if plugin_name == plugin_handler:
                    plugin_found = True
                    enabled = getattr(plugin, "enabled", True)
                    config = getattr(plugin, "config", {})

                    if enabled:
                        enabled_servers.append(server_name)
                    else:
                        disabled_servers.append(server_name)

                    effective_config[server_name] = {
                        "enabled": enabled,
                        "config": config,
                    }

                    # Check if this server has an override
                    server_specific_plugins = plugins_dict.get(server_name, [])
                    for sp in server_specific_plugins:
                        sp_name = getattr(sp, "handler", sp.__class__.__name__)
                        if sp_name == plugin_handler:
                            server_overrides[server_name] = {
                                "enabled": getattr(sp, "enabled", True),
                                "config": getattr(sp, "config", {}),
                            }
                            break
                    break

            # If plugin not found in effective config, it's disabled
            if not plugin_found:
                disabled_servers.append(server_name)
                effective_config[server_name] = {"enabled": False, "config": {}}

        return {
            "total_servers": len(all_servers),
            "enabled_servers": enabled_servers,
            "disabled_servers": disabled_servers,
            "global_enabled": global_enabled,
            "server_overrides": server_overrides,
            "effective_config": effective_config,
        }

    def get_plugin_status_description(
        self, plugin_handler: str, plugin_type: str = "security"
    ) -> str:
        """Generate a status description for TUI display showing plugin enablement.

        Args:
            plugin_handler: The handler name (e.g., "basic_pii_filter", "tool_manager")
            plugin_type: Plugin type - "security" or "auditing"

        Returns:
            Status string suitable for TUI display
        """
        summary = self.get_plugin_enablement_summary(plugin_handler, plugin_type)

        total_servers = summary["total_servers"]
        enabled_count = len(summary["enabled_servers"])
        global_enabled = summary["global_enabled"]

        if total_servers == 0:
            return "No servers configured"

        if enabled_count == 0:
            return "Disabled on all servers"
        elif enabled_count == total_servers:
            if global_enabled and not summary["server_overrides"]:
                return "Enabled globally"
            else:
                return "Enabled on all servers"
        else:
            # Partial enablement
            enabled_servers = summary["enabled_servers"]
            if len(enabled_servers) <= 2:
                server_list = ", ".join(enabled_servers)
                return f"Enabled on {server_list}"
            else:
                return f"Enabled on {enabled_count}/{total_servers} servers"

    def get_all_available_servers(self) -> List[str]:
        """Get list of all available upstream server names.

        Returns:
            List of server names configured in the system
        """
        all_servers = set()

        # Get servers from security plugins
        for upstream_name in self.upstream_security_plugins.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        # Get servers from auditing plugins
        for upstream_name in self.upstream_auditing_plugins.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        # Also check original config for servers that might not have plugins loaded yet
        security_config = self.plugins_config.get("security", {})
        auditing_config = self.plugins_config.get("auditing", {})

        for upstream_name in security_config.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        for upstream_name in auditing_config.keys():
            if upstream_name != "_global":
                all_servers.add(upstream_name)

        return sorted(list(all_servers))
