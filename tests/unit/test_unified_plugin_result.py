"""Comprehensive tests for unified PluginResult type system."""

import pytest
from typing import Optional
from gatekit.plugins.interfaces import (
    PluginResult,
    SecurityPlugin,
    MiddlewarePlugin,
    PipelineOutcome,
    StageOutcome,
)
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestPluginResultSemantics:
    """Test the semantics of the unified PluginResult type."""

    def test_plugin_result_default_allowed_is_none(self):
        """Test that PluginResult defaults to allowed=None."""
        result = PluginResult()
        assert result.allowed is None
        assert result.reason == ""
        assert result.metadata == {}

    def test_plugin_result_allowed_none_means_no_decision(self):
        """Test that allowed=None means no security decision was made."""
        result = PluginResult(allowed=None, reason="Just processing")
        assert result.allowed is None
        assert result.reason == "Just processing"

    def test_plugin_result_allowed_true_means_explicitly_allowed(self):
        """Test that allowed=True means explicitly allowed by security."""
        result = PluginResult(allowed=True, reason="Allowed by policy")
        assert result.allowed is True
        assert result.reason == "Allowed by policy"

    def test_plugin_result_allowed_false_means_explicitly_denied(self):
        """Test that allowed=False means explicitly denied by security."""
        result = PluginResult(allowed=False, reason="Blocked by policy")
        assert result.allowed is False
        assert result.reason == "Blocked by policy"

    def test_plugin_result_with_modification_and_decision(self):
        """Test that PluginResult can have both modification and security decision."""
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
        result = PluginResult(
            allowed=True, modified_content=request, reason="Allowed but sanitized"
        )
        assert result.allowed is True
        assert result.modified_content == request
        assert result.reason == "Allowed but sanitized"

    def test_plugin_result_cannot_have_both_modifications(self):
        """Test that PluginResult cannot have both modified_content and completed_response."""
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
        response = MCPResponse(jsonrpc="2.0", id=1, result={})

        with pytest.raises(ValueError, match="Cannot set both"):
            PluginResult(modified_content=request, completed_response=response)


