"""Tests for plugin execution sequencing and priority system."""

import pytest
from typing import Optional
from unittest.mock import AsyncMock

from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    PipelineOutcome,
)
from gatekit.plugins.manager import PluginManager
from gatekit.protocol.messages import MCPRequest


class MockSecurityPlugin(SecurityPlugin):
    """Mock security plugin for testing priority ordering."""

    def __init__(self, config: dict, plugin_id: str, priority: int = 50):
        super().__init__(config)
        self.plugin_id_value = plugin_id
        self.priority = priority
        self.process_request_mock = AsyncMock(
            return_value=PluginResult(allowed=True, reason="Mock allowed")
        )
        self.process_response_mock = AsyncMock(
            return_value=PluginResult(allowed=True, reason="Mock allowed")
        )
        self.process_notification_mock = AsyncMock(
            return_value=PluginResult(allowed=True, reason="Mock allowed")
        )

    @property
    def plugin_id(self) -> str:
        return self.plugin_id_value

    async def process_request(self, request, server_name: Optional[str] = None):
        return await self.process_request_mock(request, server_name)

    async def process_response(
        self, request, response, server_name: Optional[str] = None
    ):
        return await self.process_response_mock(request, response, server_name)

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ):
        return await self.process_notification_mock(notification, server_name)


class MockAuditingPlugin(AuditingPlugin):
    """Mock auditing plugin for testing priority ordering."""

    def __init__(self, config: dict, plugin_id: str, priority: int = 50):
        super().__init__(config)
        self.plugin_id_value = plugin_id
        self.priority = priority
        self.log_request_mock = AsyncMock()
        self.log_response_mock = AsyncMock()
        self.log_notification_mock = AsyncMock()

    @property
    def plugin_id(self) -> str:
        return self.plugin_id_value

    async def log_request(self, request, decision, server_name: Optional[str] = None):
        return await self.log_request_mock(request, decision, server_name)

    async def log_response(
        self, request, response, decision, server_name: Optional[str] = None
    ):
        return await self.log_response_mock(request, response, decision, server_name)

    async def log_notification(
        self, notification, decision, server_name: Optional[str] = None
    ):
        return await self.log_notification_mock(notification, decision, server_name)


@pytest.fixture
def plugin_manager():
    """Create a plugin manager for testing."""
    manager = PluginManager(plugins_config={})
    manager._initialized = True  # Mark as initialized for unit tests
    return manager


