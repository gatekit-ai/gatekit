"""Tests for plugin manager security critical handling functionality."""

from typing import Optional
import pytest
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    PluginResult,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestPluginManagerSecurityCriticalHandling:
    """Test PluginManager security critical handling functionality."""

    @pytest.mark.asyncio
    async def test_critical_security_plugin_failure_blocks_request(self):
        """Test that critical security plugin failures block requests."""

        class CriticalFailingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                raise Exception("Critical security plugin failure")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        config = {
            "security": {
                "_global": [
                    {
                        "handler": "critical_failing",
                        "config": {"enabled": True, "critical": True},
                    }
                ]
            }
        }

        manager = PluginManager(config)

        # Mock the plugin loading to use our test plugin
        manager.security_plugins = [CriticalFailingSecurityPlugin({"critical": True})]
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id="1")

        pipeline = await manager.process_request(request)

        assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
        # Check error stage
        assert len(pipeline.stages) > 0
        error_stage = pipeline.stages[-1]
        assert error_stage.outcome.value == "error"  # StageOutcome.ERROR
        assert error_stage.result.allowed is False
        assert error_stage.error_type == "Exception"

    @pytest.mark.asyncio
    async def test_non_critical_security_plugin_failure_allows_request(self):
        """Test that non-critical security plugin failures allow requests to continue."""

        class NonCriticalFailingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                raise Exception("Non-critical security plugin failure")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        class PassingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(
                    allowed=True, reason="Request allowed by basic security"
                )

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        config = {
            "security": [
                {
                    "handler": "non_critical_failing",
                    "config": {"enabled": True, "critical": False},
                },
                {"handler": "passing", "config": {"enabled": True, "critical": True}},
            ]
        }

        manager = PluginManager(config)

        # Mock the plugin loading to use our test plugins
        manager.upstream_security_plugins = {
            "unknown": [
                NonCriticalFailingSecurityPlugin({"critical": False}),
                PassingSecurityPlugin({"critical": True}),
            ]
        }
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id="1")

        pipeline = await manager.process_request(request)

        # Non-critical plugin failure should not prevent request processing
        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        # Should have both error stage (non-critical) and success stage (passing plugin)
        assert len(pipeline.stages) == 2
        # First stage should be the failing non-critical plugin
        assert pipeline.stages[0].outcome.value == "error"
        assert pipeline.stages[0].result.allowed is False
        # Second stage should be the passing plugin
        assert pipeline.stages[1].result.allowed is True
        # Reason may be cleared due to content clearing, so just verify it exists
        assert pipeline.stages[1].result.reason is not None

    @pytest.mark.asyncio
    async def test_mixed_critical_non_critical_plugin_failures(self):
        """Test behavior with mix of critical and non-critical plugin failures."""

        class NonCriticalFailingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                raise Exception("Non-critical security plugin failure")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        class CriticalFailingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                raise Exception("Critical security plugin failure")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        config = {
            "security": [
                {
                    "handler": "non_critical_failing",
                    "config": {"enabled": True, "critical": False},
                },
                {
                    "handler": "critical_failing",
                    "config": {"enabled": True, "critical": True},
                },
            ]
        }

        manager = PluginManager(config)

        # Mock the plugin loading to use our test plugins
        # Non-critical plugin has lower priority (executes first)
        non_critical_plugin = NonCriticalFailingSecurityPlugin({"critical": False})
        non_critical_plugin.priority = 10

        critical_plugin = CriticalFailingSecurityPlugin({"critical": True})
        critical_plugin.priority = 20

        manager.security_plugins = [non_critical_plugin, critical_plugin]
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id="1")

        pipeline = await manager.process_request(request)

        # With mixed plugin failures, critical failure should still block
        assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
        # Should have one error stage from the non-critical plugin, then stop at critical
        assert len(pipeline.stages) >= 1
        # Last stage should be the critical error
        error_stage = pipeline.stages[-1]
        assert error_stage.outcome.value == "error"
        assert error_stage.result.allowed is False
        assert error_stage.error_type == "Exception"

    @pytest.mark.asyncio
    async def test_critical_security_plugin_failure_blocks_response(self):
        """Test that critical security plugin failures block responses."""

        class CriticalFailingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                raise Exception("Critical security plugin failure on response")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

        config = {
            "security": {
                "_global": [
                    {
                        "handler": "critical_failing",
                        "config": {"enabled": True, "critical": True},
                    }
                ]
            }
        }

        manager = PluginManager(config)

        # Mock the plugin loading to use our test plugin
        manager.upstream_security_plugins = {
            "unknown": [CriticalFailingSecurityPlugin({"critical": True})]
        }
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id="1")
        response = MCPResponse(jsonrpc="2.0", result={"test": "data"}, id="1")

        pipeline = await manager.process_response(request, response)

        assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
        # Check error stage
        assert len(pipeline.stages) > 0
        error_stage = pipeline.stages[-1]
        assert error_stage.outcome.value == "error"
        assert error_stage.result.allowed is False
        assert error_stage.error_type == "Exception"

    @pytest.mark.asyncio
    async def test_critical_security_plugin_failure_blocks_notification(self):
        """Test that critical security plugin failures block notifications."""

        class CriticalFailingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="Test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                raise Exception("Critical security plugin failure on notification")

        config = {
            "security": {
                "_global": [
                    {
                        "handler": "critical_failing",
                        "config": {"enabled": True, "critical": True},
                    }
                ]
            }
        }

        manager = PluginManager(config)

        # Mock the plugin loading to use our test plugin
        manager.upstream_security_plugins = {
            "unknown": [CriticalFailingSecurityPlugin({"critical": True})]
        }
        manager._initialized = True

        notification = MCPNotification(jsonrpc="2.0", method="test_notification")

        pipeline = await manager.process_notification(notification)

        assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
        # Check error stage
        assert len(pipeline.stages) > 0
        error_stage = pipeline.stages[-1]
        assert error_stage.outcome.value == "error"  # StageOutcome.ERROR
        assert error_stage.result.allowed is False
        assert error_stage.error_type == "Exception"
