"""Tests for critical auditing plugin functionality.

This test module verifies that auditing plugins can be configured as critical,
meaning that audit failures will halt system operation when critical=True.
"""

import pytest
from unittest.mock import patch

from gatekit.plugins.interfaces import (
    AuditingPlugin,
    ProcessingPipeline,
    PipelineOutcome,
)
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest, MCPResponse
from gatekit.protocol.errors import AuditingFailureError


class MockCriticalAuditingPlugin(AuditingPlugin):
    """Mock auditing plugin that can simulate failures (pipeline-based)."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.fail_on_log = config.get("fail_on_log", False)
        self.logged_requests = []  # (request, pipeline, server_name)
        self.logged_responses = []  # (request, response, pipeline, server_name)

    async def log_request(
        self, request: MCPRequest, pipeline: ProcessingPipeline, server_name: str
    ) -> None:
        if self.fail_on_log:
            raise RuntimeError("Simulated audit failure on request")
        self.logged_requests.append((request, pipeline, server_name))

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        pipeline: ProcessingPipeline,
        server_name: str,
    ) -> None:
        if self.fail_on_log:
            raise RuntimeError("Simulated audit failure on response")
        self.logged_responses.append((request, response, pipeline, server_name))

    async def log_notification(
        self, notification: dict, pipeline: ProcessingPipeline, server_name: str
    ) -> None:
        if self.fail_on_log:
            raise RuntimeError("Simulated audit failure on notification")


class TestCriticalAuditingConfiguration:
    """Test that auditing plugins respect critical configuration."""

    def test_auditing_plugin_respects_critical_true(self):
        """Auditing plugins should honor critical=True from config."""
        config = {"critical": True, "fail_on_log": False}
        plugin = MockCriticalAuditingPlugin(config)

        # Plugin should have critical=True when configured
        assert (
            plugin.critical is True
        ), "Auditing plugin should respect critical=True configuration"

    def test_auditing_plugin_respects_critical_false(self):
        """Auditing plugins should honor critical=False from config."""
        config = {"critical": False, "fail_on_log": False}
        plugin = MockCriticalAuditingPlugin(config)

        # Plugin should have critical=False when configured
        assert (
            plugin.critical is False
        ), "Auditing plugin should respect critical=False configuration"

    def test_auditing_plugin_defaults_to_critical(self):
        """Auditing plugins should default to critical=True when not specified."""
        config = {"fail_on_log": False}
        plugin = MockCriticalAuditingPlugin(config)

        # All plugins default to critical=True (fail-closed)
        assert (
            plugin.critical is True
        ), "All plugins should default to critical=True (fail-closed)"


class TestCriticalAuditingBehavior:
    """Test that critical auditing plugins properly halt on failure."""

    @pytest.mark.asyncio
    async def test_critical_audit_failure_raises_error_on_request(self):
        """Critical audit plugin failures should raise AuditingFailureError on request logging."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "mock_critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_on_log": True,
                        },
                    }
                ]
            },
            "security": {"_global": []},
        }

        # Mock the plugin discovery to include our test plugin
        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "auditing":
                    return {"mock_critical_audit": MockCriticalAuditingPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            # Create test request
            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            pipeline = ProcessingPipeline(
                original_content=request,
                stages=[],
                final_content=request,
                pipeline_outcome=PipelineOutcome.ALLOWED,
                had_security_plugin=True,
            )
            # Critical audit failure should raise AuditingFailureError
            with pytest.raises(
                AuditingFailureError, match="Critical auditing plugin.*failed"
            ):
                await manager.log_request(request, pipeline, server_name="test-server")

    @pytest.mark.asyncio
    async def test_critical_audit_failure_raises_error_on_response(self):
        """Critical audit plugin failures should raise AuditingFailureError on response logging."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "mock_critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_on_log": True,
                        },
                    }
                ]
            },
            "security": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "auditing":
                    return {"mock_critical_audit": MockCriticalAuditingPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            response = MCPResponse(jsonrpc="2.0", result={"status": "ok"}, id="test-1")
            pipeline = ProcessingPipeline(
                original_content=response,
                stages=[],
                final_content=response,
                pipeline_outcome=PipelineOutcome.ALLOWED,
                had_security_plugin=True,
            )
            # Critical audit failure should raise AuditingFailureError
            with pytest.raises(
                AuditingFailureError, match="Critical auditing plugin.*failed"
            ):
                await manager.log_response(
                    request, response, pipeline, server_name="test-server"
                )

    @pytest.mark.asyncio
    async def test_non_critical_audit_failure_continues_on_request(self):
        """Non-critical audit plugin failures should not raise errors on request logging."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "mock_audit",
                        "config": {
                            "enabled": True,
                            "critical": False,
                            "fail_on_log": True,
                        },
                    }
                ]
            },
            "security": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "auditing":
                    return {"mock_audit": MockCriticalAuditingPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            pipeline = ProcessingPipeline(
                original_content=request,
                stages=[],
                final_content=request,
                pipeline_outcome=PipelineOutcome.ALLOWED,
                had_security_plugin=True,
            )
            # Non-critical audit failure should NOT raise an error
            await manager.log_request(request, pipeline, server_name="test-server")
            # Should complete without exception

    @pytest.mark.asyncio
    async def test_mixed_critical_and_non_critical_audit_plugins(self):
        """Test multiple audit plugins with mixed critical settings."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "mock_non_critical",
                        "config": {
                            "enabled": True,
                            "critical": False,
                            "fail_on_log": True,
                        },
                    },
                    {
                        "handler": "mock_critical",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_on_log": False,
                        },
                    },
                ]
            },
            "security": {"_global": []},
        }

        class NonCriticalPlugin(MockCriticalAuditingPlugin):
            pass

        class CriticalPlugin(MockCriticalAuditingPlugin):
            pass

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "auditing":
                    return {
                        "mock_non_critical": NonCriticalPlugin,
                        "mock_critical": CriticalPlugin,
                    }
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            pipeline = ProcessingPipeline(
                original_content=request,
                stages=[],
                final_content=request,
                pipeline_outcome=PipelineOutcome.ALLOWED,
                had_security_plugin=True,
            )
            # Should complete even though non-critical plugin fails because critical plugin succeeds
            await manager.log_request(request, pipeline, server_name="test-server")

            # Verify the critical plugin was executed
            critical_plugins = [
                p
                for p in manager.upstream_auditing_plugins["_global"]
                if isinstance(p, CriticalPlugin)
            ]
            assert len(critical_plugins) == 1
            assert len(critical_plugins[0].logged_requests) == 1


class TestCriticalAuditingInitialization:
    """Test that critical audit plugins halt system on initialization failure."""

    @pytest.mark.asyncio
    async def test_critical_audit_init_failure_halts_system(self):
        """Critical audit plugin initialization failure should halt the system."""

        class FailingInitPlugin(AuditingPlugin):
            def __init__(self, config: dict):
                super().__init__(config)
                if config.get("fail_init", False):
                    raise RuntimeError("Simulated initialization failure")

            async def log_request(self, request, pipeline, server_name):
                pass

            async def log_response(self, request, response, pipeline, server_name):
                pass

            async def log_notification(self, notification, pipeline, server_name):
                pass

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "failing_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_init": True,
                        },
                    }
                ]
            },
            "security": {"_global": []},
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:

            def discover_side_effect(category):
                if category == "auditing":
                    return {"failing_audit": FailingInitPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)

            # Critical audit init failure should raise an error
            with pytest.raises(RuntimeError, match="Simulated initialization failure"):
                await manager.load_plugins()
