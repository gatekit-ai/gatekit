"""Simplified pipeline-based tests for PluginManager."""

import pytest
from unittest.mock import patch
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.plugins.interfaces import (
    PipelineOutcome,
    ProcessingPipeline,
    StageOutcome,
)
from conftest import (
    MockSecurityPlugin,
    MockAuditingPlugin,
    FailingSecurityPlugin,
    FailingAuditingPlugin,
)


def make_pipeline(
    content,
    outcome=PipelineOutcome.NO_SECURITY_EVALUATION,
    had_security=False,
    stages=None,
):
    return ProcessingPipeline(
        original_content=content,
        stages=stages or [],
        final_content=content,
        pipeline_outcome=outcome,
        had_security_plugin=had_security,
    )


class TestPluginManagerLoading:
    def test_initialization(self):
        manager = PluginManager({})
        assert manager._initialized is False
        assert manager.security_plugins == []
        assert manager.auditing_plugins == []

    @pytest.mark.asyncio
    async def test_load_plugins_empty(self):
        manager = PluginManager({})
        await manager.load_plugins()
        assert manager._initialized is True
        assert manager.security_plugins == []
        assert manager.auditing_plugins == []

    @pytest.mark.asyncio
    async def test_load_plugins_double_call(self):
        manager = PluginManager({})
        await manager.load_plugins()
        with patch("gatekit.plugins.manager.logger") as mock_logger:
            await manager.load_plugins()
            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    @patch("gatekit.plugins.manager.PluginManager._discover_handlers")
    async def test_load_valid_plugins(self, mock_discover):
        def side_effect(category):
            if category == "security":
                return {"mock_security": MockSecurityPlugin}
            if category == "auditing":
                return {"mock_auditing": MockAuditingPlugin}
            return {}

        mock_discover.side_effect = side_effect
        config = {
            "security": {
                "_global": [{"handler": "mock_security", "config": {"enabled": True}}]
            },
            "auditing": {
                "_global": [{"handler": "mock_auditing", "config": {"enabled": True}}]
            },
        }
        manager = PluginManager(config)
        await manager.load_plugins()
        assert len(manager.upstream_security_plugins["_global"]) == 1
        assert len(manager.upstream_auditing_plugins["_global"]) == 1

    def test_get_available_handlers_scope_filtering(self):
        manager = PluginManager({})

        class _GlobalPlugin:
            DISPLAY_SCOPE = "global"

        class _ServerAwarePlugin:
            DISPLAY_SCOPE = "server_aware"

        class _FilesystemPlugin:
            DISPLAY_SCOPE = "server_specific"
            COMPATIBLE_SERVERS = ["secure-filesystem-server"]

        with patch.object(
            manager,
            "_discover_handlers",
            return_value={
                "global": _GlobalPlugin,
                "aware": _ServerAwarePlugin,
                "filesystem_server": _FilesystemPlugin,
            },
        ):
            global_handlers = manager.get_available_handlers(
                "security", scope="_global"
            )
            assert set(global_handlers.keys()) == {"global"}

            server_handlers = manager.get_available_handlers(
                "security",
                scope="filesystem",
                server_identity="secure-filesystem-server",
            )
            assert set(server_handlers.keys()) == {
                "global",
                "aware",
                "filesystem_server",
            }

            incompatible_handlers = manager.get_available_handlers(
                "security",
                scope="filesystem",
                server_identity="untrusted-server",
            )
            assert set(incompatible_handlers.keys()) == {"global", "aware"}

            alias_fallback = manager.get_available_handlers(
                "security",
                scope="filesystem",
                server_identity=None,
                server_alias="secure-filesystem-server",
            )
            assert "filesystem_server" in alias_fallback