class TestSecurityPluginContract:
    """Test that SecurityPlugin contract is enforced."""

    @pytest.mark.asyncio
    async def test_security_plugin_must_set_allowed(self):
        """Test that SecurityPlugin must set allowed to True or False."""

        class BadSecurityPlugin(SecurityPlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                # Violates contract: returns None for allowed
                return PluginResult(allowed=None, reason="No decision")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True)

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True)

        plugin = BadSecurityPlugin({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        # Contract violation is caught and returns an ERROR outcome
        pipeline = await manager.process_request(request, None)
        assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
        # Check that the error was from the contract violation
        assert len(pipeline.stages) > 0
        assert pipeline.stages[0].error_type == "PluginValidationError"

    @pytest.mark.asyncio
    async def test_security_plugin_allowed_true_works(self):
        """Test that SecurityPlugin with allowed=True works correctly."""

        class AllowingSecurityPlugin(SecurityPlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Request allowed")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Response allowed")

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Notification allowed")

        plugin = AllowingSecurityPlugin({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        # Check the pipeline's aggregated reason
        stages = [
            s for s in pipeline.stages if s.plugin_name == "AllowingSecurityPlugin"
        ]
        assert len(stages) > 0
        assert "allowed" in stages[0].result.reason.lower()

    @pytest.mark.asyncio
    async def test_security_plugin_allowed_false_blocks(self):
        """Test that SecurityPlugin with allowed=False blocks processing."""

        class BlockingSecurityPlugin(SecurityPlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=False, reason="Request blocked")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True)

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True)

        plugin = BlockingSecurityPlugin({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        # Check the blocking was recorded
        assert pipeline.blocked_at_stage == "BlockingSecurityPlugin"


class TestMiddlewarePluginBehavior:
    """Test that MiddlewarePlugin can leave allowed as None."""

    @pytest.mark.asyncio
    async def test_middleware_plugin_setting_allowed_gets_stripped(self):
        """Test that MiddlewarePlugin setting allowed gets the value stripped with warning."""

        class ViolatingMiddlewarePlugin(MiddlewarePlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                # This violates the contract - middleware shouldn't set allowed
                return PluginResult(allowed=False, reason="Trying to block")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Trying to allow")

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=False)

        plugin = ViolatingMiddlewarePlugin({"critical": False})  # Non-critical for this test
        manager = PluginManager({})
        manager._initialized = True
        # Set up the plugin in the proper structure
        manager.upstream_middleware_plugins = {"_global": [plugin]}
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        # Process request - should log error but continue since plugin is non-critical
        import logging
        import unittest

        with unittest.TestCase().assertLogs(
            "gatekit.plugins.manager", level=logging.WARNING
        ) as cm:
            result = await manager.process_request(request, None)

        # Verify error was logged
        assert any("illegally set allowed=False" in log for log in cm.output)

        # Verify the outcome - should be NO_SECURITY_EVALUATION since no security plugins ran
        # and this middleware is explicitly non-critical, so processing continues
        assert result.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION

        # Verify the stage shows an error
        assert len(result.stages) == 1
        assert result.stages[0].outcome == StageOutcome.ERROR
        assert result.stages[0].error_type == "PluginValidationError"

    @pytest.mark.asyncio
    async def test_middleware_plugin_can_return_none_allowed(self):
        """Test that MiddlewarePlugin can return allowed=None."""

        class ObservingMiddlewarePlugin(MiddlewarePlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=None, reason="Just observing")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=None, reason="Just observing")

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=None, reason="Just observing")

        plugin = ObservingMiddlewarePlugin({})
        manager = PluginManager({})
        manager._initialized = True
        # Put middleware in security_plugins list for simplicity (they're processed the same)
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        # Should be NO_SECURITY_EVALUATION since it's a middleware plugin in security_plugins list
        # but middleware doesn't make security decisions
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        # Check the stage has the middleware's reason
        assert len(pipeline.stages) == 1
        assert pipeline.stages[0].result.reason == "Just observing"

    @pytest.mark.asyncio
    async def test_middleware_can_modify_without_security_decision(self):
        """Test that MiddlewarePlugin can modify content without making security decision."""

        class ModifyingMiddlewarePlugin(MiddlewarePlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                modified = MCPRequest(
                    jsonrpc=request.jsonrpc,
                    id=request.id,
                    method="modified_" + request.method,
                    params=request.params,
                )
                return PluginResult(
                    allowed=None,  # No security decision
                    modified_content=modified,
                    reason="Modified request",
                )

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=None)

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=None)

        plugin = ModifyingMiddlewarePlugin({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        # Should have MODIFIED outcome
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
        # Check the modification
        assert pipeline.final_content.method == "modified_test"


class TestMixedPluginScenarios:
    """Test scenarios with both Security and Middleware plugins."""

    @pytest.mark.asyncio
    async def test_no_plugins_returns_none_allowed(self):
        """Test that no plugins returns allowed=None."""
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = []
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        # When no plugins run, pipeline has empty stages list
        assert len(pipeline.stages) == 0
        assert pipeline.final_content == request

    @pytest.mark.asyncio
    async def test_middleware_only_returns_none_allowed(self):
        """Test that middleware-only setup returns allowed=None."""

        class SimpleMiddleware(MiddlewarePlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(reason="Processed")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(reason="Processed")

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(reason="Processed")

        plugin = SimpleMiddleware({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # No security plugins ran
        # Check the pipeline's stages
        stages = [s for s in pipeline.stages if s.plugin_name == "SimpleMiddleware"]
        assert len(stages) > 0

    @pytest.mark.asyncio
    async def test_security_and_middleware_returns_security_decision(self):
        """Test that mix of security and middleware returns security decision."""

        class SimpleMiddleware(MiddlewarePlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(reason="Logged")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(reason="Logged")

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(reason="Logged")

        class SimpleSecurity(SecurityPlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Allowed")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Allowed")

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True, reason="Allowed")

        middleware = SimpleMiddleware({})
        security = SimpleSecurity({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [middleware, security]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        )  # Security plugin made a decision
        # Check the security plugin stage
        stages = [s for s in pipeline.stages if s.plugin_name == "SimpleSecurity"]
        assert len(stages) > 0
        assert "allowed" in stages[0].result.reason.lower()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_critical_plugin_failure_with_unified_result(self):
        """Test that critical plugin failures return appropriate PluginResult."""

        class FailingCriticalPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)
                self.critical = True  # Mark as critical

            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                raise RuntimeError("Critical failure")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True)

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True)

        plugin = FailingCriticalPlugin({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [plugin]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.ERROR
        )  # Critical failure returns ERROR
        # Check that the error was captured
        assert len(pipeline.stages) > 0
        assert pipeline.stages[0].error_type == "RuntimeError"

    @pytest.mark.asyncio
    async def test_completed_response_bypasses_remaining_plugins(self):
        """Test that completed_response stops plugin chain."""

        class CompletingMiddleware(MiddlewarePlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                completed = MCPResponse(
                    jsonrpc="2.0", id=request.id, result={"completed": True}
                )
                return PluginResult(
                    completed_response=completed, reason="Handled directly"
                )

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult()

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult()

        class NeverCalledSecurity(SecurityPlugin):
            async def process_request(
                self, request: MCPRequest, server_name: Optional[str] = None
            ) -> PluginResult:
                raise AssertionError("Should not be called")

            async def process_response(
                self,
                request: MCPRequest,
                response: MCPResponse,
                server_name: Optional[str] = None,
            ) -> PluginResult:
                return PluginResult(allowed=True)

            async def process_notification(
                self, notification: MCPNotification, server_name: Optional[str] = None
            ) -> PluginResult:
                return PluginResult(allowed=True)

        completing = CompletingMiddleware({})
        never_called = NeverCalledSecurity({})
        manager = PluginManager({})
        manager._initialized = True
        manager.security_plugins = [completing, never_called]
        request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})

        pipeline = await manager.process_request(request, None)
        assert pipeline.final_content is not None
        assert pipeline.final_content.result == {"completed": True}
        # When middleware completes the response, outcome is COMPLETED_BY_MIDDLEWARE
        assert pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
