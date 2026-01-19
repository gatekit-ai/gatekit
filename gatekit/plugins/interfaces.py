"""Plugin interfaces for Gatekit MCP gateway.

This module defines the abstract base classes and data structures that all
plugins must implement to integrate with the Gatekit plugin system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Union, List, Optional
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


@dataclass
class PluginResult:
    """Unified result from any plugin processing.

    All plugins return this single type, simplifying the type system
    while maintaining semantic clarity through the plugin class hierarchy.

    Attributes:
        allowed: Security decision (None if no security decision made)
        modified_content: Optional modified version of the message for further processing
        completed_response: Optional complete response that ends pipeline processing
        reason: Human-readable explanation of what was done
        metadata: Additional information about the processing
    """

    # Security decision (None if no security decision made)
    allowed: Optional[bool] = None

    # Content transformations
    modified_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None
    completed_response: Optional[MCPResponse] = None

    # Processing information
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate state consistency."""
        if self.metadata is None:
            self.metadata = {}
        # Can't set both modified_content and completed_response
        if self.modified_content and self.completed_response:
            raise ValueError("Cannot set both modified_content and completed_response")


class PluginInterface(ABC):  # noqa: B024
    """Base interface for all Gatekit plugins.

    All plugins must inherit from this interface and implement the required
    initialization method. This ensures consistent plugin lifecycle management.

    TUI Display Metadata:
    Plugins that want to appear in the TUI must provide class-level display metadata:

    - DISPLAY_NAME: Human-readable name for the plugin
    - DESCRIPTION: Short (1-2 line) description of what the plugin does
    - DISPLAY_SCOPE: (SecurityPlugin only) Plugin scope category - where plugin appears in TUI:
        * "global" - Server-agnostic plugins (PII Filter, Secrets Filter)
        * "server_aware" - Universal plugins requiring per-server config (Tool Allowlist)
        * "server_specific" - Plugins for specific server implementations (Filesystem Server)
        Note: AuditingPlugin subclasses don't use DISPLAY_SCOPE - they always appear in global sections
    - describe_status(cls, config: dict) -> str: Generate status description from config
    - get_display_actions(cls, config: dict) -> List[str]: Return available UI actions
    """

    # TUI Display Metadata (Optional - plugins provide these for TUI integration)
    # DISPLAY_NAME = "Plugin Name"  # Human-readable name
    # DESCRIPTION = "Short description"  # 1-2 line description
    # DISPLAY_SCOPE = "global"      # (SecurityPlugin only) "global", "server_aware", or "server_specific"

    def __init__(self, config: Dict[str, Any]):  # noqa: B027
        """Initialize plugin with configuration.

        Args:
            config: Plugin-specific configuration dictionary

        Raises:
            ValueError: If configuration is invalid
            TypeError: If configuration has wrong types
        """
        # Base interface just stores config for subclasses
        # Subclasses handle their own specific configuration needs
        pass

    @property
    def plugin_id(self) -> str:
        """Unique identifier for this plugin (DISPLAY_NAME if available, otherwise class name)."""
        return getattr(self.__class__, "DISPLAY_NAME", self.__class__.__name__)

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        """Generate status description from configuration.

        Called by TUI to populate the status column. Must work without plugin
        instantiation. Config may be empty for disabled plugins.

        Default implementation returns a basic enabled/disabled status.
        Plugins should override this to provide meaningful status descriptions.

        Args:
            config: Current plugin configuration dict (may be empty)

        Returns:
            Status string for display (e.g. "Blocking: API Keys, Tokens")
        """
        if not config or not config.get("enabled", False):
            return "Disabled"
        return "Enabled"

    @classmethod
    def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
        """Return available UI actions based on configuration state.

        Args:
            config: Current plugin configuration dict (may be empty)

        Returns:
            List of action strings (e.g. ["Configure", "Test"])
        """
        if config and config.get("enabled", False):
            return ["Configure"]
        return ["Setup"]

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for this plugin's configuration.

        Returns:
            Dict containing JSON Schema (2020-12) for plugin configuration
        """
        # Plugins should override this with their specific schema
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }


class MiddlewarePlugin(PluginInterface):
    """Base class for all middleware plugins.

    Middleware plugins process MCP messages and can modify content, trigger side effects,
    communicate with external systems, or enhance functionality. They cannot block
    messages - use SecurityPlugin for blocking capability.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize middleware plugin with configuration."""
        super().__init__(config)
        # All plugins default to critical (fail closed) for security
        self.critical = config.get("critical", True)
        # Middleware uses priority for ordering
        self.priority = config.get("priority", 50)
        # Validate priority range
        if not isinstance(self.priority, int) or not (0 <= self.priority <= 100):
            raise ValueError(
                f"Plugin priority {self.priority} must be between 0 and 100"
            )

    def is_critical(self) -> bool:
        """Return whether this plugin is critical for operation."""
        return self.critical

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Process an incoming request.

        Can:
        - Modify the request for further processing (set modified_content)
        - Fully handle the request (set completed_response)
        - Trigger side effects and pass through unchanged (return empty result)

        Args:
            request: The MCP request to evaluate
            server_name: Name of the target server

        Returns:
            PluginResult: Processing result
        """
        return PluginResult()

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Process a response from the upstream server.

        Args:
            request: The original MCP request
            response: The MCP response to evaluate
            server_name: Name of the source server

        Returns:
            PluginResult: Processing result
        """
        return PluginResult()

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        """Process a notification message.

        Args:
            notification: The MCP notification to evaluate
            server_name: Name of the source server

        Returns:
            PluginResult: Processing result
        """
        return PluginResult()


class SecurityPlugin(MiddlewarePlugin):
    """Base class for security policy plugins.

    Security plugins evaluate MCP messages (requests, responses, and notifications)
    and determine whether they should be allowed to proceed.

    Security plugins extend middleware with the ability to prevent
    requests/responses from proceeding when they violate security policies.
    Override methods to return PluginResult with allowed=False to block messages.

    Default implementations allow all messages. Override only the methods you need.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize security plugin with configuration.

        Args:
            config: Plugin-specific configuration dictionary

        Raises:
            ValueError: If configuration is invalid
            TypeError: If configuration has wrong types
        """
        # Initialize base middleware class
        super().__init__(config)

        # All plugins default to critical (fail closed) for security
        # SecurityPlugin inherits from MiddlewarePlugin which now also defaults to True
        self.critical = config.get("critical", True)

    # Remove is_critical() - inherited from MiddlewarePlugin

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Evaluate if request should be allowed.

        Override this method to validate request content for security violations.

        Args:
            request: The MCP request to evaluate
            server_name: Name of the target server

        Returns:
            PluginResult: Decision on whether to allow the request
        """
        return PluginResult(allowed=True)

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Evaluate if response should be allowed.

        Override this method to validate response content to prevent data leakage.

        Args:
            request: The original MCP request
            response: The MCP response to evaluate
            server_name: Name of the source server

        Returns:
            PluginResult: Decision on whether to allow the response
        """
        return PluginResult(allowed=True)

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        """Evaluate if notification should be allowed.

        Override this method to validate notification content to prevent information disclosure.

        Args:
            notification: The MCP notification to evaluate
            server_name: Name of the source server

        Returns:
            PluginResult: Decision on whether to allow the notification
        """
        return PluginResult(allowed=True)


class AuditingPlugin(PluginInterface):
    """Abstract base class for auditing plugins.

    Auditing plugins observe the complete processing pipeline for security
    monitoring, compliance, and debugging purposes. They execute sequentially
    after message processing completes, but do not use priority ordering.
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize auditing plugin with configuration.

        Args:
            config: Plugin-specific configuration dictionary
        """
        # Initialize base class
        super().__init__(config)

        # Auditing plugins don't use priority - they execute in definition order
        # All plugins default to critical (fail closed) for security
        self.critical = config.get("critical", True)

    async def log_request(
        self, request: MCPRequest, pipeline: ProcessingPipeline, server_name: str
    ) -> None:
        """Log request with processing pipeline.

        Override this method to log request processing.

        Args:
            request: The MCP request being processed
            pipeline: The complete processing pipeline
            server_name: Name of the target server
        """
        pass

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        """Log response from upstream server with processing pipeline.

        Override this method to log response processing.

        Args:
            request: The original MCP request for correlation
            response: The MCP response from the upstream server
            pipeline: The complete processing pipeline
            server_name: Name of the source server
        """
        pass

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        """Log notification message.

        Override this method to log notification processing.

        Args:
            notification: The MCP notification being processed
            pipeline: The complete processing pipeline
            server_name: Name of the source server
        """
        pass

    def is_critical(self) -> bool:
        """Return whether this plugin is critical for operation.

        Critical plugins will cause processing to halt on failure.
        Non-critical plugins log errors but allow processing to continue.

        Returns:
            bool: True if plugin failures should halt processing, False otherwise
        """
        return getattr(self, "critical", True)


class PathResolvablePlugin(ABC):
    """Abstract base class for plugins that use file paths in their configuration.

    This interface formalizes the contract for plugins that need path resolution
    relative to the configuration directory. Plugins implementing this interface
    will receive the config directory and can resolve relative paths accordingly.

    Path-aware plugins must:
    1. Implement set_config_directory() to receive the config directory
    2. Implement validate_paths() to validate resolved paths
    3. Use the config directory to resolve relative paths in their configuration

    This interface can be mixed with SecurityPlugin or AuditingPlugin to create
    path-aware security or auditing plugins.
    """

    @abstractmethod
    def set_config_directory(self, config_directory: Union[str, Path]) -> None:
        """Set the configuration directory for path resolution.

        This method is called by the plugin manager after plugin initialization
        to provide the directory containing the configuration file. Plugins should
        use this directory to resolve any relative paths in their configuration.

        Args:
            config_directory: Directory containing the configuration file

        Raises:
            TypeError: If config_directory is not a valid path type
            ValueError: If config_directory is invalid or inaccessible
        """
        pass

    @abstractmethod
    def validate_paths(self) -> List[str]:
        """Validate all paths used by this plugin.

        This method should validate that all paths resolved by the plugin
        are valid, accessible, and secure. It should return a list of validation
        errors, or an empty list if all paths are valid.

        Returns:
            List[str]: List of validation error messages, empty if no errors

        Examples:
            ["Log directory does not exist: /invalid/path"]
            ["Output file parent directory is not writable: /readonly/dir"]
            []  # No validation errors
        """
        pass


class StageOutcome(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    MODIFIED = "modified"
    COMPLETED_BY_MIDDLEWARE = "completed_by_middleware"
    ERROR = "error"


class PipelineOutcome(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    MODIFIED = "modified"
    COMPLETED_BY_MIDDLEWARE = "completed_by_middleware"
    ERROR = "error"
    NO_SECURITY_EVALUATION = "no_security"


@dataclass
class PipelineStage:
    plugin_name: str
    plugin_type: str  # security | middleware
    input_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]]
    output_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]]
    content_hash: str
    result: PluginResult
    processing_time_ms: float
    outcome: StageOutcome
    error_type: Optional[str] = None
    security_evaluated: bool = False

    @property
    def modified(self) -> bool:
        """Return True if this stage modified content."""
        return self.result.modified_content is not None

    @property
    def blocked(self) -> bool:
        """Return True if this stage blocked the request."""
        return self.result.allowed is False

    @property
    def completed(self) -> bool:
        """Return True if this stage completed the request."""
        return self.result.completed_response is not None

    def to_metadata_dict(self) -> Dict[str, Any]:
        """Return metadata dict for this stage (excludes content).

        This is the standard representation for audit logs - includes all
        processing information but not the actual message content.
        """
        return {
            "plugin": self.plugin_name,
            "type": self.plugin_type,
            "processing_time_ms": self.processing_time_ms,
            "outcome": self.outcome.value,
            "error_type": self.error_type,
            "security_evaluated": self.security_evaluated,
            "reason": (
                self.result.reason if getattr(self.result, "reason", None) else None
            ),
            "allowed": self.result.allowed,
            # Include plugin metadata directly - no flattening, preserves per-stage data
            "metadata": self.result.metadata if self.result.metadata else None,
        }


@dataclass
class ProcessingPipeline:
    """Complete record of message processing through all plugins.

    Provides full visibility into how a message was processed,
    modified, and evaluated by the plugin pipeline.
    """

    original_content: Union[MCPRequest, MCPResponse, MCPNotification]
    stages: List[PipelineStage] = field(default_factory=list)
    final_content: Optional[Union[MCPRequest, MCPResponse, MCPNotification]] = None
    total_time_ms: float = 0.0
    pipeline_outcome: PipelineOutcome = PipelineOutcome.NO_SECURITY_EVALUATION
    blocked_at_stage: Optional[str] = None
    completed_by: Optional[str] = None
    had_security_plugin: bool = False
    capture_content: bool = True

    def add_stage(self, stage: PipelineStage) -> None:
        self.stages.append(stage)
        if stage.outcome == StageOutcome.BLOCKED and not self.blocked_at_stage:
            self.blocked_at_stage = stage.plugin_name
            self.pipeline_outcome = PipelineOutcome.BLOCKED
        elif (
            stage.outcome == StageOutcome.COMPLETED_BY_MIDDLEWARE
            and not self.completed_by
        ):
            self.completed_by = stage.plugin_name
            self.pipeline_outcome = PipelineOutcome.COMPLETED_BY_MIDDLEWARE
        # Note: ERROR outcomes are handled by the manager after checking plugin criticality

    def should_capture_content(self) -> bool:
        for s in self.stages:
            if s.plugin_type == "security":
                if s.result.allowed is False:
                    return False
                if s.result.modified_content is not None:
                    return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_outcome": self.pipeline_outcome.value,
            "blocked_at_stage": self.blocked_at_stage,
            "completed_by": self.completed_by,
            "had_security_plugin": self.had_security_plugin,
            "total_time_ms": self.total_time_ms,
            "capture_content": self.capture_content,
            "stages": [self._stage_to_full_dict(s) for s in self.stages],
        }

    def _stage_to_full_dict(self, stage: PipelineStage) -> Dict[str, Any]:
        return {
            **stage.to_metadata_dict(),
            "content_hash": stage.content_hash,
            "input_content": stage.input_content if self.capture_content else None,
            "output_content": stage.output_content if self.capture_content else None,
        }

    def to_audit_log(self, capture_sensitive: bool = False) -> Dict[str, Any]:
        if capture_sensitive or self.capture_content:
            return self.to_dict()
        return {
            "pipeline_outcome": self.pipeline_outcome.value,
            "blocked_at_stage": self.blocked_at_stage,
            "completed_by": self.completed_by,
            "had_security_plugin": self.had_security_plugin,
            "total_time_ms": self.total_time_ms,
            "content_captured": False,
            "stages": [s.to_metadata_dict() for s in self.stages],
        }

    @property
    def final_decision(self) -> Optional[bool]:
        """Return the final allow/deny decision from the pipeline."""
        # If blocked, return False
        if self.blocked_at_stage is not None:
            return False
        # If any security plugin made a decision, return True (allowed)
        # (since if it was False, we'd have blocked_at_stage set)
        for stage in self.stages:
            if stage.result.allowed is not None:
                if stage.result.allowed is False:
                    return False
        # If we had security evaluation and didn't block, we allowed
        if self.had_security_plugin:
            return True
        # No security decision was made
        return None

    def get_modifications(self) -> List[str]:
        """Get list of plugin names that modified content."""
        return [stage.plugin_name for stage in self.stages if stage.modified]

    def get_processing_summary(self) -> Dict[str, Any]:
        """Get summary of processing pipeline."""
        blocked = self.blocked_at_stage is not None
        return {
            "total_stages": len(self.stages),
            "pipeline_outcome": self.pipeline_outcome.value,
            "blocked": blocked,
            "blocked_by": self.blocked_at_stage if blocked else None,
            "blocked_at_stage": self.blocked_at_stage,
            "completed_by": self.completed_by,
            "total_time_ms": self.total_time_ms,
        }
