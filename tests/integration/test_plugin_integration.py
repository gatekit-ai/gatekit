"""Integration tests for plugin system with other components."""

from typing import Optional
import tempfile
import pytest
from pathlib import Path
import yaml

from gatekit.config import ConfigLoader
from gatekit.plugins import (
    PluginManager,
    SecurityPlugin,
    PluginResult,
)
from gatekit.plugins.interfaces import PipelineOutcome, ProcessingPipeline
from gatekit.protocol.messages import MCPRequest, MCPResponse

# Import mock classes from conftest
from conftest import MockAuditingPlugin


class TestPluginIntegration:
    """Test integration scenarios between plugin system and other components."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config_loader = ConfigLoader()

    @pytest.mark.asyncio
    async def test_plugin_manager_with_yaml_config(self, plugin_yaml_config):
        """Test loading plugins from YAML configuration."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(plugin_yaml_config)
            f.flush()

            try:
                # Load configuration
                self.config_loader.load_from_file(Path(f.name))

                # Parse YAML again to extract plugins section
                with open(f.name, "r") as yaml_file:
                    full_config = yaml.safe_load(yaml_file)

                plugins_config = full_config.get("plugins", {})

                # Create plugin manager with plugins config
                plugin_manager = PluginManager(plugins_config)

                # Load the plugins
                await plugin_manager.load_plugins()

                # Verify plugins were loaded
                assert (
                    len(plugin_manager.upstream_middleware_plugins["test_server"]) == 1
                )
                assert len(plugin_manager.auditing_plugins) == 1

                # Test the loaded middleware plugin
                middleware_plugin = plugin_manager.upstream_middleware_plugins[
                    "test_server"
                ][0]
                assert hasattr(middleware_plugin, "policy")
                assert middleware_plugin.policy == "allowlist"
                assert hasattr(middleware_plugin, "tools")
                assert middleware_plugin.tools == ["test_tool"]

                # Test the loaded auditing plugin
                auditing_plugin = plugin_manager.auditing_plugins[0]
                # FileAuditingPlugin should have output_file attribute
                assert hasattr(auditing_plugin, "output_file")
                # Check the output file ends with expected filename
                assert auditing_plugin.output_file.endswith("test_audit.log")

            finally:
                try:
                    Path(f.name).unlink()
                except PermissionError:
                    pass  # Windows file locking - temp file cleanup handled elsewhere

    @pytest.mark.asyncio
    async def test_end_to_end_request_processing(self):
        """Test complete request processing pipeline with plugins."""

        # Create specialized mock for this test that checks keywords
        class KeywordBlockingSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                super().__init__(config)
                self.blocked_keywords = config.get("blocked_keywords", [])

            async def process_request(self, request, server_name: Optional[str] = None):
                text = str(getattr(request, "params", {}))
                if any(kw in text for kw in self.blocked_keywords):
                    return PluginResult(allowed=False, reason="Keyword blocked")
                return PluginResult(allowed=True, reason="Clean")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Resp ok")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="Notif ok")

        plugin_manager = PluginManager(
            {"security": {"_global": []}, "auditing": {"_global": []}}
        )
        plugin_manager.security_plugins = [
            KeywordBlockingSecurityPlugin({"blocked_keywords": ["malicious"]})
        ]
        auditing_plugin = MockAuditingPlugin({})
        plugin_manager.auditing_plugins = [auditing_plugin]
        plugin_manager._initialized = True

        allowed_request = MCPRequest(
            jsonrpc="2.0", method="test/allowed", id="req-1", params={"data": "safe"}
        )
        blocked_request = MCPRequest(
            jsonrpc="2.0",
            method="test/blocked",
            id="req-2",
            params={"data": "malicious"},
        )

        allowed_pipeline = await plugin_manager.process_request(allowed_request)
        assert allowed_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        await plugin_manager.log_request(allowed_request, allowed_pipeline)
        assert len(auditing_plugin.logged_requests) == 1

        blocked_pipeline = await plugin_manager.process_request(blocked_request)
        assert blocked_pipeline.pipeline_outcome in (
            PipelineOutcome.BLOCKED,
            PipelineOutcome.ERROR,
        )
        assert any(
            s.outcome.name in ("BLOCKED", "ERROR") for s in blocked_pipeline.stages
        )
        await plugin_manager.log_request(blocked_request, blocked_pipeline)
        assert len(auditing_plugin.logged_requests) == 2

    @pytest.mark.asyncio
    async def test_response_logging_integration(self):
        """Test response logging with real MCPResponse objects."""
        # Create plugin manager with mock auditing plugin
        config = {"security": {"_global": []}, "auditing": {"_global": []}}
        plugin_manager = PluginManager(config)

        # Manually add mock auditing plugin for this test
        auditing_plugin = MockAuditingPlugin({})
        plugin_manager.auditing_plugins = [auditing_plugin]
        plugin_manager._initialized = True

        # Create test request to associate with responses
        request1 = MCPRequest(
            jsonrpc="2.0", method="test/request1", id="resp-1", params={}
        )

        # Test successful response
        success_response = MCPResponse(
            jsonrpc="2.0", id="resp-1", result={"status": "success", "data": "test"}
        )

        # Create a pipeline for response logging
        response_pipeline = ProcessingPipeline(
            original_content=success_response,
            stages=[],
            final_content=success_response,
            total_time_ms=0.0,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            blocked_at_stage=None,
            completed_by=None,
            had_security_plugin=False,
            capture_content=True,
        )
        await plugin_manager.log_response(request1, success_response, response_pipeline)

        # Create second test request
        request2 = MCPRequest(
            jsonrpc="2.0", method="test/request2", id="resp-2", params={}
        )

        # Test error response
        error_response = MCPResponse(
            jsonrpc="2.0", id="resp-2", error={"code": -1, "message": "Test error"}
        )

        # Create a pipeline for error response logging
        error_response_pipeline = ProcessingPipeline(
            original_content=error_response,
            stages=[],
            final_content=error_response,
            total_time_ms=0.0,
            pipeline_outcome=PipelineOutcome.ALLOWED,
            blocked_at_stage=None,
            completed_by=None,
            had_security_plugin=False,
            capture_content=True,
        )
        await plugin_manager.log_response(
            request2, error_response, error_response_pipeline
        )

        # Verify both responses were logged
        auditing_plugin = plugin_manager.auditing_plugins[0]
        assert len(auditing_plugin.logged_responses) == 2

        # Check logged responses (stored as tuples: (request, response, pipeline))
        success_log = auditing_plugin.logged_responses[0]
        assert success_log[0].id == "resp-1"  # request
        assert success_log[1].id == "resp-1"  # response
        assert success_log[2].pipeline_outcome == PipelineOutcome.ALLOWED  # pipeline
        assert hasattr(success_log[1], "result")

        # Check error response logging
        error_log = auditing_plugin.logged_responses[1]
        assert error_log[0].id == "resp-2"  # request
        assert error_log[1].id == "resp-2"  # response
        assert error_log[2].pipeline_outcome == PipelineOutcome.ALLOWED  # pipeline
        assert hasattr(error_log[1], "error")

    @pytest.mark.asyncio
    async def test_basic_plugin_system_integration(self):
        """Test basic plugin system integration with minimal configuration.

        This test validates the fundamental integration scenario:
        - Plugin manager initialization with empty plugin lists
        - Real MCPRequest/MCPResponse object creation
        - End-to-end request processing and response logging
        - No mocks - pure integration validation
        """
        # Configuration with empty plugin lists (minimal case)
        config = {"security": [], "auditing": []}

        # Initialize plugin manager
        plugin_manager = PluginManager(config)
        assert plugin_manager is not None
        assert len(plugin_manager.security_plugins) == 0
        assert len(plugin_manager.auditing_plugins) == 0

        # Create real MCP request object
        request = MCPRequest(
            jsonrpc="2.0", method="tools/list", id="test-123", params={}
        )

        # Test request processing (should allow with no plugins)
        pipeline = await plugin_manager.process_request(request)
        assert pipeline is not None
        assert (
            pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        )  # No security evaluation when no plugins
        assert pipeline.had_security_plugin is False

        # Create real MCP response object
        response = MCPResponse(jsonrpc="2.0", id="test-123", result={"tools": []})

        # Test response logging (should work with no plugins)
        # This should not raise any exceptions
        # Build synthetic pipeline representing pass-through (no security evaluation)
        passthrough_pipeline = ProcessingPipeline(
            original_content=response,
            final_content=response,
            pipeline_outcome=PipelineOutcome.NO_SECURITY_EVALUATION,
            had_security_plugin=False,
            stages=[],
        )
        await plugin_manager.log_response(request, response, passthrough_pipeline)

        # Test request logging as well
        await plugin_manager.log_request(request, passthrough_pipeline)

        # Verify the plugin manager remains in a valid state
        assert plugin_manager.security_plugins == []
        assert plugin_manager.auditing_plugins == []