class TestPluginManagerProcessing:
    @pytest.mark.asyncio
    async def test_process_request_no_plugins(self):
        manager = PluginManager({})
        pipeline = await manager.process_request(
            MCPRequest(jsonrpc="2.0", method="x", id="1")
        )
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
        assert pipeline.had_security_plugin is False

    @pytest.mark.asyncio
    async def test_process_request_allow(self):
        manager = PluginManager({})
        manager.security_plugins = [MockSecurityPlugin({"allowed": True})]
        manager._initialized = True
        pipeline = await manager.process_request(
            MCPRequest(jsonrpc="2.0", method="x", id="1")
        )
        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
        assert pipeline.had_security_plugin is True

    @pytest.mark.asyncio
    async def test_process_request_block(self):
        manager = PluginManager({})
        manager.security_plugins = [MockSecurityPlugin({"allowed": False})]
        manager._initialized = True
        pipeline = await manager.process_request(
            MCPRequest(jsonrpc="2.0", method="x", id="1")
        )
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage is not None

    @pytest.mark.asyncio
    async def test_process_request_failure(self):
        manager = PluginManager({})
        manager.security_plugins = [FailingSecurityPlugin({})]
        manager._initialized = True
        pipeline = await manager.process_request(
            MCPRequest(jsonrpc="2.0", method="x", id="1")
        )
        assert pipeline.pipeline_outcome in (
            PipelineOutcome.ERROR,
            PipelineOutcome.BLOCKED,
        )
        assert any(s.outcome == StageOutcome.ERROR for s in pipeline.stages)

    @pytest.mark.asyncio
    async def test_auto_initialize_process_request(self):
        manager = PluginManager({})
        assert manager._initialized is False
        await manager.process_request(MCPRequest(jsonrpc="2.0", method="x", id="1"))
        assert manager._initialized is True

    @pytest.mark.asyncio
    async def test_process_response_allow(self):
        manager = PluginManager({})
        manager.security_plugins = [MockSecurityPlugin({"allowed": True})]
        manager._initialized = True
        req = MCPRequest(jsonrpc="2.0", method="x", id="1")
        resp = MCPResponse(jsonrpc="2.0", id="1", result={"ok": True})
        pipeline = await manager.process_response(req, resp)
        assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED

    @pytest.mark.asyncio
    async def test_process_notification_block(self):
        manager = PluginManager({})
        manager.security_plugins = [MockSecurityPlugin({"allowed": False})]
        manager._initialized = True
        notif = MCPNotification(jsonrpc="2.0", method="progress", params={"p": 1})
        pipeline = await manager.process_notification(notif)
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED


class TestPluginManagerAuditing:
    @pytest.mark.asyncio
    async def test_log_request_auto_init(self):
        manager = PluginManager({})
        req = MCPRequest(jsonrpc="2.0", method="x", id="1")
        pipeline = make_pipeline(req)
        await manager.log_request(req, pipeline)
        assert manager._initialized is True

    @pytest.mark.asyncio
    async def test_log_response_invokes_plugins(self):
        manager = PluginManager({})
        plugin1 = MockAuditingPlugin({})
        plugin2 = MockAuditingPlugin({})
        manager.auditing_plugins = [plugin1, plugin2]
        manager._initialized = True
        req = MCPRequest(jsonrpc="2.0", method="x", id="1")
        resp = MCPResponse(jsonrpc="2.0", id="1", result={"ok": True})
        pipeline = make_pipeline(resp)
        await manager.log_response(req, resp, pipeline)
        assert len(plugin1.logged_responses) == 1
        assert len(plugin2.logged_responses) == 1

    @pytest.mark.asyncio
    async def test_auditing_failure_critical(self):
        from gatekit.protocol.errors import AuditingFailureError

        manager = PluginManager({})
        manager.auditing_plugins = [FailingAuditingPlugin({"critical": True})]
        manager._initialized = True
        req = MCPRequest(jsonrpc="2.0", method="x", id="1")
        pipeline = make_pipeline(req)
        with pytest.raises(AuditingFailureError):
            await manager.log_request(req, pipeline)

    @pytest.mark.asyncio
    async def test_log_notification_handles_failure(self):
        manager = PluginManager({})
        good = MockAuditingPlugin({})
        bad = FailingAuditingPlugin({"critical": False})  # Non-critical: should log error but not raise
        manager.auditing_plugins = [good, bad]
        manager._initialized = True
        notif = MCPNotification(jsonrpc="2.0", method="progress", params={"p": 1})
        pipeline = make_pipeline(notif)
        with patch("gatekit.plugins.manager.logger") as mock_logger:
            await manager.log_notification(notif, pipeline)
            mock_logger.error.assert_called()
        assert len(good.logged_notifications) == 1
