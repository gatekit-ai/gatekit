"""Integration tests for plugin manager metadata preservation functionality."""

import pytest
from typing import Optional
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    PipelineOutcome,
    ProcessingPipeline,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse


class MockModifyingSecurityPlugin(SecurityPlugin):
    """Mock security plugin that modifies responses with detailed metadata"""

    def __init__(self, config=None):
        if config is None:
            config = {}
        super().__init__(config)

    async def process_request(self, request, server_name: Optional[str] = None):
        return PluginResult(allowed=True, reason="Request allowed")

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        # Simulate response modification with security context
        modified_response = MCPResponse(
            jsonrpc="2.0",
            id=response.id,
            result={"sanitized": True, "original": response.result},
        )
        return PluginResult(
            allowed=True,
            reason="Response sanitized by security filter",
            metadata={
                "items_sanitized": 2,
                "filter": "basic_pii_filter",
                "confidence": 0.95,
            },
            modified_content=modified_response,
        )

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        return PluginResult(allowed=True, reason="Notification allowed")


class MockAuditingPlugin(AuditingPlugin):
    """Mock auditing plugin that captures enhanced metadata"""

    def __init__(self, config=None):
        if config is None:
            config = {}
        super().__init__(config)
        self.logged_responses = []

    async def log_request(
        self, request, pipeline: ProcessingPipeline, server_name: Optional[str] = None
    ):
        pass  # Not relevant for this test

    async def log_response(
        self,
        request,
        response,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ):
        # Store the response for verification
        self.logged_responses.append(response)

    async def log_notification(
        self,
        notification,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ):
        pass  # Not relevant for this test


@pytest.mark.asyncio
class TestMetadataPreservationIntegration:

    async def test_single_plugin_metadata_preservation(self):
        """Test that a single security plugin's metadata is preserved through the pipeline"""
        # Set up plugins
        security_plugin = MockModifyingSecurityPlugin()
        auditing_plugin = MockAuditingPlugin()

        manager = PluginManager({})
        manager.security_plugins = [security_plugin]
        manager.auditing_plugins = [auditing_plugin]
        manager._initialized = True

        # Original request/response
        request = MCPRequest(jsonrpc="2.0", method="get_user_data", id=1)
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"user": "john@example.com", "ssn": "123-45-6789"},
        )

        # Process through security plugins
        pipeline = await manager.process_response(request, response)

        # Verify enhanced metadata is preserved from security plugin
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
        # Get the last stage's result since pipeline doesn't have reason/metadata directly
        assert len(pipeline.stages) > 0
        last_stage = pipeline.stages[-1]
        # Reason is cleared to generic when content is modified (security-first approach)
        assert last_stage.result.reason == "[modified]"
        # Check that plugin metadata is preserved along with auto-injected plugin name
        expected_metadata = {
            "items_sanitized": 2,
            "filter": "basic_pii_filter",
            "confidence": 0.95,
            "plugin": "MockModifyingSecurityPlugin",
        }
        assert last_stage.result.metadata == expected_metadata
        assert last_stage.result.modified_content is not None
        assert isinstance(last_stage.result.modified_content, MCPResponse)
        assert last_stage.result.modified_content.result == {
            "sanitized": True,
            "original": {"user": "john@example.com", "ssn": "123-45-6789"},
        }

        # Log the response (this is what happens in the actual proxy flow)
        await manager.log_response(
            request,
            pipeline.final_content if pipeline.final_content else response,
            pipeline,
        )

        # Verify auditing plugin received the modified response
        assert len(auditing_plugin.logged_responses) == 1
        logged_response = auditing_plugin.logged_responses[0]
        assert logged_response.result["sanitized"] is True

    async def test_user_error_messages_contain_specific_plugin_context(self):
        """Test that error messages to users contain specific plugin reasons, not generic ones"""
        # This simulates the scenario where a user would see the error message
        security_plugin = MockModifyingSecurityPlugin()

        # Override to return a denial with specific context
        async def denying_response(
            request, response, server_name: Optional[str] = None
        ):
            return PluginResult(
                allowed=False,
                reason="Response blocked: contains sensitive PII data",
                metadata={
                    "violation_type": "pii_detection",
                    "confidence": 0.98,
                    "items_found": ["ssn", "email"],
                },
            )

        security_plugin.process_response = denying_response

        manager = PluginManager({})
        manager.security_plugins = [security_plugin]
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="get_user_data", id=1)
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"user": "john@example.com", "ssn": "123-45-6789"},
        )

        pipeline = await manager.process_response(request, response)

        # Verify specific error context is preserved (not generic)
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert len(pipeline.stages) > 0
        last_stage = pipeline.stages[-1]
        # Reason is cleared to generic when content is blocked (security-first approach)
        assert last_stage.result.reason == "[blocked]"
        assert last_stage.result.metadata["violation_type"] == "pii_detection"
        assert last_stage.result.metadata["confidence"] == 0.98
        assert last_stage.result.metadata["items_found"] == ["ssn", "email"]

        # When security blocks occur, reasons are cleared to prevent information leakage
        # The generic reason prevents leaking why something was blocked
        assert last_stage.result.reason == "[blocked]"

    async def test_multiple_plugins_last_modification_wins(self):
        """Test integration with multiple security plugins where last modifier wins"""
        # First plugin - PII filter
        pii_plugin = MockModifyingSecurityPlugin()

        # Second plugin - Content filter (higher priority, runs later)
        content_plugin = MockModifyingSecurityPlugin({"priority": 60})

        async def content_filter_response(
            request, response, server_name: Optional[str] = None
        ):
            modified_response = MCPResponse(
                jsonrpc="2.0",
                id=response.id,
                result={"content_filtered": True, "previous": response.result},
            )
            return PluginResult(
                allowed=True,
                reason="Content filtered for appropriate language",
                metadata={"filter_type": "content", "words_replaced": 1},
                modified_content=modified_response,
            )

        content_plugin.process_response = content_filter_response

        manager = PluginManager({})
        manager.security_plugins = [
            pii_plugin,
            content_plugin,
        ]  # Content plugin runs last
        manager._initialized = True

        request = MCPRequest(jsonrpc="2.0", method="get_content", id=1)
        response = MCPResponse(
            jsonrpc="2.0", id=1, result={"text": "Hello world, damn it!"}
        )

        pipeline = await manager.process_response(request, response)

        # Should preserve the LAST modifying plugin's reason but merge all metadata
        assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
        assert len(pipeline.stages) > 0
        last_stage = pipeline.stages[-1]
        # Reason is cleared to generic when content is modified (security-first approach)
        assert last_stage.result.reason == "[modified]"
        # The last plugin's metadata overwrites, not merges
        assert last_stage.result.metadata == {
            "filter_type": "content",
            "words_replaced": 1,
            "plugin": "MockModifyingSecurityPlugin",
        }

        # Response should reflect both modifications (nested structure)
        assert last_stage.result.modified_content.result["content_filtered"] is True
        assert "previous" in last_stage.result.modified_content.result
