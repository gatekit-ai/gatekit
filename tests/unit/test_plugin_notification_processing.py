"""Pipeline-based notification processing tests.

All tests now validate outcomes via ProcessingPipeline instead of legacy
decision objects. Security behavior is inferred from PipelineOutcome
and final_content modifications.
"""

from typing import Optional
import json
import pytest

from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    ProcessingPipeline,
    PipelineOutcome,
)
from gatekit.protocol.messages import MCPNotification
from gatekit.config.models import PluginsConfig, PluginConfig
from tests.mocks.notification_mock import NotificationScenarios


class MockSecurityPlugin(SecurityPlugin):
    def __init__(self, config: dict):
        super().__init__(config)
        self.should_block = config.get("block", False)
        self.should_modify = config.get("modify", False)
        self.seen = []

    async def process_request(
        self, request, server_name: Optional[str] = None
    ):  # pragma: no cover (not used here)
        return PluginResult(allowed=True)

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):  # pragma: no cover
        return PluginResult(allowed=True)

    async def process_notification(
        self, notification: MCPNotification, server_name: Optional[str] = None
    ) -> PluginResult:
        self.seen.append(notification)
        if self.should_block:
            return PluginResult(allowed=False, reason="Blocked by policy")
        if self.should_modify:
            modified = MCPNotification(
                jsonrpc=notification.jsonrpc,
                method=notification.method,
                params={**notification.params, "modified": True},
            )
            return PluginResult(
                allowed=True, reason="Modified", modified_content=modified
            )
        return PluginResult(allowed=True, reason="Allowed")


class MockAuditingPlugin(AuditingPlugin):
    def __init__(self, config: dict):
        super().__init__(config)
        self.logged_notifications = []  # (notification, pipeline)

    async def log_request(
        self, request, pipeline, server_name: Optional[str] = None
    ):  # pragma: no cover
        pass

    async def log_response(
        self, request, response, pipeline, server_name: Optional[str] = None
    ):  # pragma: no cover
        pass

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ):
        self.logged_notifications.append((notification, pipeline))


@pytest.fixture
def plugin_config():
    return PluginsConfig(
        security={
            "_global": [PluginConfig(handler="mock_security", config={"enabled": True})]
        },
        auditing={
            "_global": [PluginConfig(handler="mock_auditing", config={"enabled": True})]
        },
    )


def _setup_manager(plugin_config, security_plugins, auditing_plugins):
    pm = PluginManager(plugin_config)
    pm.security_plugins = security_plugins
    pm.auditing_plugins = auditing_plugins
    pm._initialized = True
    return pm


@pytest.mark.asyncio
async def test_security_plugin_allows_notification(plugin_config):
    sec = MockSecurityPlugin({})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [sec], [aud])
    n = NotificationScenarios.initialized_notification()
    pipeline = await pm.process_notification(n)
    assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
    assert len(sec.seen) == 1
    assert sec.seen[0].method == "notifications/initialized"


@pytest.mark.asyncio
async def test_security_plugin_blocks_notification(plugin_config):
    sec = MockSecurityPlugin({"block": True})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [sec], [aud])
    n = NotificationScenarios.log_message_notification("error", "Sensitive")
    pipeline = await pm.process_notification(n)
    assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
    assert len(sec.seen) == 1


@pytest.mark.asyncio
async def test_security_plugin_modifies_notification(plugin_config):
    sec = MockSecurityPlugin({"modify": True})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [sec], [aud])
    n = NotificationScenarios.progress_notification("tok", 42)
    pipeline = await pm.process_notification(n)
    assert pipeline.pipeline_outcome == PipelineOutcome.MODIFIED
    # Modification should result in final_content carrying modified param
    assert isinstance(pipeline.final_content, MCPNotification)
    assert pipeline.final_content.params.get("modified") is True


@pytest.mark.asyncio
async def test_auditing_plugin_logs_notifications(plugin_config):
    sec = MockSecurityPlugin({})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [sec], [aud])
    n = NotificationScenarios.resource_change_notification("prompts")
    pipeline = await pm.process_notification(n)
    await pm.log_notification(n, pipeline)
    assert len(aud.logged_notifications) == 1
    logged_n, logged_pipeline = aud.logged_notifications[0]
    assert logged_n.method == "notifications/prompts/list_changed"
    assert logged_pipeline.pipeline_outcome in (
        PipelineOutcome.ALLOWED,
        PipelineOutcome.NO_SECURITY_EVALUATION,
    )


@pytest.mark.asyncio
async def test_multiple_security_plugins_modify_notification(plugin_config):
    # Add second modifying plugin
    p1 = MockSecurityPlugin({})
    p2 = MockSecurityPlugin({"modify": True})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [p1, p2], [aud])
    n = NotificationScenarios.cancelled_notification("req-9", "User cancelled")
    pipeline = await pm.process_notification(n)
    assert len(p1.seen) == 1 and len(p2.seen) == 1
    assert isinstance(pipeline.final_content, MCPNotification)
    assert pipeline.final_content.params.get("modified") is True


@pytest.mark.asyncio
async def test_json_auditing_plugin_logs_notifications(tmp_path):
    log_file = tmp_path / "audit.log"
    config = {
        "security": {"_global": []},
        "auditing": {
            "_global": [
                {
                    "handler": "audit_jsonl",
                    "enabled": True,
                    "config": {
                        "output_file": str(log_file),
                        "format": "json",
                        "include_notifications": True,
                    },
                }
            ]
        },
    }
    pm = PluginManager(config)
    await pm.load_plugins()
    notifications = [
        NotificationScenarios.initialized_notification(),
        NotificationScenarios.progress_notification("task", 10),
        NotificationScenarios.log_message_notification("info", "Started"),
    ]
    for n in notifications:
        pipeline = await pm.process_notification(n)
        await pm.log_notification(n, pipeline)
    lines = log_file.read_text().splitlines()
    assert len(lines) == 3
    for i, line in enumerate(lines):
        entry = json.loads(line)
        assert entry["event_type"].upper() == "NOTIFICATION"
        assert entry["method"] == notifications[i].method
        assert "pipeline" in entry  # Full pipeline details with per-stage metadata


