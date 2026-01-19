"""Tests for plugin manager middleware support."""

import pytest
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    MiddlewarePlugin,
    PluginResult,
    ProcessingPipeline,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class MockMiddlewarePlugin(MiddlewarePlugin):
    """Mock middleware plugin implementation for testing."""

    HANDLERS = {"test_middleware": "MockMiddlewarePlugin"}

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Test middleware processed")

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Test middleware processed")

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Test middleware processed")


@pytest.mark.asyncio
async def test_middleware_plugin_loading():
    """Test that middleware plugins can be loaded."""
    config = {
        "middleware": {
            "_global": [
                {
                    "handler": "test_middleware",
                    "enabled": True,
                    "config": {"priority": 30},
                }
            ]
        }
    }

    manager = PluginManager(config)
    # Mock the discovery to find our test plugin
    import unittest.mock as mock

    with mock.patch.object(
        manager,
        "_discover_handlers",
        lambda category: (
            {"test_middleware": MockMiddlewarePlugin}
            if category == "middleware"
            else {}
        ),
    ):
        await manager.load_plugins()

    assert "_global" in manager.upstream_middleware_plugins
    assert len(manager.upstream_middleware_plugins["_global"]) == 1
    assert isinstance(
        manager.upstream_middleware_plugins["_global"][0], MockMiddlewarePlugin
    )


@pytest.mark.asyncio
async def test_middleware_pipeline_processing():
    """Test that middleware plugins are processed in the pipeline."""
    config = {
        "middleware": {
            "_global": [
                {
                    "handler": "test_middleware",
                    "enabled": True,
                    "config": {"priority": 30},
                }
            ]
        }
    }

    manager = PluginManager(config)
    # Mock discovery
    import unittest.mock as mock

    with mock.patch.object(
        manager,
        "_discover_handlers",
        lambda category: (
            {"test_middleware": MockMiddlewarePlugin}
            if category == "middleware"
            else {}
        ),
    ):
        await manager.load_plugins()

    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    pipeline = await manager.process_request(request, "test_server")

    assert isinstance(pipeline, ProcessingPipeline)
    assert (
        pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
    )  # No security decision when only middleware plugins
    assert len(pipeline.stages) == 1
    assert "processed" in pipeline.stages[0].result.reason.lower()


class CompletingMiddlewarePlugin(MiddlewarePlugin):
    """Middleware plugin that completes requests."""

    HANDLERS = {"completing_middleware": "CompletingMiddlewarePlugin"}

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        # Complete the request with a response
        completed_response = MCPResponse(
            jsonrpc="2.0", id=request.id, result={"completed": True, "by": "middleware"}
        )
        return PluginResult(
            completed_response=completed_response,
            reason="Request completed by middleware",
        )

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Response processed")

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Notification processed")


@pytest.mark.asyncio
async def test_middleware_request_completion():
    """Test that middleware can complete requests without forwarding."""
    config = {
        "middleware": {
            "_global": [
                {
                    "handler": "completing_middleware",
                    "enabled": True,
                    "config": {"priority": 10},
                }
            ]
        }
    }

    manager = PluginManager(config)
    # Mock discovery
    import unittest.mock as mock

    with mock.patch.object(
        manager,
        "_discover_handlers",
        lambda category: (
            {"completing_middleware": CompletingMiddlewarePlugin}
            if category == "middleware"
            else {}
        ),
    ):
        await manager.load_plugins()

    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    pipeline = await manager.process_request(request, "test_server")

    # Should have completed_by set in pipeline
    assert isinstance(pipeline, ProcessingPipeline)
    assert pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
    assert (
        pipeline.completed_by == "CompletingMiddlewarePlugin"
    )  # Uses class name as plugin_id
    assert pipeline.final_content is not None
    assert pipeline.final_content.result == {"completed": True, "by": "middleware"}


class ModifyingMiddlewarePlugin(MiddlewarePlugin):
    """Middleware plugin that modifies requests."""

    HANDLERS = {"modifying_middleware": "ModifyingMiddlewarePlugin"}

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        # Modify the request
        modified_request = MCPRequest(
            jsonrpc=request.jsonrpc,
            id=request.id,
            method=request.method,
            params=(
                {"modified": True, **request.params}
                if request.params
                else {"modified": True}
            ),
        )
        return PluginResult(
            modified_content=modified_request, reason="Request modified by middleware"
        )

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Response processed")

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        return PluginResult(reason="Notification processed")


