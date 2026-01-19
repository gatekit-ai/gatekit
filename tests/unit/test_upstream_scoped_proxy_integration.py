"""Unit tests for upstream-scoped proxy server integration (TDD - RED phase).

This test file contains failing tests that define the requirements for integrating
upstream-scoped plugin resolution into the proxy server request processing.
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from typing import Dict, Any

from gatekit.proxy.server import MCPProxy
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    ProcessingPipeline,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse


class MockSecurityPlugin(SecurityPlugin):
    """Mock security plugin for testing."""

    def __init__(self, config: Dict[str, Any]):
        self.handler = config.get("policy_name", config.get("policy", "mock_security"))
        self.priority = config.get("priority", 50)
        self.decision_to_return = config.get(
            "decision", PluginResult(allowed=True, reason="Mock plugin allowed")
        )
        self.called_requests = []
        self.called_responses = []
        self.called_notifications = []
        super().__init__(config)

    @property
    def plugin_id(self) -> str:
        return self.handler

    async def process_request(self, request: MCPRequest, **kwargs) -> PluginResult:
        self.called_requests.append(request)
        return self.decision_to_return

    async def process_response(
        self, request: MCPRequest, response, **kwargs
    ) -> PluginResult:
        self.called_responses.append(response)
        return self.decision_to_return

    async def process_notification(self, notification, **kwargs) -> PluginResult:
        self.called_notifications.append(notification)
        return self.decision_to_return


class MockAuditingPlugin(AuditingPlugin):
    """Mock auditing plugin for testing."""

    def __init__(self, config: Dict[str, Any]):
        self.handler = config.get("policy_name", "mock_auditing")
        self.priority = config.get("priority", 50)
        self.logged_requests = []
        self.logged_responses = []
        self.logged_notifications = []
        super().__init__(config)

    @property
    def plugin_id(self) -> str:
        return self.handler

    async def log_request(
        self, request: MCPRequest, pipeline: ProcessingPipeline, **kwargs
    ) -> None:
        self.logged_requests.append(
            {
                "request": request,
                "pipeline": pipeline,
                "plugin": self.plugin_id,
                "server_name": kwargs.get("server_name"),
            }
        )

    async def log_response(
        self, request: MCPRequest, response, pipeline: ProcessingPipeline, **kwargs
    ) -> None:
        self.logged_responses.append(
            {
                "request": request,
                "response": response,
                "pipeline": pipeline,
                "plugin": self.plugin_id,
                "server_name": kwargs.get("server_name"),
            }
        )

    async def log_notification(
        self, notification, decision: PluginResult, **kwargs
    ) -> None:
        self.logged_notifications.append(
            {
                "notification": notification,
                "decision": decision,
                "plugin": self.plugin_id,
                "server_name": kwargs.get("server_name"),
            }
        )


class TestUpstreamScopedRequestProcessing:
    """Test upstream-scoped request processing in the proxy server.

    These tests define how the proxy server should use upstream-specific
    plugin sets when processing requests.
    """

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_process_request_uses_upstream_specific_plugins(self):
        """Test that request processing uses upstream-specific plugins."""
        # Test configuration with different plugins for different upstreams
        config = {
            "plugins": {
                "security": {
                    "github": [
                        {
                            "handler": "github_security",
                            "config": {"policy_name": "github_security"},
                        }
                    ],
                    "file-system": [
                        {
                            "handler": "file_security",
                            "config": {"policy_name": "file_security"},
                        }
                    ],
                },
                "auditing": {
                    "github": [
                        {
                            "handler": "github_audit",
                            "config": {"policy_name": "github_audit"},
                        }
                    ],
                    "file-system": [
                        {
                            "handler": "file_audit",
                            "config": {"policy_name": "file_audit"},
                        }
                    ],
                },
            }
        }

        # Use a real PluginManager instance
        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "github_security": MockSecurityPlugin,
                "file_security": MockSecurityPlugin,
                "github_audit": MockAuditingPlugin,
                "file_audit": MockAuditingPlugin,
            }

            plugin_manager = PluginManager(config["plugins"])
            await plugin_manager.load_plugins()

            github_audit_plugin = plugin_manager.get_plugins_for_upstream("github")[
                "auditing"
            ][0]
            file_system_audit_plugin = plugin_manager.get_plugins_for_upstream(
                "file-system"
            )["auditing"][0]

            # Create a minimal mock config
            mock_config = Mock()
            mock_config.transport = "stdio"
            mock_config.plugins = None  # We'll use dependency injection instead
            mock_config.upstreams = []  # Empty list for len() call in logging

            # Create a mock server manager
            mock_server_manager = Mock()

            # Use dependency injection to provide the real plugin manager
            proxy = MCPProxy(
                mock_config,
                plugin_manager=plugin_manager,
                server_manager=mock_server_manager,
            )
            proxy.transport = AsyncMock()
            proxy._is_running = True  # Set proxy as running

            # Mock the routing to isolate the request processing logic
            with patch.object(proxy, "_route_request") as mock_route_request:
                # Mock route request will return a simple response
                def mock_route_side_effect(request):
                    return MCPResponse(jsonrpc="2.0", id=request.id, result={})

                mock_route_request.side_effect = mock_route_side_effect

                # Test request for github upstream
                github_request = MCPRequest(
                    jsonrpc="2.0",
                    id="test1",
                    method="tools/call",
                    params={"name": "github__git_clone", "arguments": {}},
                )

                await proxy.handle_request(github_request)

                # Verify that the correct audit plugin was used
                assert len(github_audit_plugin.logged_requests) == 1
                assert github_audit_plugin.logged_requests[0]["server_name"] == "github"
                assert (
                    github_audit_plugin.logged_requests[0]["plugin"] == "github_audit"
                )
                assert len(file_system_audit_plugin.logged_requests) == 0

                # Test request for file-system upstream
                file_request = MCPRequest(
                    jsonrpc="2.0",
                    id="test2",
                    method="tools/call",
                    params={"name": "file-system__read_file", "arguments": {}},
                )

                await proxy.handle_request(file_request)

                # Verify that the correct audit plugin was used
                assert len(file_system_audit_plugin.logged_requests) == 1
                assert (
                    file_system_audit_plugin.logged_requests[0]["server_name"]
                    == "file-system"
                )
                assert (
                    file_system_audit_plugin.logged_requests[0]["plugin"]
                    == "file_audit"
                )
                # Ensure the other plugin was not called again
                assert len(github_audit_plugin.logged_requests) == 1


class TestUpstreamScopedResponseProcessing:
    """Test upstream-scoped response processing in the proxy server."""

    @pytest.mark.asyncio
    async def test_process_response_uses_upstream_specific_plugins(self):
        """Test that response processing uses upstream-specific plugins."""
        config = {
            "plugins": {
                "auditing": {
                    "github": [
                        {
                            "handler": "github_audit",
                            "config": {"policy_name": "github_audit"},
                        }
                    ],
                    "file-system": [
                        {
                            "handler": "file_audit",
                            "config": {"policy_name": "file_audit"},
                        }
                    ],
                }
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "github_audit": MockAuditingPlugin,
                "file_audit": MockAuditingPlugin,
            }

            plugin_manager = PluginManager(config["plugins"])
            await plugin_manager.load_plugins()

            github_audit_plugin = plugin_manager.get_plugins_for_upstream("github")[
                "auditing"
            ][0]
            file_system_audit_plugin = plugin_manager.get_plugins_for_upstream(
                "file-system"
            )["auditing"][0]

            mock_config = Mock()
            mock_config.transport = "stdio"
            mock_config.plugins = None
            mock_config.upstreams = []

            mock_server_manager = Mock()

            proxy = MCPProxy(
                mock_config,
                plugin_manager=plugin_manager,
                server_manager=mock_server_manager,
            )
            proxy.transport = AsyncMock()
            proxy._is_running = True

            with patch.object(proxy, "_route_request") as mock_route_request:
                mock_route_request.return_value = MCPResponse(
                    jsonrpc="2.0", id="test1", result={}
                )

                github_request = MCPRequest(
                    jsonrpc="2.0",
                    id="test1",
                    method="tools/call",
                    params={"name": "github__git_clone", "arguments": {}},
                )

                await proxy.handle_request(github_request)

                assert len(github_audit_plugin.logged_responses) == 1
                assert (
                    github_audit_plugin.logged_responses[0]["server_name"] == "github"
                )
                assert len(file_system_audit_plugin.logged_responses) == 0

                mock_route_request.return_value = MCPResponse(
                    jsonrpc="2.0", id="test2", result={}
                )
                file_request = MCPRequest(
                    jsonrpc="2.0",
                    id="test2",
                    method="tools/call",
                    params={"name": "file-system__read_file", "arguments": {}},
                )

                await proxy.handle_request(file_request)

                assert len(file_system_audit_plugin.logged_responses) == 1
                assert (
                    file_system_audit_plugin.logged_responses[0]["server_name"]
                    == "file-system"
                )
                assert len(github_audit_plugin.logged_responses) == 1


class TestUpstreamPluginOverrideScenarios:
    """Test upstream plugin override and denial scenarios."""

    @pytest.mark.asyncio
    async def test_security_plugin_denial_stops_processing(self):
        """Test that a security plugin denial stops request processing and auditing."""
        config = {
            "plugins": {
                "security": {
                    "github": [
                        {
                            "handler": "deny_all",
                            "config": {
                                "policy_name": "deny_all",
                                "decision": PluginResult(
                                    allowed=False, reason="Test Denial"
                                ),
                            },
                        }
                    ]
                },
                "auditing": {
                    "github": [
                        {
                            "handler": "github_audit",
                            "config": {"policy_name": "github_audit"},
                        }
                    ]
                },
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "deny_all": MockSecurityPlugin,
                "github_audit": MockAuditingPlugin,
            }

            plugin_manager = PluginManager(config["plugins"])
            await plugin_manager.load_plugins()

            github_audit_plugin = plugin_manager.get_plugins_for_upstream("github")[
                "auditing"
            ][0]

            mock_config = Mock()
            mock_config.transport = "stdio"
            mock_config.plugins = None
            mock_config.upstreams = []

            mock_server_manager = Mock()

            proxy = MCPProxy(
                mock_config,
                plugin_manager=plugin_manager,
                server_manager=mock_server_manager,
            )
            proxy.transport = AsyncMock()
            proxy._is_running = True

            with patch.object(proxy, "_route_request") as mock_route_request:
                github_request = MCPRequest(
                    jsonrpc="2.0",
                    id="test1",
                    method="tools/call",
                    params={"name": "github__git_clone", "arguments": {}},
                )

                response = await proxy.handle_request(github_request)

                # Verify the request was not routed
                mock_route_request.assert_not_called()

                # Verify the response is an error
                assert response.error is not None
                assert response.error["code"] == -32000
                # Security-first approach means specific reasons are cleared, generic message is used
                assert "Request blocked" in response.error["message"]

                # Verify the audit log reflects the denial
                assert len(github_audit_plugin.logged_requests) == 1
                assert (
                    github_audit_plugin.logged_requests[0][
                        "pipeline"
                    ].pipeline_outcome.value
                    == "blocked"
                )

                # Even when a request is denied, the error response should be logged
                assert len(github_audit_plugin.logged_responses) == 1
                logged_response = github_audit_plugin.logged_responses[0]
                assert logged_response["response"].error is not None
                assert logged_response["response"].error["code"] == -32000

    @pytest.mark.asyncio
    async def test_global_plugins_are_used_and_overridden(self):
        """Test that global plugins apply unless overridden by specific ones."""
        config = {
            "plugins": {
                "security": {
                    "_global": [
                        {
                            "handler": "global_security",
                            "config": {"policy_name": "global_security"},
                        }
                    ],
                    "github": [
                        {
                            "handler": "github_security",
                            "config": {"policy_name": "github_security"},
                        }
                    ],
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "global_audit",
                            "config": {"policy_name": "global_audit"},
                        }
                    ],
                    "file-system": [
                        {
                            "handler": "file_audit",
                            "config": {"policy_name": "file_audit"},
                        }
                    ],
                },
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "global_security": MockSecurityPlugin,
                "github_security": MockSecurityPlugin,
                "global_audit": MockAuditingPlugin,
                "file_audit": MockAuditingPlugin,
            }

            plugin_manager = PluginManager(config["plugins"])
            await plugin_manager.load_plugins()

            mock_config = Mock()
            mock_config.transport = "stdio"
            mock_config.plugins = None
            mock_config.upstreams = []

            mock_server_manager = Mock()

            proxy = MCPProxy(
                mock_config,
                plugin_manager=plugin_manager,
                server_manager=mock_server_manager,
            )
            proxy.transport = AsyncMock()
            proxy._is_running = True

            with patch.object(proxy, "_route_request") as mock_route_request:
                mock_route_request.return_value = MCPResponse(
                    jsonrpc="2.0", id="test", result={}
                )

                # Request for github: should use github_security and global_audit
                github_request = MCPRequest(
                    jsonrpc="2.0",
                    id="gh",
                    method="tools/call",
                    params={"name": "github__clone"},
                )
                await proxy.handle_request(github_request)

                # Request for file-system: should use global_security and file_audit
                file_request = MCPRequest(
                    jsonrpc="2.0",
                    id="fs",
                    method="tools/call",
                    params={"name": "file-system__read"},
                )
                await proxy.handle_request(file_request)

                # Request for unknown: should use global_security and global_audit
                unknown_request = MCPRequest(
                    jsonrpc="2.0",
                    id="un",
                    method="tools/call",
                    params={"name": "unknown__op"},
                )
                await proxy.handle_request(unknown_request)

                # Get plugin instances for direct assertion
                # For github upstream: [global_security, github_security] (index 0 and 1)
                github_plugins = plugin_manager.get_plugins_for_upstream("github")
                github_global_security_plugin = github_plugins["security"][
                    0
                ]  # global_security
                github_specific_security_plugin = github_plugins["security"][
                    1
                ]  # github_security
                github_global_audit_plugin = github_plugins["auditing"][
                    0
                ]  # global_audit

                # For file-system upstream: [global_security] and [global_audit, file_audit]
                fs_plugins = plugin_manager.get_plugins_for_upstream("file-system")
                fs_global_security_plugin = fs_plugins["security"][0]  # global_security
                fs_global_audit_plugin = fs_plugins["auditing"][0]  # global_audit
                fs_specific_audit_plugin = fs_plugins["auditing"][1]  # file_audit

                # For unknown upstream: [global_security] and [global_audit]
                unknown_plugins = plugin_manager.get_plugins_for_upstream("unknown")
                unknown_global_security_plugin = unknown_plugins["security"][
                    0
                ]  # global_security
                unknown_global_audit_plugin = unknown_plugins["auditing"][
                    0
                ]  # global_audit

                # Verify all instances are the same global_security plugin
                assert github_global_security_plugin is fs_global_security_plugin
                assert fs_global_security_plugin is unknown_global_security_plugin

                # Assert Security Plugin Calls
                # Global security plugin should be called for all 3 requests (github, file-system, unknown)
                assert len(github_global_security_plugin.called_requests) == 3
                request_ids = [
                    req.id for req in github_global_security_plugin.called_requests
                ]
                assert "gh" in request_ids
                assert "fs" in request_ids
                assert "un" in request_ids

                # GitHub-specific security plugin should only be called for github request
                assert len(github_specific_security_plugin.called_requests) == 1
                assert github_specific_security_plugin.called_requests[0].id == "gh"

                # Verify global audit instances are the same
                assert github_global_audit_plugin is fs_global_audit_plugin
                assert fs_global_audit_plugin is unknown_global_audit_plugin

                # Assert Auditing Plugin Calls
                # Global audit plugin should be called for all 3 requests (github, unknown, and file-system)
                # File-system has both global and specific audit plugins (different policy names)
                assert len(github_global_audit_plugin.logged_requests) == 3
                audit_server_names = [
                    req["server_name"]
                    for req in github_global_audit_plugin.logged_requests
                ]
                assert "github" in audit_server_names
                assert "unknown" in audit_server_names
                assert "file-system" in audit_server_names

                # File-system specific audit plugin should be called for file-system request
                assert len(fs_specific_audit_plugin.logged_requests) == 1
                assert (
                    fs_specific_audit_plugin.logged_requests[0]["server_name"]
                    == "file-system"
                )


# Additional test classes can be added here when needed
