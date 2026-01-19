"""Tests for plugin failure metadata consistency.

This test module ensures that plugin failure metadata always includes
the plugin name, even when exceptions occur early in the execution path.
"""

import pytest
from unittest.mock import patch

from gatekit.plugins.interfaces import (
    SecurityPlugin,
    PluginResult,
    PipelineOutcome,
    StageOutcome,
)
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class EarlyFailureSecurityPlugin(SecurityPlugin):
    """Security plugin that fails immediately."""

    def __init__(self, config: dict):
        # Fail before parent init for testing early failures
        if config.get("fail_on_init", False):
            raise ValueError("Init failure before parent constructor")
        super().__init__(config)
        self.fail_on_check = config.get("fail_on_check", False)

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        if self.fail_on_check:
            raise RuntimeError("Request check failed immediately")
        return PluginResult(allowed=True, reason="Test")

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        if self.fail_on_check:
            raise RuntimeError("Response check failed immediately")
        return PluginResult(allowed=True, reason="Test")

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        if self.fail_on_check:
            raise RuntimeError("Notification check failed immediately")
        return PluginResult(allowed=True, reason="Test")


class TestPluginFailureMetadata:
    """Test that plugin failure metadata is consistent."""

    @pytest.mark.asyncio
    async def test_security_plugin_failure_includes_plugin_name_in_metadata(self):
        """Test that security plugin failures always include plugin name in metadata."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "early_failure",
                        "enabled": True,
                        "critical": True,
                        "config": {"fail_on_check": True},
                    }
                ]
            },
            "auditing": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "security":
                    return {"early_failure": EarlyFailureSecurityPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )

            # Check request failure metadata
            pipeline = await manager.process_request(request, server_name="test-server")
            assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
            # Find the error stage
            error_stage = None
            for stage in pipeline.stages:
                if stage.outcome == StageOutcome.ERROR:
                    error_stage = stage
                    break
            assert error_stage is not None
            assert error_stage.plugin_name == "EarlyFailureSecurityPlugin"
            assert "plugin" in error_stage.result.metadata
            assert error_stage.result.metadata["plugin"] == "EarlyFailureSecurityPlugin"

    @pytest.mark.asyncio
    async def test_security_plugin_response_failure_includes_plugin_name(self):
        """Test that security plugin response failures include plugin name in metadata."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "early_failure",
                        "enabled": True,
                        "critical": True,
                        "config": {"fail_on_check": True},
                    }
                ]
            },
            "auditing": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "security":
                    return {"early_failure": EarlyFailureSecurityPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            response = MCPResponse(jsonrpc="2.0", result={"test": "value"}, id="test-1")

            # Check response failure metadata
            pipeline = await manager.process_response(
                request, response, server_name="test-server"
            )
            assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
            # Find the error stage
            error_stage = None
            for stage in pipeline.stages:
                if stage.outcome == StageOutcome.ERROR:
                    error_stage = stage
                    break
            assert error_stage is not None
            assert error_stage.plugin_name == "EarlyFailureSecurityPlugin"
            assert "plugin" in error_stage.result.metadata
            assert error_stage.result.metadata["plugin"] == "EarlyFailureSecurityPlugin"

    @pytest.mark.asyncio
    async def test_security_plugin_notification_failure_includes_plugin_name(self):
        """Test that security plugin notification failures include plugin name in metadata."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "early_failure",
                        "enabled": True,
                        "critical": True,
                        "config": {"fail_on_check": True},
                    }
                ]
            },
            "auditing": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "security":
                    return {"early_failure": EarlyFailureSecurityPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0", method="test/notification", params={"data": "test"}
            )

            # Check notification failure metadata
            pipeline = await manager.process_notification(
                notification, server_name="test-server"
            )
            assert pipeline.pipeline_outcome == PipelineOutcome.ERROR
            # Find the error stage
            error_stage = None
            for stage in pipeline.stages:
                if stage.outcome == StageOutcome.ERROR:
                    error_stage = stage
                    break
            assert error_stage is not None
            assert error_stage.plugin_name == "EarlyFailureSecurityPlugin"
            assert "plugin" in error_stage.result.metadata
            assert error_stage.result.metadata["plugin"] == "EarlyFailureSecurityPlugin"

    @pytest.mark.asyncio
    async def test_plugin_init_failure_still_logs_plugin_name(self):
        """Test that even init failures attempt to identify the plugin."""
        # Use critical=False so init failures are logged rather than raising
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "init_failure",
                        "enabled": True,
                        "config": {"fail_on_init": True, "critical": False},
                    }
                ]
            },
            "auditing": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "security":
                    return {"init_failure": EarlyFailureSecurityPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)

            # Init failures for non-critical security plugins are logged but don't raise
            await manager.load_plugins()

            # Plugin should have failed to load but system continues
            # The error should have been logged with the handler name
            assert len(manager._load_failures) > 0
            assert any(
                "init_failure" in str(failure) for failure in manager._load_failures
            )
