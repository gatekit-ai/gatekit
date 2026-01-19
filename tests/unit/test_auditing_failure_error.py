"""Explicit tests for AuditingFailureError being raised.

This test module provides focused tests to lock down the behavior
of critical auditing plugins raising AuditingFailureError on failure.
"""

import pytest
from unittest.mock import patch

from gatekit.plugins.interfaces import AuditingPlugin, PluginResult
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.protocol.errors import AuditingFailureError


class CriticalAuditPlugin(AuditingPlugin):
    """Test auditing plugin that can be configured to fail."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.fail_request = config.get("fail_request", False)
        self.fail_response = config.get("fail_response", False)
        self.fail_notification = config.get("fail_notification", False)

    async def log_request(
        self, request: MCPRequest, decision: PluginResult, server_name: str
    ) -> None:
        if self.fail_request:
            raise Exception("Request audit failed")

    async def log_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        decision: PluginResult,
        server_name: str,
    ) -> None:
        if self.fail_response:
            raise Exception("Response audit failed")

    async def log_notification(
        self, notification: MCPNotification, decision: PluginResult, server_name: str
    ) -> None:
        if self.fail_notification:
            raise Exception("Notification audit failed")


class TestAuditingFailureError:
    """Test that critical auditing plugin failures raise AuditingFailureError."""

    @pytest.mark.asyncio
    async def test_critical_log_request_failure_raises_auditing_failure_error(self):
        """Test that critical audit plugin failure on log_request raises AuditingFailureError."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_request": True,
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
                    return {"critical_audit": CriticalAuditPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            decision = PluginResult(allowed=True, reason="Test")

            # Should raise AuditingFailureError specifically
            with pytest.raises(AuditingFailureError) as exc_info:
                await manager.log_request(request, decision, server_name="test-server")

            # Verify error message contains plugin info
            assert "Critical auditing plugin" in str(exc_info.value)
            assert "failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_critical_log_response_failure_raises_auditing_failure_error(self):
        """Test that critical audit plugin failure on log_response raises AuditingFailureError."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_response": True,
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
                    return {"critical_audit": CriticalAuditPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            response = MCPResponse(jsonrpc="2.0", result={"test": "value"}, id="test-1")
            decision = PluginResult(allowed=True, reason="Test")

            # Should raise AuditingFailureError specifically
            with pytest.raises(AuditingFailureError) as exc_info:
                await manager.log_response(
                    request, response, decision, server_name="test-server"
                )

            # Verify error message
            assert "Critical auditing plugin" in str(exc_info.value)
            assert "failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_critical_audit_notification_failure_raises_auditing_failure_error(
        self,
    ):
        """Test that critical audit plugin failure on log_notification raises AuditingFailureError."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_notification": True,
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
                    return {"critical_audit": CriticalAuditPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0", method="test/notification", params={"data": "test"}
            )
            decision = PluginResult(allowed=True, reason="Test")

            # Should raise AuditingFailureError specifically
            with pytest.raises(AuditingFailureError) as exc_info:
                await manager.log_notification(
                    notification, decision, server_name="test-server"
                )

            # Verify error message
            assert "Critical auditing plugin" in str(exc_info.value)
            assert "failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_non_critical_audit_failure_does_not_raise(self):
        """Test that non-critical audit plugin failures do not raise errors."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "non_critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": False,  # Non-critical - must be inside config
                            "fail_request": True,
                            "fail_response": True,
                            "fail_notification": True,
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
                    return {"non_critical_audit": CriticalAuditPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            response = MCPResponse(jsonrpc="2.0", result={"test": "value"}, id="test-1")
            notification = MCPNotification(
                jsonrpc="2.0", method="test/notification", params={"data": "test"}
            )
            decision = PluginResult(allowed=True, reason="Test")

            # None of these should raise errors for non-critical plugin
            await manager.log_request(request, decision, server_name="test-server")
            await manager.log_response(
                request, response, decision, server_name="test-server"
            )
            await manager.log_notification(
                notification, decision, server_name="test-server"
            )

            # Test passes if we reach here without exceptions

    @pytest.mark.asyncio
    async def test_auditing_failure_error_contains_original_exception(self):
        """Test that AuditingFailureError message contains the original exception details."""
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "critical_audit",
                        "config": {
                            "enabled": True,
                            "critical": True,
                            "fail_request": True,
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
                    return {"critical_audit": CriticalAuditPlugin}
                return {}

            mock_discover.side_effect = discover_side_effect

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0", method="test/method", params={}, id="test-1"
            )
            decision = PluginResult(allowed=True, reason="Test")

            with pytest.raises(AuditingFailureError) as exc_info:
                await manager.log_request(request, decision, server_name="test-server")

            # Verify the original error message is preserved
            error_str = str(exc_info.value)
            assert (
                "Request audit failed" in error_str
                or "Exception: Request audit failed" in error_str
            )
