"""Test plugin contract enforcement - ensuring SecurityPlugin and MiddlewarePlugin contracts are enforced."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from gatekit.protocol.messages import MCPNotification, MCPRequest, MCPResponse
from gatekit.plugins.interfaces import (
    PipelineOutcome,
    MiddlewarePlugin,
    PluginResult,
    SecurityPlugin,
    StageOutcome,
)
from gatekit.plugins.manager import PluginManager


class TestMiddlewareContractEnforcement:
    """Test that MiddlewarePlugin cannot make security decisions."""

    @pytest.fixture
    def manager(self):
        """Create a PluginManager instance."""
        return PluginManager(plugins_config={})

    @pytest.fixture
    def mock_middleware_plugin(self):
        """Create a mock middleware plugin that illegally sets allowed."""
        plugin = MagicMock(spec=MiddlewarePlugin)
        plugin.plugin_id = "illegal_middleware"
        plugin.priority = 50
        plugin.is_critical.return_value = False

        # This middleware illegally tries to make a security decision
        plugin.process_request = AsyncMock(
            return_value=PluginResult(
                allowed=False,  # ILLEGAL: MiddlewarePlugin cannot set allowed to False
                reason="Middleware blocking request",
                metadata={"plugin": "illegal_middleware"},
            )
        )
        plugin.process_response = AsyncMock(
            return_value=PluginResult(
                allowed=True,  # ILLEGAL: MiddlewarePlugin cannot set allowed to True
                reason="Middleware allowing response",
                metadata={"plugin": "illegal_middleware"},
            )
        )
        plugin.process_notification = AsyncMock(
            return_value=PluginResult(
                allowed=False,  # ILLEGAL: MiddlewarePlugin cannot set allowed to False
                reason="Middleware blocking notification",
                metadata={"plugin": "illegal_middleware"},
            )
        )

        return plugin

    @pytest.fixture
    def mock_legal_middleware_plugin(self):
        """Create a mock middleware plugin that correctly sets allowed=None."""
        plugin = MagicMock(spec=MiddlewarePlugin)
        plugin.plugin_id = "legal_middleware"
        plugin.priority = 50
        plugin.is_critical.return_value = False

        # This middleware correctly doesn't make security decisions
        plugin.process_request = AsyncMock(
            return_value=PluginResult(
                allowed=None,  # CORRECT: MiddlewarePlugin leaves allowed as None
                reason="Middleware processed request",
                metadata={"plugin": "legal_middleware"},
            )
        )
        plugin.process_response = AsyncMock(
            return_value=PluginResult(
                allowed=None,  # CORRECT: MiddlewarePlugin leaves allowed as None
                reason="Middleware processed response",
                metadata={"plugin": "legal_middleware"},
            )
        )
        plugin.process_notification = AsyncMock(
            return_value=PluginResult(
                allowed=None,  # CORRECT: MiddlewarePlugin leaves allowed as None
                reason="Middleware processed notification",
                metadata={"plugin": "legal_middleware"},
            )
        )

        return plugin

    @pytest.mark.asyncio
    async def test_middleware_contract_violation_request(
        self, manager, mock_middleware_plugin, caplog
    ):
        """Test that middleware plugins cannot set allowed on requests."""
        # Set up manager with the illegal middleware plugin
        manager.upstream_security_plugins = {"_global": []}
        manager.upstream_middleware_plugins = {"_global": [mock_middleware_plugin]}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="test/method", params={})

        with caplog.at_level(logging.WARNING):
            pipeline = await manager.process_request(request)

        # The middleware's illegal allowed=False should cause an error
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # Non-critical error, processing continues
        assert len(pipeline.stages) == 1
        assert pipeline.stages[0].outcome == StageOutcome.ERROR
        assert pipeline.stages[0].error_type == "PluginValidationError"
        assert "illegally set allowed=False" in caplog.text
        assert "Only SecurityPlugin can make security decisions" in caplog.text

    @pytest.mark.asyncio
    async def test_middleware_contract_violation_response(
        self, manager, mock_middleware_plugin, caplog
    ):
        """Test that middleware plugins cannot set allowed on responses."""
        # Set up manager with the illegal middleware plugin
        manager.upstream_security_plugins = {"_global": []}
        manager.upstream_middleware_plugins = {"_global": [mock_middleware_plugin]}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="test/method", params={})
        response = MCPResponse(jsonrpc="2.0", id=1, result={"data": "test"})

        with caplog.at_level(logging.WARNING):
            pipeline = await manager.process_response(request, response)

        # The middleware's illegal allowed=True should cause an error
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # Non-critical error, processing continues
        assert len(pipeline.stages) == 1
        assert pipeline.stages[0].outcome == StageOutcome.ERROR
        assert pipeline.stages[0].error_type == "PluginValidationError"
        assert "illegally set allowed=True" in caplog.text
        assert "Only SecurityPlugin can make security decisions" in caplog.text

    @pytest.mark.asyncio
    async def test_middleware_contract_violation_notification(
        self, manager, mock_middleware_plugin, caplog
    ):
        """Test that middleware plugins cannot set allowed on notifications."""
        # Set up manager with the illegal middleware plugin
        manager.upstream_security_plugins = {"_global": []}
        manager.upstream_middleware_plugins = {"_global": [mock_middleware_plugin]}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        notification = MCPNotification(
            jsonrpc="2.0", method="test/notification", params={}
        )

        with caplog.at_level(logging.WARNING):
            pipeline = await manager.process_notification(notification)

        # The middleware's illegal allowed=False should cause an error
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # Non-critical error, processing continues
        assert len(pipeline.stages) == 1
        assert pipeline.stages[0].outcome == StageOutcome.ERROR
        assert pipeline.stages[0].error_type == "PluginValidationError"
        assert "illegally set allowed=False" in caplog.text
        assert "Only SecurityPlugin can make security decisions" in caplog.text

    @pytest.mark.asyncio
    async def test_legal_middleware_no_warning(
        self, manager, mock_legal_middleware_plugin, caplog
    ):
        """Test that legal middleware plugins don't trigger warnings."""
        # Set up manager with the legal middleware plugin
        manager.upstream_security_plugins = {"_global": []}
        manager.upstream_middleware_plugins = {
            "_global": [mock_legal_middleware_plugin]
        }
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="test/method", params={})

        with caplog.at_level(logging.WARNING):
            pipeline = await manager.process_request(request)

        # Legal middleware correctly has no security decision
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        assert "illegally set allowed" not in caplog.text
        # Middleware provided its own reason which is preserved in the stage
        assert (
            len(pipeline.stages) > 0
            and pipeline.stages[0].result.reason == "Middleware processed request"
        )

    @pytest.mark.asyncio
    async def test_middleware_contract_aggregated_tools(
        self, manager, mock_middleware_plugin, caplog
    ):
        """Test that middleware contract is enforced in aggregated tools/list."""
        # Set up manager with the illegal middleware plugin
        manager.upstream_security_plugins = {"_global": []}
        manager.upstream_middleware_plugins = {"_global": [mock_middleware_plugin]}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="tools/list", params={})
        response = MCPResponse(
            jsonrpc="2.0", id=1, result={"tools": [{"name": "server1__tool1"}]}
        )

        with caplog.at_level(logging.WARNING):
            pipeline = await manager._process_aggregated_tools_list_response(
                request, response
            )

        # The middleware's illegal allowed should cause an error in aggregated response too
        # But aggregated tools continue processing despite non-critical errors
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # No security plugins ran
        # Check that we have an error stage for the middleware contract violation
        error_stages = [s for s in pipeline.stages if s.outcome == StageOutcome.ERROR]
        assert len(error_stages) > 0
        assert "illegally set allowed" in caplog.text

    @pytest.mark.asyncio
    async def test_aggregated_tools_with_only_middleware(
        self, manager, mock_legal_middleware_plugin
    ):
        """Test that aggregated tools/list with only middleware returns allowed=None."""
        # Set up manager with only middleware plugins (no security plugins)
        manager.upstream_security_plugins = {"_global": []}
        manager.upstream_middleware_plugins = {
            "_global": [mock_legal_middleware_plugin]
        }
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="tools/list", params={})
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "tools": [
                    {"name": "server1__tool1", "description": "Tool 1"},
                    {"name": "server2__tool2", "description": "Tool 2"},
                ]
            },
        )

        pipeline = await manager._process_aggregated_tools_list_response(
            request, response
        )

        # With only middleware plugins, pipeline outcome should be NO_SECURITY_EVALUATION
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        assert not pipeline.had_security_plugin
        # Verify tools are still processed correctly
        assert (
            pipeline.final_content and len(pipeline.final_content.result["tools"]) == 2
        )


