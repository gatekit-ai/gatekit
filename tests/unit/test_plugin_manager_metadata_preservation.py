"""Tests for plugin manager metadata preservation functionality."""

from typing import Optional
import pytest
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    PluginResult,
    PipelineOutcome,
    StageOutcome,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse


class MockModifyingPlugin(SecurityPlugin):
    """Mock plugin that modifies responses with specific reason/metadata"""

    def __init__(self, config=None):
        if config is None:
            config = {}
        super().__init__(config)

    async def process_request(self, request, server_name: Optional[str] = None):
        return PluginResult(allowed=True, reason="Request allowed")

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        # Simulate response modification with specific context
        modified_response = MCPResponse(
            jsonrpc="2.0",
            id=response.id,
            result={"modified": True, "original": response.result},
        )
        return PluginResult(
            allowed=True,
            reason="Content filtered by mock plugin",
            metadata={"items_filtered": 3},
            modified_content=modified_response,
        )

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        return PluginResult(allowed=True, reason="Notification allowed")


class MockNonModifyingPlugin(SecurityPlugin):
    """Mock plugin that allows without modification"""

    def __init__(self, config=None):
        if config is None:
            config = {}
        super().__init__(config)

    async def process_request(self, request, server_name: Optional[str] = None):
        return PluginResult(allowed=True, reason="Request allowed")

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        return PluginResult(
            allowed=True,
            reason="Content reviewed and approved",
            metadata={"review_passed": True},
        )

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        return PluginResult(allowed=True, reason="Notification allowed")


@pytest.mark.asyncio
class TestPluginManagerMetadataPreservation:

    async def test_plugin_manager_metadata_preservation(self):
        """Test plugin manager preserves plugin reason and metadata when response is modified"""
        # RED: Write test first - expect it to fail with current implementation
        manager = PluginManager({})
        manager.security_plugins = [MockModifyingPlugin()]
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id=1)
        response = MCPResponse(jsonrpc="2.0", id=1, result={"data": "test"})

        pipeline = await manager.process_response(request, response)

        # Should preserve plugin's specific context, not use generic
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
        assert len(pipeline.stages) == 1
        stage = pipeline.stages[0]
        assert stage.outcome == StageOutcome.MODIFIED
        # When capture_content is False (due to modification), reason is replaced with [outcome]
        assert (
            stage.result.reason == "[modified]"
        )  # Reason replaced when capture_content=False
        # Metadata should still be preserved
        assert stage.result.metadata == {
            "items_filtered": 3,
            "plugin": "MockModifyingPlugin",
        }
        assert stage.result.modified_content is not None

    async def test_plugin_manager_generic_metadata_when_no_modification(self):
        """Test plugin manager uses generic reason/metadata when plugins allow without modification"""
        manager = PluginManager({})
        manager.security_plugins = [MockNonModifyingPlugin()]
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id=1)
        response = MCPResponse(jsonrpc="2.0", id=1, result={"data": "test"})

        pipeline = await manager.process_response(request, response)

        # Should preserve plugin's meaningful reason even without modification
        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        assert len(pipeline.stages) == 1
        stage = pipeline.stages[0]
        assert stage.outcome == StageOutcome.ALLOWED
        # When no modification, reason should be preserved
        assert (
            stage.result.reason == "Content reviewed and approved"
        )  # Preserved from plugin
        assert stage.result.metadata == {
            "plugin": "MockNonModifyingPlugin",
            "review_passed": True,
        }  # Plugin metadata
        assert stage.result.modified_content is None

    async def test_plugin_manager_last_modifying_plugin_wins(self):
        """Test that when multiple plugins modify responses, last plugin's metadata is preserved"""
        plugin1 = MockModifyingPlugin({"priority": 10})

        plugin2 = MockModifyingPlugin({"priority": 20})

        # Override second plugin to return different context
        async def second_plugin_response(
            request, response, server_name: Optional[str] = None
        ):
            modified_response = MCPResponse(
                jsonrpc="2.0", id=response.id, result={"final_modification": True}
            )
            return PluginResult(
                allowed=True,
                reason="Final processing by second plugin",
                metadata={"final_step": True},
                modified_content=modified_response,
            )

        plugin2.process_response = second_plugin_response

        manager = PluginManager({})
        manager.security_plugins = [plugin1, plugin2]  # Sorted by priority
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id=1)
        response = MCPResponse(jsonrpc="2.0", id=1, result={"data": "test"})

        pipeline = await manager.process_response(request, response)

        # Should preserve LAST modifying plugin's reason but merge metadata
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
        assert len(pipeline.stages) == 2
        # Last stage should have plugin2's metadata
        last_stage = pipeline.stages[-1]
        # When capture_content is False (due to modification), reason is replaced with [outcome]
        assert (
            last_stage.result.reason == "[modified]"
        )  # Reason replaced when capture_content=False
        # Stages have independent metadata (not merged)
        assert last_stage.result.metadata == {
            "final_step": True,
            "plugin": "MockModifyingPlugin",
        }
        # Final content should be the last plugin's modification
        assert pipeline.final_content.result == {"final_modification": True}

    async def test_plugin_manager_preserves_denial_metadata(self):
        """Test that plugin denials preserve specific context (existing behavior)"""
        # This test verifies current behavior is not broken
        plugin = MockModifyingPlugin()

        async def denying_response(
            request, response, server_name: Optional[str] = None
        ):
            return PluginResult(
                allowed=False,
                reason="Content blocked by security policy",
                metadata={"violation": "sensitive_data", "confidence": 0.95},
            )

        plugin.process_response = denying_response

        manager = PluginManager({})
        manager.security_plugins = [plugin]
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="test", id=1)
        response = MCPResponse(jsonrpc="2.0", id=1, result={"data": "test"})

        pipeline = await manager.process_response(request, response)

        # Should preserve denial context (existing behavior)
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage == "MockModifyingPlugin"
        # Find the blocking stage
        blocking_stage = None
        for stage in pipeline.stages:
            if stage.outcome == StageOutcome.BLOCKED:
                blocking_stage = stage
                break
        assert blocking_stage is not None
        # When capture_content is False (due to blocking), reason is replaced with [outcome]
        assert (
            blocking_stage.result.reason == "[blocked]"
        )  # Reason replaced when capture_content=False
        # Metadata should be preserved
        assert blocking_stage.result.metadata == {
            "violation": "sensitive_data",
            "confidence": 0.95,
            "plugin": "MockModifyingPlugin",
        }