@pytest.mark.asyncio
async def test_middleware_request_modification():
    """Test that middleware can modify requests."""
    config = {
        "middleware": {
            "_global": [
                {
                    "handler": "modifying_middleware",
                    "enabled": True,
                    "config": {"priority": 20},
                }
            ]
        }
    }

    manager = PluginManager(config)
    # Mock discovery
    import unittest.mock as mock

    with mock.patch.object(
        manager,
        "_discover_handlers",
        lambda category: (
            {"modifying_middleware": ModifyingMiddlewarePlugin}
            if category == "middleware"
            else {}
        ),
    ):
        await manager.load_plugins()

    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={"original": True})
    pipeline = await manager.process_request(request, "test_server")

    # Should have modified content in pipeline
    assert isinstance(pipeline, ProcessingPipeline)
    assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
    assert pipeline.final_content is not None
    assert isinstance(pipeline.final_content, MCPRequest)
    assert pipeline.final_content.params == {"modified": True, "original": True}
    assert len(pipeline.stages) == 1
    assert "modified by middleware" in pipeline.stages[0].result.reason.lower()


@pytest.mark.asyncio
async def test_middleware_priority_ordering():
    """Test that middleware and security plugins are ordered by priority."""
    # Create plugins with different priorities
    from gatekit.plugins.interfaces import SecurityPlugin, PluginResult

    class HighPriorityMiddleware(MiddlewarePlugin):
        HANDLERS = {"high_priority": "HighPriorityMiddleware"}

        def __init__(self, config):
            super().__init__(config)
            self.priority = 10  # High priority (runs first)

        async def process_request(
            self, request: MCPRequest, server_name: str
        ) -> PluginResult:
            modified = MCPRequest(
                jsonrpc=request.jsonrpc,
                id=request.id,
                method=request.method,
                params=(
                    {**request.params, "high_priority": True}
                    if request.params
                    else {"high_priority": True}
                ),
            )
            return PluginResult(
                modified_content=modified, reason="High priority middleware"
            )

        async def process_response(
            self, request: MCPRequest, response: MCPResponse, server_name: str
        ) -> PluginResult:
            return PluginResult(reason="Response processed")

        async def process_notification(
            self, notification: MCPNotification, server_name: str
        ) -> PluginResult:
            return PluginResult(reason="Notification processed")

    class LowPrioritySecurityPlugin(SecurityPlugin):
        HANDLERS = {"low_priority": "LowPrioritySecurityPlugin"}

        def __init__(self, config):
            super().__init__(config)
            self.priority = 90  # Low priority (runs last)

        async def process_request(
            self, request: MCPRequest, server_name: str
        ) -> PluginResult:
            # Verify that high priority middleware ran first
            assert request.params and "high_priority" in request.params
            return PluginResult(
                allowed=True, reason="Low priority security check passed"
            )

        async def process_response(
            self, request: MCPRequest, response: MCPResponse, server_name: str
        ) -> PluginResult:
            return PluginResult(allowed=True, reason="Response allowed")

        async def process_notification(
            self, notification: MCPNotification, server_name: str
        ) -> PluginResult:
            return PluginResult(allowed=True, reason="Notification allowed")

    config = {
        "middleware": {
            "_global": [{"handler": "high_priority", "config": {"enabled": True}}]
        },
        "security": {
            "_global": [{"handler": "low_priority", "config": {"enabled": True}}]
        },
    }

    manager = PluginManager(config)
    # Mock discovery
    import unittest.mock as mock

    def mock_discover(category):
        if category == "middleware":
            return {"high_priority": HighPriorityMiddleware}
        elif category == "security":
            return {"low_priority": LowPrioritySecurityPlugin}
        return {}

    with mock.patch.object(manager, "_discover_handlers", mock_discover):
        await manager.load_plugins()

    request = MCPRequest(jsonrpc="2.0", id=1, method="test", params={})
    pipeline = await manager.process_request(request, "test_server")

    # The security plugin's assertion will verify ordering
    assert isinstance(pipeline, ProcessingPipeline)
    # Pipeline outcome is MODIFIED because middleware modified the request
    assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
    assert len(pipeline.stages) == 2  # One middleware, one security
    # Verify ordering - high priority middleware (priority 10) should be first
    assert pipeline.stages[0].plugin_name == "HighPriorityMiddleware"
    assert pipeline.stages[1].plugin_name == "LowPrioritySecurityPlugin"