class TestSecurityPluginContractEnforcement:
    """Test that SecurityPlugin must make security decisions."""

    @pytest.fixture
    def manager(self):
        """Create a PluginManager instance."""
        return PluginManager(plugins_config={})

    @pytest.fixture
    def mock_security_plugin_no_decision(self):
        """Create a mock security plugin that fails to make a decision."""
        plugin = MagicMock(spec=SecurityPlugin)
        plugin.plugin_id = "broken_security"
        plugin.priority = 50
        plugin.is_critical.return_value = True

        # This security plugin incorrectly returns allowed=None
        plugin.process_request = AsyncMock(
            return_value=PluginResult(
                allowed=None,  # VIOLATION: SecurityPlugin must set allowed to True or False
                reason="Security plugin didn't decide",
                metadata={"plugin": "broken_security"},
            )
        )
        plugin.process_response = AsyncMock(
            return_value=PluginResult(
                allowed=None,  # VIOLATION: SecurityPlugin must set allowed to True or False
                reason="Security plugin didn't decide",
                metadata={"plugin": "broken_security"},
            )
        )
        plugin.process_notification = AsyncMock(
            return_value=PluginResult(
                allowed=None,  # VIOLATION: SecurityPlugin must set allowed to True or False
                reason="Security plugin didn't decide",
                metadata={"plugin": "broken_security"},
            )
        )

        return plugin

    @pytest.mark.asyncio
    async def test_security_plugin_must_make_decision_request(
        self, manager, mock_security_plugin_no_decision
    ):
        """Test that security plugins must make decisions on requests."""
        # Set up manager with the broken security plugin
        manager.upstream_security_plugins = {
            "_global": [mock_security_plugin_no_decision]
        }
        manager.upstream_middleware_plugins = {"_global": []}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="test/method", params={})

        # Security plugin contract violation should raise an error
        pipeline = await manager.process_request(request)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.ERROR
        )  # Contract violation results in ERROR

    @pytest.mark.asyncio
    async def test_security_plugin_must_make_decision_response(
        self, manager, mock_security_plugin_no_decision
    ):
        """Test that security plugins must make decisions on responses."""
        # Set up manager with the broken security plugin
        manager.upstream_security_plugins = {
            "_global": [mock_security_plugin_no_decision]
        }
        manager.upstream_middleware_plugins = {"_global": []}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="test/method", params={})
        response = MCPResponse(jsonrpc="2.0", id=1, result={"data": "test"})

        # Security plugin contract violation should raise an error
        pipeline = await manager.process_response(request, response)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.ERROR
        )  # Contract violation results in ERROR

    @pytest.mark.asyncio
    async def test_security_plugin_must_make_decision_notification(
        self, manager, mock_security_plugin_no_decision
    ):
        """Test that security plugins must make decisions on notifications."""
        # Set up manager with the broken security plugin
        manager.upstream_security_plugins = {
            "_global": [mock_security_plugin_no_decision]
        }
        manager.upstream_middleware_plugins = {"_global": []}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        notification = MCPNotification(
            jsonrpc="2.0", method="test/notification", params={}
        )

        # Security plugin contract violation should raise an error
        pipeline = await manager.process_notification(notification)
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.ERROR
        )  # Contract violation results in ERROR

    @pytest.mark.asyncio
    async def test_security_plugin_must_make_decision_aggregated(
        self, manager, mock_security_plugin_no_decision
    ):
        """Test that security plugins must make decisions in aggregated tools/list."""
        # Set up manager with the broken security plugin
        manager.upstream_security_plugins = {
            "_global": [mock_security_plugin_no_decision]
        }
        manager.upstream_middleware_plugins = {"_global": []}
        manager.upstream_auditing_plugins = {"_global": []}
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", id=1, method="tools/list", params={})
        response = MCPResponse(
            jsonrpc="2.0", id=1, result={"tools": [{"name": "server1__tool1"}]}
        )

        # Security plugin contract violation should result in ERROR outcome
        pipeline = await manager._process_aggregated_tools_list_response(
            request, response
        )

        # In aggregated tools processing, errors in individual servers lead to BLOCKED outcome
        # when all servers fail (as in this case with single server)
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        # Check that we have error stages from the contract violation
        error_stages = [s for s in pipeline.stages if s.outcome == StageOutcome.ERROR]
        assert len(error_stages) > 0
        assert any(s.error_type == "PluginValidationError" for s in error_stages)