@pytest.mark.asyncio
async def test_plugin_error_during_notification_processing(plugin_config):
    class ErrorPlugin(MockSecurityPlugin):
        async def process_notification(
            self, notification, server_name: Optional[str] = None
        ):
            raise RuntimeError("Injected failure")

    err = ErrorPlugin({})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [err], [aud])
    n = NotificationScenarios.error_notification("Boom", {"code": 500})
    pipeline = await pm.process_notification(n)
    # Manager converts failure into blocked/error outcome via stage result
    assert pipeline.pipeline_outcome in (PipelineOutcome.BLOCKED, PipelineOutcome.ERROR)


@pytest.mark.asyncio
async def test_basic_notification_structure_validation(plugin_config):
    # Plugin that rejects notifications missing params (simulate structure check)
    class ValidatingPlugin(MockSecurityPlugin):
        async def process_notification(
            self, notification, server_name: Optional[str] = None
        ):
            if (
                notification.method.startswith("notifications/")
                and notification.params is None
            ):
                return PluginResult(allowed=False, reason="Invalid structure")
            return PluginResult(allowed=True, reason="OK")

    val = ValidatingPlugin({})
    aud = MockAuditingPlugin({})
    pm = _setup_manager(plugin_config, [val], [aud])
    n = NotificationScenarios.initialized_notification()
    pipeline = await pm.process_notification(n)
    assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED


class ServerNameTrackingAuditPlugin(AuditingPlugin):
    """Auditing plugin that tracks server_name passed to log_notification."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.logged_notifications = []  # (notification, pipeline, server_name)

    async def log_request(self, request, pipeline, server_name: Optional[str] = None):
        pass

    async def log_response(
        self, request, response, pipeline, server_name: Optional[str] = None
    ):
        pass

    async def log_notification(
        self,
        notification: MCPNotification,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ):
        self.logged_notifications.append((notification, pipeline, server_name))


@pytest.mark.asyncio
async def test_server_name_passed_to_auditing_plugin_for_notifications():
    """Verify server_name is correctly passed through to auditing plugins."""
    config = PluginsConfig(
        security={"_global": []},
        auditing={"_global": [PluginConfig(handler="mock", config={"enabled": True})]},
    )
    aud = ServerNameTrackingAuditPlugin({})
    pm = PluginManager(config)
    pm.auditing_plugins = [aud]
    pm._initialized = True

    n = NotificationScenarios.log_message_notification("info", "Test message")
    pipeline = await pm.process_notification(n, server_name="test-server")
    await pm.log_notification(n, pipeline, server_name="test-server")

    assert len(aud.logged_notifications) == 1
    logged_n, logged_pipeline, logged_server = aud.logged_notifications[0]
    assert logged_n.method == "notifications/message"
    assert logged_server == "test-server"


@pytest.mark.asyncio
async def test_server_specific_auditing_receives_notifications_with_server_name(
    tmp_path,
):
    """Verify server-specific auditing plugins receive notifications with correct server_name.

    When the same handler (audit_jsonl) is configured at both global and server level,
    the server-specific config OVERRIDES the global one for that server.
    """
    server_log = tmp_path / "server.jsonl"

    config = {
        "security": {"_global": []},
        "auditing": {
            # Server-specific config - will be used for my-server notifications
            "my-server": [
                {
                    "handler": "audit_jsonl",
                    "enabled": True,
                    "config": {
                        "output_file": str(server_log),
                        "include_notification_body": True,
                    },
                }
            ],
        },
    }
    pm = PluginManager(config)
    await pm.load_plugins()

    n = NotificationScenarios.log_message_notification("info", "Server notification")
    pipeline = await pm.process_notification(n, server_name="my-server")
    await pm.log_notification(n, pipeline, server_name="my-server")

    # Server-specific log should have the notification with correct server_name
    server_lines = server_log.read_text().splitlines()
    assert len(server_lines) == 1
    server_entry = json.loads(server_lines[0])
    assert server_entry["event_type"] == "NOTIFICATION"
    assert server_entry["server_name"] == "my-server"
    # Server-specific config has include_notification_body=True
    assert "notification_body" in server_entry


@pytest.mark.asyncio
async def test_notification_with_null_server_name_only_goes_to_global(tmp_path):
    """Notifications with null server_name should only go to _global plugins."""
    global_log = tmp_path / "global.jsonl"
    server_log = tmp_path / "server.jsonl"

    config = {
        "security": {"_global": []},
        "auditing": {
            "_global": [
                {
                    "handler": "audit_jsonl",
                    "enabled": True,
                    "config": {"output_file": str(global_log)},
                }
            ],
            "specific-server": [
                {
                    "handler": "audit_jsonl",
                    "enabled": True,
                    "config": {"output_file": str(server_log)},
                }
            ],
        },
    }
    pm = PluginManager(config)
    await pm.load_plugins()

    n = NotificationScenarios.progress_notification("task", 50)
    # Simulate notification with no server context (e.g., client-originated)
    pipeline = await pm.process_notification(n, server_name=None)
    await pm.log_notification(n, pipeline, server_name=None)

    # Global log should have the notification
    global_lines = global_log.read_text().splitlines()
    assert len(global_lines) == 1

    # Server-specific log should NOT have the notification (different server)
    assert not server_log.exists() or server_log.read_text().strip() == ""
