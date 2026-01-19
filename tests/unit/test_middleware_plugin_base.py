"""Tests for MiddlewarePlugin base class."""

import pytest
from gatekit.plugins.interfaces import MiddlewarePlugin, SecurityPlugin, PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class ConcreteMiddlewarePlugin(MiddlewarePlugin):
    """Test implementation of MiddlewarePlugin."""

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="test")

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="test")

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="test")


def test_middleware_plugin_defaults():
    """Test middleware plugin default configuration."""
    plugin = ConcreteMiddlewarePlugin({})
    assert plugin.critical is True  # All plugins default to critical (fail-closed)
    assert plugin.priority == 50
    assert plugin.is_critical() is True


def test_middleware_plugin_critical_config():
    """Test middleware plugin critical configuration."""
    plugin = ConcreteMiddlewarePlugin({"critical": True})
    assert plugin.critical is True
    assert plugin.is_critical() is True


def test_middleware_plugin_priority():
    """Test middleware plugin priority configuration."""
    plugin = ConcreteMiddlewarePlugin({"priority": 10})
    assert plugin.priority == 10

    # Test invalid priority
    with pytest.raises(ValueError, match="priority.*must be between"):
        ConcreteMiddlewarePlugin({"priority": 150})


def test_security_plugin_inherits_middleware():
    """Test that SecurityPlugin properly inherits from MiddlewarePlugin."""
    # SecurityPlugin should be a subclass of MiddlewarePlugin
    assert issubclass(SecurityPlugin, MiddlewarePlugin)


def test_security_plugin_defaults():
    """Test that security plugins have different defaults than middleware."""

    class TestSecurityPlugin(SecurityPlugin):
        async def process_request(
            self, request: MCPRequest, server_name: str
        ) -> PluginResult:
            return PluginResult(allowed=True, reason="test")

        async def process_response(
            self, request: MCPRequest, response: MCPResponse, server_name: str
        ) -> PluginResult:
            return PluginResult(allowed=True, reason="test")

        async def process_notification(
            self, notification: MCPNotification, server_name: str
        ) -> PluginResult:
            return PluginResult(allowed=True, reason="test")

    plugin = TestSecurityPlugin({})
    assert plugin.critical is True  # Security defaults to critical
    assert plugin.priority == 50
    assert plugin.is_critical() is True


@pytest.mark.asyncio
async def test_middleware_plugin_interface():
    """Test middleware plugin interface methods."""
    plugin = ConcreteMiddlewarePlugin({})
    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    response = MCPResponse(jsonrpc="2.0", id=1, result={})
    notification = MCPNotification(jsonrpc="2.0", method="test", params={})

    result1 = await plugin.process_request(request, "test_server")
    assert isinstance(result1, PluginResult)

    result2 = await plugin.process_response(request, response, "test_server")
    assert isinstance(result2, PluginResult)

    result3 = await plugin.process_notification(notification, "test_server")
    assert isinstance(result3, PluginResult)


def test_pipeline_stage_properties():
    """Test PipelineStage properties."""
    from gatekit.plugins.interfaces import PipelineStage, StageOutcome

    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    modified_request = MCPRequest(
        jsonrpc="2.0", id=1, method="test_modified", params={}
    )

    # Test modified property
    stage1 = PipelineStage(
        plugin_name="TestPlugin",
        plugin_type="middleware",
        input_content=request,
        output_content=modified_request,
        content_hash="abc123",
        result=PluginResult(modified_content=modified_request),
        processing_time_ms=1.5,
        outcome=StageOutcome.MODIFIED,
    )
    assert stage1.modified is True

    # Test blocked property (security plugin)
    stage2 = PipelineStage(
        plugin_name="SecurityPlugin",
        plugin_type="security",
        input_content=request,
        output_content=None,
        content_hash="def456",
        result=PluginResult(allowed=False, reason="Blocked"),
        processing_time_ms=0.5,
        outcome=StageOutcome.BLOCKED,
    )
    assert stage2.blocked is True

    # Test completed property (middleware with completed_response)
    completed_response = MCPResponse(jsonrpc="2.0", id=1, result={})
    stage3 = PipelineStage(
        plugin_name="CachePlugin",
        plugin_type="middleware",
        input_content=request,
        output_content=None,
        content_hash="ghi789",
        result=PluginResult(completed_response=completed_response),
        processing_time_ms=0.2,
        outcome=StageOutcome.COMPLETED_BY_MIDDLEWARE,
    )
    assert stage3.completed is True


def test_processing_pipeline():
    """Test ProcessingPipeline functionality."""
    from gatekit.plugins.interfaces import (
        ProcessingPipeline,
        PipelineStage,
        StageOutcome,
    )

    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    modified_request = MCPRequest(
        jsonrpc="2.0", id=1, method="test_modified", params={}
    )
    pipeline = ProcessingPipeline(original_content=request)

    # Add a modification stage
    stage1 = PipelineStage(
        plugin_name="ModifierPlugin",
        plugin_type="middleware",
        input_content=request,
        output_content=modified_request,
        content_hash="aaa111",
        result=PluginResult(modified_content=modified_request),
        processing_time_ms=1.0,
        outcome=StageOutcome.MODIFIED,
    )
    pipeline.add_stage(stage1)

    # Add a blocking stage
    stage2 = PipelineStage(
        plugin_name="BlockerPlugin",
        plugin_type="security",
        input_content=request,
        output_content=None,
        content_hash="bbb222",
        result=PluginResult(allowed=False, reason="Blocked"),
        processing_time_ms=0.5,
        outcome=StageOutcome.BLOCKED,
    )
    pipeline.add_stage(stage2)
    # When a stage blocks, we need to set blocked_at_stage
    pipeline.blocked_at_stage = "BlockerPlugin"

    assert pipeline.blocked_at_stage == "BlockerPlugin"
    assert pipeline.final_decision is False
    assert "ModifierPlugin" in pipeline.get_modifications()

    summary = pipeline.get_processing_summary()
    assert summary["total_stages"] == 2
    assert summary["blocked"] is True
    assert summary["blocked_by"] == "BlockerPlugin"
