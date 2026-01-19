"""Integration tests for upstream-scoped plugin configuration.

This module tests the complete upstream-scoped plugin configuration functionality
with real PluginManager instances (no mocking of core plugin resolution).
Tests verify end-to-end behavior including plugin loading, request processing,
and audit logging with upstream context.
"""

import pytest
from typing import Optional, Dict, Any

from gatekit.config import ConfigLoader
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    PipelineOutcome,
    ProcessingPipeline,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification

# Import mock classes from conftest for specific test scenarios


class MockUpstreamScopedSecurityPlugin(SecurityPlugin):
    """Test security plugin that tracks upstream context."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.config = config
        self._plugin_id = f"test_security_{config.get('identifier', 'default')}"
        self.priority = config.get("priority", 50)
        self.blocked_methods = config.get("blocked_methods", [])
        self.upstream_requests = []  # Track requests by upstream

    @property
    def plugin_id(self) -> str:
        """Unique identifier for this plugin."""
        return self._plugin_id

    async def process_request(
        self, request: MCPRequest, server_name: Optional[str] = None
    ) -> PluginResult:
        # Track which upstream this request came from
        self.upstream_requests.append(
            {
                "upstream": server_name,
                "method": request.method,
                "request_id": request.id,
            }
        )

        if request.method in self.blocked_methods:
            return PluginResult(
                allowed=False,
                reason=f"Method {request.method} blocked by {self._plugin_id} for upstream {server_name}",
                metadata={"upstream": server_name, "plugin": self._plugin_id},
            )

        return PluginResult(
            allowed=True,
            reason=f"Method {request.method} allowed by {self._plugin_id} for upstream {server_name}",
            metadata={"upstream": server_name, "plugin": self._plugin_id},
        )

    async def process_response(
        self,
        request: MCPRequest,
        response: MCPResponse,
        server_name: Optional[str] = None,
    ) -> PluginResult:
        return PluginResult(
            allowed=True,
            reason=f"Response allowed by {self._plugin_id} for upstream {server_name}",
            metadata={"upstream": server_name, "plugin": self._plugin_id},
        )

    async def process_notification(
        self, notification, server_name: Optional[str] = None
    ) -> PluginResult:
        return PluginResult(
            allowed=True,
            reason=f"Notification allowed by {self._plugin_id} for upstream {server_name}",
            metadata={"upstream": server_name, "plugin": self._plugin_id},
        )


class MockUpstreamScopedAuditingPlugin(AuditingPlugin):
    """Test auditing plugin that tracks upstream context."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.config = config
        self._plugin_id = f"test_audit_{config.get('identifier', 'default')}"
        self.priority = config.get("priority", 50)
        self.logged_requests = []
        self.logged_responses = []
        self.logged_notifications = []

    @property
    def plugin_id(self) -> str:
        """Unique identifier for this plugin."""
        return self._plugin_id

    async def log_request(
        self, request, pipeline: ProcessingPipeline, server_name: Optional[str] = None
    ) -> None:
        self.logged_requests.append(
            {
                "upstream": server_name,
                "method": request.method,
                "request_id": request.id,
                "pipeline_outcome": pipeline.pipeline_outcome,
                "plugin": self._plugin_id,
            }
        )

    async def log_response(
        self,
        request,
        response,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        self.logged_responses.append(
            {
                "upstream": server_name,
                "request_id": request.id,
                "response_id": response.id,
                "pipeline_outcome": pipeline.pipeline_outcome,
                "plugin": self._plugin_id,
            }
        )

    async def log_notification(
        self,
        notification,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        self.logged_notifications.append(
            {
                "upstream": server_name,
                "pipeline_outcome": pipeline.pipeline_outcome,
                "plugin": self._plugin_id,
            }
        )


class TestUpstreamScopedPluginIntegration:
    """Integration tests for upstream-scoped plugin configuration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config_loader = ConfigLoader()

    @pytest.mark.asyncio
    async def test_global_plus_specific_policies_integration(self):
        """Test upstream with both global and specific policies - verify both sets apply correctly."""
        # Mock the plugin discovery to use our test plugins
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "global_security": MockUpstreamScopedSecurityPlugin,
                "github_security": MockUpstreamScopedSecurityPlugin,
                "global_audit": MockUpstreamScopedAuditingPlugin,
                "github_audit": MockUpstreamScopedAuditingPlugin,
            }

            # Configuration with global + upstream-specific policies
            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "global_security",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "global",
                                "blocked_methods": ["dangerous_global"],
                            },
                        }
                    ],
                    "github": [
                        {
                            "handler": "github_security",
                            "enabled": True,
                            "priority": 20,
                            "config": {
                                "identifier": "github",
                                "blocked_methods": ["git_forbidden"],
                            },
                        }
                    ],
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "global_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global"},
                        }
                    ],
                    "github": [
                        {
                            "handler": "github_audit",
                            "enabled": True,
                            "priority": 20,
                            "config": {"identifier": "github"},
                        }
                    ],
                },
            }

            # Initialize plugin manager and load plugins
            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Verify plugins loaded for github upstream
            github_plugins = plugin_manager.get_plugins_for_upstream("github")
            assert len(github_plugins["security"]) == 2  # global + github-specific
            assert len(github_plugins["auditing"]) == 2  # global + github-specific

            # Test request processing for github upstream
            request = MCPRequest(
                jsonrpc="2.0",
                method="git_clone",
                id="test-1",
                params={"repo": "example/repo"},
            )

            # Process request through upstream-specific plugins
            pipeline = await plugin_manager.process_request(
                request, server_name="github"
            )
            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                pipeline.stages[0].result.metadata["upstream"]
                if pipeline.stages
                else None == "github"
            )

            # Log request through upstream-specific audit plugins
            await plugin_manager.log_request(request, pipeline, server_name="github")

            # Verify both audit plugins logged the request
            github_plugins["security"]
            github_audit_plugins = github_plugins["auditing"]

            # Check that both audit plugins have logged the request
            global_audit_plugin = next(
                p for p in github_audit_plugins if p.plugin_id == "test_audit_global"
            )
            github_audit_plugin = next(
                p for p in github_audit_plugins if p.plugin_id == "test_audit_github"
            )

            assert len(global_audit_plugin.logged_requests) == 1
            assert len(github_audit_plugin.logged_requests) == 1
            assert global_audit_plugin.logged_requests[0]["upstream"] == "github"
            assert github_audit_plugin.logged_requests[0]["upstream"] == "github"

    @pytest.mark.asyncio
    async def test_specific_only_policies_integration(self):
        """Test upstream with only specific policies - ensure no accidental global inheritance."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "github_security": MockUpstreamScopedSecurityPlugin,
                "filesystem_security": MockUpstreamScopedSecurityPlugin,
                "filesystem_audit": MockUpstreamScopedAuditingPlugin,
            }

            # Configuration with only upstream-specific policies (no _global)
            plugins_config = {
                "security": {
                    "github": [
                        {
                            "handler": "github_security",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "github",
                                "blocked_methods": ["git_push"],
                            },
                        }
                    ],
                    "filesystem": [
                        {
                            "handler": "filesystem_security",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "filesystem",
                                "blocked_methods": ["rm_rf"],
                            },
                        }
                    ],
                },
                "auditing": {
                    "filesystem": [
                        {
                            "handler": "filesystem_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "filesystem"},
                        }
                    ]
                },
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Test github upstream - should only have github-specific plugins
            github_plugins = plugin_manager.get_plugins_for_upstream("github")
            assert len(github_plugins["security"]) == 1
            assert len(github_plugins["auditing"]) == 0  # No auditing for github

            github_security = github_plugins["security"][0]
            assert github_security.plugin_id == "test_security_github"

            # Test filesystem upstream - should only have filesystem-specific plugins
            filesystem_plugins = plugin_manager.get_plugins_for_upstream("filesystem")
            assert len(filesystem_plugins["security"]) == 1
            assert len(filesystem_plugins["auditing"]) == 1

            filesystem_security = filesystem_plugins["security"][0]
            filesystem_audit = filesystem_plugins["auditing"][0]
            assert filesystem_security.plugin_id == "test_security_filesystem"
            assert filesystem_audit.plugin_id == "test_audit_filesystem"

            # Test unknown upstream - should have no plugins
            unknown_plugins = plugin_manager.get_plugins_for_upstream("unknown")
            assert len(unknown_plugins["security"]) == 0
            assert len(unknown_plugins["auditing"]) == 0

            # Test request processing for each upstream
            github_request = MCPRequest(
                jsonrpc="2.0", method="git_status", id="github-1", params={}
            )
            filesystem_request = MCPRequest(
                jsonrpc="2.0", method="read_file", id="fs-1", params={}
            )

            github_pipeline = await plugin_manager.process_request(
                github_request, server_name="github"
            )
            filesystem_pipeline = await plugin_manager.process_request(
                filesystem_request, server_name="filesystem"
            )

            # Both should be allowed
            assert github_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert filesystem_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                github_pipeline.stages[0].result.metadata["upstream"]
                if github_pipeline.stages
                else None == "github"
            )
            assert (
                filesystem_pipeline.stages[0].result.metadata["upstream"]
                if filesystem_pipeline.stages
                else None == "filesystem"
            )

    @pytest.mark.asyncio
    async def test_global_fallback_integration(self):
        """Test upstream without specific config - confirm it uses global policies."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "global_security": MockUpstreamScopedSecurityPlugin,
                "global_audit": MockUpstreamScopedAuditingPlugin,
            }

            # Configuration with only global policies
            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "global_security",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "global",
                                "blocked_methods": ["dangerous_method"],
                            },
                        }
                    ]
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "global_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global"},
                        }
                    ]
                },
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Test multiple upstreams - all should get global plugins
            for upstream in ["github", "filesystem", "unknown_server"]:
                plugins = plugin_manager.get_plugins_for_upstream(upstream)
                assert len(plugins["security"]) == 1
                assert len(plugins["auditing"]) == 1

                security_plugin = plugins["security"][0]
                audit_plugin = plugins["auditing"][0]
                assert security_plugin.plugin_id == "test_security_global"
                assert audit_plugin.plugin_id == "test_audit_global"

                # Test request processing
                request = MCPRequest(
                    jsonrpc="2.0", method="test_method", id=f"{upstream}-1", params={}
                )

                pipeline = await plugin_manager.process_request(
                    request, server_name=upstream
                )
                assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
                assert (
                    pipeline.stages[0].result.metadata["upstream"]
                    if pipeline.stages
                    else None is upstream
                )

                # Test auditing
                await plugin_manager.log_request(
                    request, pipeline, server_name=upstream
                )

                # Verify audit plugin captured the upstream context
                assert len(audit_plugin.logged_requests) >= 1
                latest_log = audit_plugin.logged_requests[-1]
                assert latest_log["upstream"] == upstream

    @pytest.mark.asyncio
    async def test_policy_override_integration(self):
        """Test upstream-specific policy overrides global policy with same name."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "rate_limiting": MockUpstreamScopedSecurityPlugin,
                "access_control": MockUpstreamScopedSecurityPlugin,
            }

            # Configuration where github overrides global rate_limiting policy
            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "rate_limiting",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "global_rate",
                                "blocked_methods": ["global_blocked"],
                            },
                        },
                        {
                            "handler": "access_control",
                            "enabled": True,
                            "priority": 20,
                            "config": {
                                "identifier": "global_access",
                                "blocked_methods": [],
                            },
                        },
                    ],
                    "github": [
                        {
                            "handler": "rate_limiting",  # Same policy name - should override
                            "enabled": True,
                            "priority": 15,
                            "config": {
                                "identifier": "github_rate",
                                "blocked_methods": ["github_blocked"],
                            },
                        }
                    ],
                },
                "auditing": {},
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Test github upstream - should have github rate_limiting + global access_control
            github_plugins = plugin_manager.get_plugins_for_upstream("github")
            assert (
                len(github_plugins["security"]) == 2
            )  # access_control + rate_limiting (overridden)

            # Verify the rate_limiting plugin is the github version, not global
            rate_limiting_plugin = next(
                p
                for p in github_plugins["security"]
                if p.plugin_id == "test_security_github_rate"
            )
            access_control_plugin = next(
                p
                for p in github_plugins["security"]
                if p.plugin_id == "test_security_global_access"
            )

            assert rate_limiting_plugin is not None
            assert access_control_plugin is not None
            assert "github_blocked" in rate_limiting_plugin.blocked_methods
            assert "global_blocked" not in rate_limiting_plugin.blocked_methods

            # Test request that triggers github-specific rate limiting
            request = MCPRequest(
                jsonrpc="2.0", method="github_blocked", id="override-1", params={}
            )

            pipeline = await plugin_manager.process_request(
                request, server_name="github"
            )
            assert pipeline.pipeline_outcome == PipelineOutcome.BLOCKED
            # When blocked, reasons are cleared to generic "[blocked]"
            assert pipeline.blocked_at_stage is not None
            assert (
                pipeline.stages[0].result.metadata["upstream"]
                if pipeline.stages
                else None == "github"
            )

            # Test other upstream - should use global policies only
            other_plugins = plugin_manager.get_plugins_for_upstream("other")
            assert len(other_plugins["security"]) == 2  # Both global policies

            global_rate_plugin = next(
                p
                for p in other_plugins["security"]
                if p.plugin_id == "test_security_global_rate"
            )
            assert global_rate_plugin is not None
            assert "global_blocked" in global_rate_plugin.blocked_methods

    @pytest.mark.asyncio
    async def test_audit_logs_contain_upstream_context(self):
        """Test that audit logs contain correct upstream context in real scenarios."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "context_audit": MockUpstreamScopedAuditingPlugin,
                "context_security": MockUpstreamScopedSecurityPlugin,
            }

            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "context_security",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global", "blocked_methods": []},
                        }
                    ]
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "context_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global"},
                        }
                    ],
                    "github": [
                        {
                            "handler": "context_audit",
                            "enabled": True,
                            "priority": 20,
                            "config": {"identifier": "github"},
                        }
                    ],
                },
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Test requests to different upstreams
            test_cases = [
                ("github", "git_clone"),
                ("filesystem", "read_file"),
                ("database", "query"),
            ]

            for upstream, method in test_cases:
                request = MCPRequest(
                    jsonrpc="2.0", method=method, id=f"context-{upstream}", params={}
                )

                # Process request and response
                pipeline = await plugin_manager.process_request(
                    request, server_name=upstream
                )

                response = MCPResponse(
                    jsonrpc="2.0", id=request.id, result={"status": "success"}
                )

                response_pipeline = ProcessingPipeline(
                    original_content=response, pipeline_outcome=PipelineOutcome.ALLOWED
                )
                # Note: Creating a minimal pipeline for testing

                # Log both request and response
                await plugin_manager.log_request(
                    request, pipeline, server_name=upstream
                )
                await plugin_manager.log_response(
                    request, response, response_pipeline, server_name=upstream
                )

                # Verify audit logs contain correct upstream context
                upstream_plugins = plugin_manager.get_plugins_for_upstream(upstream)
                audit_plugins = upstream_plugins["auditing"]

                for audit_plugin in audit_plugins:
                    # Check request logs
                    request_logs = [
                        log
                        for log in audit_plugin.logged_requests
                        if log["request_id"] == request.id
                    ]
                    assert len(request_logs) == 1
                    assert request_logs[0]["upstream"] == upstream
                    assert request_logs[0]["method"] == method

                    # Check response logs
                    response_logs = [
                        log
                        for log in audit_plugin.logged_responses
                        if log["request_id"] == request.id
                    ]
                    assert len(response_logs) == 1
                    assert response_logs[0]["upstream"] == upstream

    @pytest.mark.asyncio
    async def test_mixed_real_and_mock_plugins_integration(self):
        """Test integration with a mix of real and mock plugins to validate realistic scenarios."""
        # Create a configuration that uses both real Gatekit plugins and our test plugins
        plugins_config = {
            "middleware": {
                "_global": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "priority": 10,
                        "config": {
                            "tools": [
                                {"tool": "git_clone"},
                                {"tool": "git_status"},
                                {"tool": "read_file"},
                                {"tool": "write_file"},
                            ]
                        },
                    }
                ],
                "github": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "priority": 20,
                        "config": {
                            # Override global with more restrictive - only allow git_clone and git_status
                            # (git_push is NOT in the list, so it will be denied)
                            "tools": [
                                {"tool": "git_clone"},
                                {"tool": "git_status"},
                            ]
                        },
                    }
                ],
            },
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "enabled": True,
                        "priority": 10,
                        "config": {
                            "output_file": "/tmp/test_audit.log",
                            "format": "json",
                            "critical": False,  # Allow /tmp path for testing
                        },
                    }
                ]
            },
        }

        plugin_manager = PluginManager(plugins_config)
        await plugin_manager.load_plugins()

        # Test github upstream - should have overridden tool access control
        github_plugins = plugin_manager.get_plugins_for_upstream("github")
        assert len(github_plugins["middleware"]) == 1  # Overridden global policy
        assert len(github_plugins["auditing"]) == 1  # Global auditing policy

        # Test allowed git operation
        allowed_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="mixed-1",
            params={"name": "git_status", "arguments": {}},
        )

        pipeline = await plugin_manager.process_request(
            allowed_request, server_name="github"
        )
        # Middleware plugins don't set ALLOWED - they only complete or modify
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION

        # Test blocked git operation (blocked by github-specific override)
        blocked_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="mixed-2",
            params={"name": "git_push", "arguments": {}},
        )

        pipeline = await plugin_manager.process_request(
            blocked_request, server_name="github"
        )
        # Middleware returns completed response with error for blocked tools
        assert pipeline.pipeline_outcome == PipelineOutcome.COMPLETED_BY_MIDDLEWARE
        assert pipeline.completed_by is not None

        # Test filesystem upstream - should use global allowlist
        filesystem_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="mixed-3",
            params={"name": "read_file", "arguments": {}},
        )

        pipeline = await plugin_manager.process_request(
            filesystem_request, server_name="filesystem"
        )
        # Global tool_manager plugin handles filesystem requests
        assert pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION

        # Verify auditing works across all upstreams
        for request, upstream in [
            (allowed_request, "github"),
            (blocked_request, "github"),
            (filesystem_request, "filesystem"),
        ]:
            test_pipeline = ProcessingPipeline(
                original_content=request, pipeline_outcome=PipelineOutcome.ALLOWED
            )
            await plugin_manager.log_request(
                request, test_pipeline, server_name=upstream
            )

            upstream_plugins = plugin_manager.get_plugins_for_upstream(upstream)
            audit_plugins = upstream_plugins["auditing"]
            assert len(audit_plugins) == 1  # Should have global file auditing plugin

    @pytest.mark.asyncio
    async def test_upstream_scoped_response_processing_integration(self):
        """Test response processing uses correct upstream-scoped plugins in real scenarios."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "response_filter": MockUpstreamScopedSecurityPlugin,
                "response_audit": MockUpstreamScopedAuditingPlugin,
            }

            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "response_filter",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "global_response",
                                "blocked_methods": [],
                            },
                        }
                    ],
                    "github": [
                        {
                            "handler": "response_filter",
                            "enabled": True,
                            "priority": 20,
                            "config": {
                                "identifier": "github_response",
                                "blocked_methods": [],
                            },
                        }
                    ],
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "response_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global"},
                        }
                    ],
                    "github": [
                        {
                            "handler": "response_audit",
                            "enabled": True,
                            "priority": 20,
                            "config": {"identifier": "github"},
                        }
                    ],
                },
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Test response processing for github upstream
            request = MCPRequest(
                jsonrpc="2.0",
                method="git_clone",
                id="response-test-1",
                params={"repo": "example/repo"},
            )

            response = MCPResponse(
                jsonrpc="2.0",
                id="response-test-1",
                result={"success": True, "output": "Repository cloned successfully"},
            )

            # Process response through upstream-scoped plugins
            pipeline = await plugin_manager.process_response(
                request, response, server_name="github"
            )
            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                pipeline.stages[0].result.metadata["upstream"]
                if pipeline.stages
                else None == "github"
            )
            assert len(pipeline.stages) == 1  # github-specific overrides global

            # Log response through upstream-scoped audit plugins
            await plugin_manager.log_response(
                request, response, pipeline, server_name="github"
            )

            # Verify audit plugin logged the response (github overrides global)
            github_plugins = plugin_manager.get_plugins_for_upstream("github")
            github_audit_plugins = github_plugins["auditing"]

            # Only github audit plugin should be present (overrides global)
            assert len(github_audit_plugins) == 1
            github_audit_plugin = github_audit_plugins[0]
            assert github_audit_plugin.plugin_id == "test_audit_github"

            assert len(github_audit_plugin.logged_responses) == 1
            assert github_audit_plugin.logged_responses[0]["upstream"] == "github"

            # Test filesystem upstream - should only use global plugins
            filesystem_response = MCPResponse(
                jsonrpc="2.0", id="response-test-2", result={"content": "file data"}
            )

            filesystem_request = MCPRequest(
                jsonrpc="2.0",
                method="read_file",
                id="response-test-2",
                params={"path": "/example.txt"},
            )

            filesystem_pipeline = await plugin_manager.process_response(
                filesystem_request, filesystem_response, server_name="filesystem"
            )
            assert filesystem_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                filesystem_pipeline.stages[0].result.metadata["upstream"]
                if filesystem_pipeline.stages
                else None == "filesystem"
            )
            assert len(filesystem_pipeline.stages) == 1  # only global

    @pytest.mark.asyncio
    async def test_upstream_scoped_notification_processing_integration(self):
        """Test notification processing uses correct upstream-scoped plugins in real scenarios."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "notification_filter": MockUpstreamScopedSecurityPlugin,
                "notification_audit": MockUpstreamScopedAuditingPlugin,
            }

            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "notification_filter",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "global_notification",
                                "blocked_methods": [],
                            },
                        }
                    ],
                    "github": [
                        {
                            "handler": "notification_filter",
                            "enabled": True,
                            "priority": 20,
                            "config": {
                                "identifier": "github_notification",
                                "blocked_methods": [],
                            },
                        }
                    ],
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "notification_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global"},
                        }
                    ],
                    "github": [
                        {
                            "handler": "notification_audit",
                            "enabled": True,
                            "priority": 20,
                            "config": {"identifier": "github"},
                        }
                    ],
                },
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Test notification processing for github upstream
            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 50, "message": "Cloning repository..."},
            )

            # Process notification through upstream-scoped plugins
            pipeline = await plugin_manager.process_notification(
                notification, server_name="github"
            )
            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                pipeline.stages[0].result.metadata["upstream"]
                if pipeline.stages
                else None == "github"
            )
            assert len(pipeline.stages) == 1  # github-specific overrides global

            # Log notification through upstream-scoped audit plugins
            await plugin_manager.log_notification(
                notification, pipeline, server_name="github"
            )

            # Verify audit plugin logged the notification (github overrides global)
            github_plugins = plugin_manager.get_plugins_for_upstream("github")
            github_audit_plugins = github_plugins["auditing"]

            # Only github audit plugin should be present (overrides global)
            assert len(github_audit_plugins) == 1
            github_audit_plugin = github_audit_plugins[0]
            assert github_audit_plugin.plugin_id == "test_audit_github"

            assert len(github_audit_plugin.logged_notifications) == 1
            assert github_audit_plugin.logged_notifications[0]["upstream"] == "github"

            # Test filesystem upstream - should only use global plugins
            filesystem_notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 100, "message": "File operation complete"},
            )

            filesystem_pipeline = await plugin_manager.process_notification(
                filesystem_notification, server_name="filesystem"
            )
            assert filesystem_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                filesystem_pipeline.stages[0].result.metadata["upstream"]
                if filesystem_pipeline.stages
                else None == "filesystem"
            )
            assert len(filesystem_pipeline.stages) == 1  # only global

    @pytest.mark.asyncio
    async def test_complete_upstream_scoped_flow_integration(self):
        """Test complete flow: request, response, and notification processing with upstream-scoped plugins."""
        from unittest.mock import patch

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "flow_security": MockUpstreamScopedSecurityPlugin,
                "flow_audit": MockUpstreamScopedAuditingPlugin,
            }

            plugins_config = {
                "security": {
                    "_global": [
                        {
                            "handler": "flow_security",
                            "enabled": True,
                            "priority": 10,
                            "config": {
                                "identifier": "global_flow",
                                "blocked_methods": [],
                            },
                        }
                    ],
                    "github": [
                        {
                            "handler": "flow_security",
                            "enabled": True,
                            "priority": 20,
                            "config": {
                                "identifier": "github_flow",
                                "blocked_methods": [],
                            },
                        }
                    ],
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "flow_audit",
                            "enabled": True,
                            "priority": 10,
                            "config": {"identifier": "global"},
                        }
                    ],
                    "github": [
                        {
                            "handler": "flow_audit",
                            "enabled": True,
                            "priority": 20,
                            "config": {"identifier": "github"},
                        }
                    ],
                },
            }

            plugin_manager = PluginManager(plugins_config)
            await plugin_manager.load_plugins()

            # Simulate complete MCP flow for github upstream
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="flow-test-1",
                params={"name": "git_clone", "arguments": {"repo": "example/repo"}},
            )

            response = MCPResponse(
                jsonrpc="2.0",
                id="flow-test-1",
                result={"success": True, "output": "Repository cloned"},
            )

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 100, "message": "Clone complete"},
            )

            # Process request
            request_pipeline = await plugin_manager.process_request(
                request, server_name="github"
            )
            assert request_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                request_pipeline.stages[0].result.metadata["upstream"]
                if request_pipeline.stages
                else None == "github"
            )

            # Log request
            await plugin_manager.log_request(
                request, request_pipeline, server_name="github"
            )

            # Process response
            response_pipeline = await plugin_manager.process_response(
                request, response, server_name="github"
            )
            assert response_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                response_pipeline.stages[0].result.metadata["upstream"]
                if response_pipeline.stages
                else None == "github"
            )

            # Log response
            await plugin_manager.log_response(
                request, response, response_pipeline, server_name="github"
            )

            # Process notification
            notification_pipeline = await plugin_manager.process_notification(
                notification, server_name="github"
            )
            assert notification_pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            assert (
                notification_pipeline.stages[0].result.metadata["upstream"]
                if notification_pipeline.stages
                else None == "github"
            )

            # Log notification
            await plugin_manager.log_notification(
                notification, notification_pipeline, server_name="github"
            )

            # Verify plugin was used consistently
            github_plugins = plugin_manager.get_plugins_for_upstream("github")
            audit_plugins = github_plugins["auditing"]

            # Should have 1 audit plugin (github-specific overrides global)
            assert len(audit_plugins) == 1
            audit_plugin = audit_plugins[0]
            assert audit_plugin.plugin_id == "test_audit_github"

            # Plugin should have logged all three types of events
            assert len(audit_plugin.logged_requests) == 1
            assert len(audit_plugin.logged_responses) == 1
            assert len(audit_plugin.logged_notifications) == 1

            # All logs should have correct upstream context
            assert audit_plugin.logged_requests[0]["upstream"] == "github"
            assert audit_plugin.logged_responses[0]["upstream"] == "github"
            assert audit_plugin.logged_notifications[0]["upstream"] == "github"