class TestPluginPriorityOrdering:
    """Test plugin execution order based on priority."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    async def test_plugins_execute_in_priority_order(self, plugin_manager):
        """Test that plugins execute in ascending priority order (0-100)."""
        # Create plugins with different priorities
        plugin_high = MockSecurityPlugin({}, "high_priority", priority=10)
        plugin_mid = MockSecurityPlugin({}, "mid_priority", priority=50)
        plugin_low = MockSecurityPlugin({}, "low_priority", priority=90)

        # Add tracking to verify execution order
        execution_order = []

        async def track_execution_high(req, server_name=None):
            execution_order.append("high_priority")
            return PluginResult(allowed=True, reason="high_priority allowed")

        async def track_execution_mid(req, server_name=None):
            execution_order.append("mid_priority")
            return PluginResult(allowed=True, reason="mid_priority allowed")

        async def track_execution_low(req, server_name=None):
            execution_order.append("low_priority")
            return PluginResult(allowed=True, reason="low_priority allowed")

        plugin_high.process_request_mock.side_effect = track_execution_high
        plugin_mid.process_request_mock.side_effect = track_execution_mid
        plugin_low.process_request_mock.side_effect = track_execution_low

        # Register plugins in random order
        plugin_manager.register_security_plugin(plugin_mid)
        plugin_manager.register_security_plugin(plugin_low)
        plugin_manager.register_security_plugin(plugin_high)

        # Process a request
        request = MCPRequest(jsonrpc="2.0", id="test", method="test_method", params={})
        await plugin_manager.process_request(request)

        # Verify execution order (high priority first)
        assert execution_order == ["high_priority", "mid_priority", "low_priority"]

    @pytest.mark.asyncio
    async def test_priority_range_validation(self, plugin_manager):
        """Test that plugin priorities outside 0-100 range are rejected."""
        with pytest.raises(ValueError, match="priority.*must be between 0 and 100"):
            plugin_manager.register_security_plugin(
                MockSecurityPlugin({}, "invalid_high", priority=101)
            )

        with pytest.raises(ValueError, match="priority.*must be between 0 and 100"):
            plugin_manager.register_security_plugin(
                MockSecurityPlugin({}, "invalid_low", priority=-1)
            )

        # Valid boundary values should work
        plugin_manager.register_security_plugin(
            MockSecurityPlugin({}, "valid_min", priority=0)
        )
        plugin_manager.register_security_plugin(
            MockSecurityPlugin({}, "valid_max", priority=100)
        )

        assert len(plugin_manager.security_plugins) == 2

    def test_default_priority_assignments(self):
        """Test that plugins use default priority of 50 when not specified."""
        plugin = MockSecurityPlugin({}, "default_priority")
        assert plugin.priority == 50

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_same_priority_handling(self, plugin_manager):
        """Test behavior when multiple plugins have the same priority."""
        # Create plugins with the same priority
        plugin_a = MockSecurityPlugin({}, "plugin_a", priority=50)
        plugin_b = MockSecurityPlugin({}, "plugin_b", priority=50)
        plugin_c = MockSecurityPlugin({}, "plugin_c", priority=50)

        # Register plugins
        plugin_manager.register_security_plugin(plugin_a)
        plugin_manager.register_security_plugin(plugin_b)
        plugin_manager.register_security_plugin(plugin_c)

        # Process a request
        request = MCPRequest(jsonrpc="2.0", id="test", method="test_method", params={})
        await plugin_manager.process_request(request)

        # All plugins should be called
        assert plugin_a.process_request_mock.called
        assert plugin_b.process_request_mock.called
        assert plugin_c.process_request_mock.called

    @pytest.mark.asyncio
    async def test_early_termination_on_deny(self, plugin_manager):
        """Test that processing stops when a plugin denies the request."""
        # Create plugins with different priorities
        plugin_high = MockSecurityPlugin({}, "high_priority", priority=10)
        plugin_mid = MockSecurityPlugin({}, "mid_priority", priority=50)
        plugin_low = MockSecurityPlugin({}, "low_priority", priority=90)

        # Set the mid-priority plugin to deny
        async def deny_request(req, server_name=None):
            return PluginResult(allowed=False, reason="Denied for testing")

        plugin_mid.process_request_mock.side_effect = deny_request

        # Register plugins
        plugin_manager.register_security_plugin(plugin_high)
        plugin_manager.register_security_plugin(plugin_mid)
        plugin_manager.register_security_plugin(plugin_low)

        # Process a request
        request = MCPRequest(jsonrpc="2.0", id="test", method="test_method", params={})
        pipeline = await plugin_manager.process_request(request)

        # Check the pipeline outcome
        assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
        assert pipeline.blocked_at_stage == "mid_priority"

        # High and mid priority plugins should be called, but not low priority
        assert plugin_high.process_request_mock.called
        assert plugin_mid.process_request_mock.called
        assert not plugin_low.process_request_mock.called

    @pytest.mark.asyncio
    async def test_auditing_plugins_execute_in_registration_order(self, plugin_manager):
        """Test that auditing plugins execute in registration order (no priority sorting)."""
        # Create auditing plugins (priority is ignored for audit plugins)
        plugin_high = MockAuditingPlugin({}, "audit_high", priority=10)
        plugin_mid = MockAuditingPlugin({}, "audit_mid", priority=50)
        plugin_low = MockAuditingPlugin({}, "audit_low", priority=90)

        # Add tracking to verify execution order
        execution_order = []

        async def track_audit_high(req, dec, server_name=None):
            execution_order.append("audit_high")

        async def track_audit_mid(req, dec, server_name=None):
            execution_order.append("audit_mid")

        async def track_audit_low(req, dec, server_name=None):
            execution_order.append("audit_low")

        plugin_high.log_request_mock.side_effect = track_audit_high
        plugin_mid.log_request_mock.side_effect = track_audit_mid
        plugin_low.log_request_mock.side_effect = track_audit_low

        # Register plugins in this order: mid, low, high
        plugin_manager.register_auditing_plugin(plugin_mid)
        plugin_manager.register_auditing_plugin(plugin_low)
        plugin_manager.register_auditing_plugin(plugin_high)

        # Process an audit request
        request = MCPRequest(jsonrpc="2.0", id="test", method="test_method", params={})
        decision = PluginResult(allowed=True, reason="Test")
        await plugin_manager.log_request(request, decision, "test-server")

        # Verify execution order matches registration order (not priority order)
        assert execution_order == ["audit_mid", "audit_low", "audit_high"]


class TestPluginRegistration:
    """Test plugin registration with priority validation."""

    @pytest.mark.asyncio
    async def test_register_security_plugin_with_priority(self, plugin_manager):
        """Test registering security plugins with priority validation."""
        plugin = MockSecurityPlugin({}, "test_plugin", priority=25)
        plugin_manager.register_security_plugin(plugin)

        assert len(plugin_manager.security_plugins) == 1
        assert plugin_manager.security_plugins[0].priority == 25

    @pytest.mark.asyncio
    async def test_register_auditing_plugin_ignores_priority(self, plugin_manager):
        """Test that auditing plugins with priority are accepted without issues."""
        plugin = MockAuditingPlugin({}, "test_plugin", priority=75)
        plugin_manager.register_auditing_plugin(plugin)

        assert len(plugin_manager.auditing_plugins) == 1
        # MockAuditingPlugin bypasses normal init and keeps priority, but it's ignored
        # Real audit plugins remove priority in their __init__
        assert plugin_manager.auditing_plugins[0].priority == 75


class TestPluginSorting:
    """Test internal plugin sorting functionality."""

    def test_sort_plugins_by_priority(self, plugin_manager):
        """Test that plugins are sorted correctly by priority."""
        plugins = [
            MockSecurityPlugin({}, "plugin_90", priority=90),
            MockSecurityPlugin({}, "plugin_10", priority=10),
            MockSecurityPlugin({}, "plugin_50", priority=50),
            MockSecurityPlugin({}, "plugin_30", priority=30),
        ]

        sorted_plugins = plugin_manager._sort_plugins_by_priority(plugins)

        priorities = [p.priority for p in sorted_plugins]
        assert priorities == [10, 30, 50, 90]

        plugin_ids = [p.plugin_id for p in sorted_plugins]
        assert plugin_ids == ["plugin_10", "plugin_30", "plugin_50", "plugin_90"]

    def test_plugins_are_sorted_on_registration(self, plugin_manager):
        """Test that plugins are sorted immediately upon registration."""
        # Register plugins in random priority order
        plugin_90 = MockSecurityPlugin({}, "plugin_90", priority=90)
        plugin_10 = MockSecurityPlugin({}, "plugin_10", priority=10)
        plugin_50 = MockSecurityPlugin({}, "plugin_50", priority=50)

        # Register in random order
        plugin_manager.register_security_plugin(plugin_90)
        plugin_manager.register_security_plugin(plugin_10)
        plugin_manager.register_security_plugin(plugin_50)

        # Check that they are immediately sorted by priority
        priorities = [p.priority for p in plugin_manager.security_plugins]
        assert priorities == [10, 50, 90], f"Expected [10, 50, 90], got {priorities}"

        plugin_ids = [p.plugin_id for p in plugin_manager.security_plugins]
        assert plugin_ids == ["plugin_10", "plugin_50", "plugin_90"]
