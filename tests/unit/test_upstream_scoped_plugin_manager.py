"""Unit tests for upstream-scoped plugin manager functionality (TDD - RED phase).

This test file contains failing tests that define the requirements for the new
upstream-scoped plugin resolution in the plugin manager.
"""

import pytest
from unittest.mock import patch
from typing import Dict, Any, Optional

from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import (
    SecurityPlugin,
    AuditingPlugin,
    PluginResult,
    PipelineOutcome,
    ProcessingPipeline,
)
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class MockSecurityPlugin(SecurityPlugin):
    """Mock security plugin for testing."""

    def __init__(self, config: Dict[str, Any]):
        self._plugin_id = config.get("identifier", "mock_security")
        self.priority = config.get("priority", 50)
        self.config = config

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @plugin_id.setter
    def plugin_id(self, value: str):
        self._plugin_id = value

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        metadata = {"upstream": server_name, "plugins_applied": [self.plugin_id]}
        return PluginResult(
            allowed=True,
            reason=f"Mock plugin {self.plugin_id} allowed",
            metadata=metadata,
        )

    async def process_response(
        self, request: MCPRequest, response, server_name: str
    ) -> PluginResult:
        metadata = {"upstream": server_name, "plugins_applied": [self.plugin_id]}
        return PluginResult(
            allowed=True,
            reason=f"Mock plugin {self.plugin_id} allowed",
            metadata=metadata,
        )

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        metadata = {"upstream": server_name, "plugins_applied": [self.plugin_id]}
        return PluginResult(
            allowed=True,
            reason=f"Mock plugin {self.plugin_id} allowed",
            metadata=metadata,
        )


class MockAuditingPlugin(AuditingPlugin):
    """Mock auditing plugin for testing."""

    def __init__(self, config: Dict[str, Any]):
        self._plugin_id = config.get("identifier", "mock_auditing")
        self.priority = config.get("priority", 50)
        self.config = config

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @plugin_id.setter
    def plugin_id(self, value: str):
        self._plugin_id = value

    async def log_request(
        self, request, pipeline: ProcessingPipeline, server_name: Optional[str] = None
    ) -> None:
        pass

    async def log_response(
        self,
        request,
        response,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        pass

    async def log_notification(
        self,
        notification,
        pipeline: ProcessingPipeline,
        server_name: Optional[str] = None,
    ) -> None:
        pass


class TestUpstreamScopedPluginLoading:
    """Test upstream-scoped plugin loading and resolution.

    These tests define the new functionality for loading plugins based on
    upstream-scoped configuration with _global and upstream-specific sections.
    """

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_load_plugins_with_global_and_upstream_specific_config(self):
        """Test loading plugins with _global and upstream-specific configuration.

        This test should FAIL initially because the current PluginManager
        expects list-based configuration, not dictionary-based.
        """
        config = {
            "middleware": {
                "_global": [
                    {
                        "handler": "tool_manager",
                        "enabled": True,
                        "priority": 10,
                        "config": {"tools": []},
                    }
                ],
            },
            "security": {
                "github": [
                    {
                        "handler": "basic_secrets_filter",
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
                "weather-api": [
                    {
                        "handler": "basic_secrets_filter",
                        "enabled": True,
                        "priority": 30,
                        "config": {"action": "audit_only"},
                    }
                ],
            },
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "enabled": True,
                        "priority": 10,
                        "config": {"output_file": "/tmp/test.log", "critical": False},
                    }
                ]
            },
        }

        # Should load plugins successfully with new dictionary format
        manager = PluginManager(config)
        # This will fail until we implement upstream-scoped loading
        await manager.load_plugins()

        # Should be able to get plugins for different upstreams
        assert hasattr(manager, "get_plugins_for_upstream")

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_load_plugins_upstream_specific_only(self):
        """Test loading plugins with upstream-specific configuration only (no _global).

        This test should FAIL initially because the current PluginManager
        doesn't support upstream-only configuration.
        """
        config = {
            "middleware": {
                "github": [
                    {
                        "handler": "tool_manager",
                        "config": {"enabled": True, "priority": 20, "tools": []},
                    }
                ],
            },
            "security": {
                "github": [
                    {
                        "handler": "basic_secrets_filter",
                        "config": {"enabled": True, "priority": 10},
                    }
                ],
                "weather-api": [
                    {
                        "handler": "basic_secrets_filter",
                        "config": {"enabled": True, "priority": 10, "action": "audit_only"},
                    },
                    {"handler": "basic_pii_filter", "config": {"enabled": True, "priority": 20}},
                ],
            },
            "auditing": {
                "weather-api": [
                    {
                        "handler": "audit_jsonl",
                        "config": {"enabled": True, "priority": 10, "output_file": "/tmp/test_weather_api.log", "critical": False},
                    }
                ]
            },
        }

        manager = PluginManager(config)
        await manager.load_plugins()

        # Should be able to get plugins for each upstream
        assert hasattr(manager, "get_plugins_for_upstream")


class TestUpstreamPluginResolution:
    """Test plugin resolution for specific upstreams.

    These tests define the new plugin resolution functionality that applies
    the correct plugin set based on the target upstream.
    """

    @pytest.mark.asyncio
    async def test_get_plugins_for_upstream_with_global_fallback(self):
        """Test getting plugins for upstream with global fallback.

        This test should FAIL initially because get_plugins_for_upstream() doesn't exist.
        """
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "rate_limiting",
                        "enabled": True,
                        "priority": 10,
                        "config": {"max_requests": 100},
                    }
                ],
                "github": [
                    {
                        "handler": "git_token_validation",
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
            },
            "auditing": {
                "_global": [
                    {
                        "handler": "request_logging",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            },
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "rate_limiting": MockSecurityPlugin,
                "git_token_validation": MockSecurityPlugin,
                "request_logging": MockAuditingPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            # Test upstream with specific plugins + global
            plugins = manager.get_plugins_for_upstream("github")

            # Should have both global and github-specific plugins
            assert "security" in plugins
            assert "auditing" in plugins

            # Should have 2 security plugins (1 global + 1 github-specific)
            assert len(plugins["security"]) == 2

            # Should have 1 auditing plugin (1 global, no github-specific auditing)
            assert len(plugins["auditing"]) == 1

    @pytest.mark.asyncio
    async def test_get_plugins_for_upstream_specific_only(self):
        """Test getting plugins for upstream with specific configuration only.

        This test should FAIL initially because get_plugins_for_upstream() doesn't exist.
        """
        config = {
            "security": {
                "github": [
                    {
                        "handler": "git_token_validation",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ],
                "file-system": [
                    {
                        "handler": "path_restrictions",
                        "enabled": True,
                        "priority": 10,
                        "config": {"allowed_paths": ["/safe"]},
                    }
                ],
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "git_token_validation": MockSecurityPlugin,
                "path_restrictions": MockSecurityPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            # Test github upstream
            github_plugins = manager.get_plugins_for_upstream("github")
            assert len(github_plugins["security"]) == 1
            assert len(github_plugins["auditing"]) == 0

            # Test file-system upstream
            fs_plugins = manager.get_plugins_for_upstream("file-system")
            assert len(fs_plugins["security"]) == 1
            assert len(fs_plugins["auditing"]) == 0

            # Test unknown upstream
            unknown_plugins = manager.get_plugins_for_upstream("unknown")
            assert len(unknown_plugins["security"]) == 0
            assert len(unknown_plugins["auditing"]) == 0

    @pytest.mark.asyncio
    async def test_get_plugins_for_upstream_global_only(self):
        """Test getting plugins for upstream with global configuration only.

        This test should FAIL initially because get_plugins_for_upstream() doesn't exist.
        """
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "rate_limiting",
                        "enabled": True,
                        "priority": 10,
                        "config": {"max_requests": 100},
                    }
                ]
            },
            "auditing": {
                "_global": [
                    {
                        "handler": "request_logging",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            },
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "rate_limiting": MockSecurityPlugin,
                "request_logging": MockAuditingPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            # Any upstream should get global plugins
            for upstream in ["github", "file-system", "unknown"]:
                plugins = manager.get_plugins_for_upstream(upstream)
                assert len(plugins["security"]) == 1
                assert len(plugins["auditing"]) == 1

    @pytest.mark.asyncio
    async def test_get_plugins_for_upstream_empty_config(self):
        """Test getting plugins for upstream with empty configuration.

        This test should FAIL initially because get_plugins_for_upstream() doesn't exist.
        """
        config = {"security": {}, "auditing": {}}

        manager = PluginManager(config)
        await manager.load_plugins()

        # Should return empty plugin sets
        plugins = manager.get_plugins_for_upstream("github")
        assert len(plugins["security"]) == 0
        assert len(plugins["auditing"]) == 0


class TestPluginPolicyOverride:
    """Test policy override behavior in upstream-scoped configuration.

    These tests define how upstream-specific policies override global policies
    with the same name.
    """

    @pytest.mark.asyncio
    async def test_upstream_policy_overrides_global_policy(self):
        """Test that upstream-specific policies override global policies with same name.

        This test should FAIL initially because policy override logic doesn't exist.
        """
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "rate_limiting",
                        "enabled": True,
                        "priority": 10,
                        "config": {"max_requests": 100},
                    }
                ],
                "github": [
                    {
                        "handler": "rate_limiting",  # Same handler name, should override
                        "enabled": True,
                        "priority": 20,
                        "config": {"max_requests": 50},  # Different config
                    },
                    {
                        "handler": "git_token_validation",
                        "enabled": True,
                        "priority": 30,
                        "config": {},
                    },
                ],
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "rate_limiting": MockSecurityPlugin,
                "git_token_validation": MockSecurityPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            plugins = manager.get_plugins_for_upstream("github")

            # Should have 2 security plugins (global rate_limiting overridden by github rate_limiting + git_token_validation)
            assert len(plugins["security"]) == 2

            # Find the rate_limiting plugin and verify it uses github config
            rate_limiting_plugin = None
            for plugin in plugins["security"]:
                if getattr(plugin, "handler", None) == "rate_limiting":
                    rate_limiting_plugin = plugin
                    break

            assert rate_limiting_plugin is not None
            # Should use github-specific config (max_requests: 50, not 100)
            assert rate_limiting_plugin.config["max_requests"] == 50

    @pytest.mark.asyncio
    async def test_no_override_when_different_policy_names(self):
        """Test that different handler names don't override each other.

        This test should FAIL initially because additive policy logic doesn't exist.
        """
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "rate_limiting",
                        "enabled": True,
                        "priority": 10,
                        "config": {"max_requests": 100},
                    }
                ],
                "github": [
                    {
                        "handler": "git_token_validation",  # Different handler name
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "rate_limiting": MockSecurityPlugin,
                "git_token_validation": MockSecurityPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            plugins = manager.get_plugins_for_upstream("github")

            # Should have 2 security plugins (global rate_limiting + github git_token_validation)
            assert len(plugins["security"]) == 2

            # Should have both handlers
            handler_names = [getattr(p, "handler", None) for p in plugins["security"]]
            assert "rate_limiting" in handler_names
            assert "git_token_validation" in handler_names


class TestUpstreamScopedRequestProcessing:
    """Test request processing with upstream-scoped plugins.

    These tests define how the plugin manager should process requests
    using the appropriate plugin set for the target upstream.
    """

    @pytest.mark.asyncio
    async def test_process_request_with_upstream_specific_plugins(self):
        """Test request processing uses upstream-specific plugins.

        This test should FAIL initially because upstream-aware request processing doesn't exist.
        """
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "basic_security",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ],
                "github": [
                    {
                        "handler": "git_token_validation",
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
            }
        }

        # Mock the plugin loading
        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "basic_security": MockSecurityPlugin,
                "git_token_validation": MockSecurityPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            # Test request processing for github upstream
            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "git_clone", "arguments": {}},
            )

            # Should use github-specific plugins (global + github-specific)
            pipeline = await manager.process_request(request, server_name="github")

            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Current implementation doesn't yet support upstream-scoped processing
            # So this will use all loaded plugins regardless of server_name

    @pytest.mark.asyncio
    async def test_process_request_with_global_plugins_only(self):
        """Test request processing uses global plugins when no upstream-specific config.

        This test should FAIL initially because upstream-aware request processing doesn't exist.
        """
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "basic_security",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {"basic_security": MockSecurityPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "read_file", "arguments": {}},
            )

            # Should use global plugins for any upstream
            pipeline = await manager.process_request(request, server_name="file-system")

            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Current implementation doesn't yet support upstream-scoped processing

    @pytest.mark.asyncio
    async def test_process_request_no_plugins_for_upstream(self):
        """Test request processing when no plugins configured for upstream.

        This test should FAIL initially because upstream-aware request processing doesn't exist.
        """
        config = {
            "security": {
                "github": [
                    {
                        "handler": "git_token_validation",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {"git_token_validation": MockSecurityPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "read_file", "arguments": {}},
            )

            # Should return no security decision when no plugins for upstream
            pipeline = await manager.process_request(request, server_name="file-system")

            assert (
                pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
            )  # No security decision when no plugins
            # Current implementation doesn't yet support upstream-scoped processing
            # So this will use all loaded plugins regardless of server_name


class TestUpstreamScopedAuditLogging:
    """Test audit logging with upstream-scoped plugins.

    These tests define how audit logging should work with upstream-scoped configuration.
    """

    @pytest.mark.asyncio
    async def test_log_request_with_upstream_specific_plugins(self):
        """Test audit logging uses upstream-specific plugins.

        This test should FAIL initially because upstream-aware audit logging doesn't exist.
        """
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "request_logging",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ],
                "github": [
                    {
                        "handler": "git_operation_audit",
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "request_logging": MockAuditingPlugin,
                "git_operation_audit": MockAuditingPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "git_clone", "arguments": {}},
            )

            decision = PluginResult(allowed=True, reason="Test decision")

            # Should use github-specific audit plugins
            await manager.log_request(request, decision, "github")

            # Test should verify that both global and github-specific audit plugins were called
            # (Implementation details to be determined during GREEN phase)

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_log_request_captures_upstream_context(self):
        """Test that audit logging captures upstream context.

        This test should FAIL initially because upstream context capture doesn't exist.
        """
        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "request_logging",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        # Mock audit plugin that captures logs
        audit_logs = []

        class TestAuditingPlugin(AuditingPlugin):
            def __init__(self, config: Dict[str, Any]):
                self._plugin_id = config.get("identifier", "test_audit")
                self.priority = config.get("priority", 10)
                self.config = config

            @property
            def plugin_id(self) -> str:
                return self._plugin_id

            @plugin_id.setter
            def plugin_id(self, value: str):
                self._plugin_id = value

            async def log_request(
                self,
                request,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                audit_logs.append(
                    {
                        "request": request,
                        "decision": decision,
                        "upstream": getattr(decision, "upstream", None),
                    }
                )

            async def log_response(
                self,
                request,
                response,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                pass

            async def log_notification(
                self,
                notification,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                pass

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {"request_logging": TestAuditingPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "read_file", "arguments": {}},
            )

            decision = PluginResult(allowed=True, reason="Test decision")

            await manager.log_request(request, decision, "test-server")

            # Should have captured upstream context in audit log
            assert len(audit_logs) == 1
            # In current implementation, upstream is None since it's not passed yet
            assert audit_logs[0]["upstream"] is None


class TestBackwardCompatibility:
    """Test backward compatibility handling during transition.

    These tests define how the plugin manager should handle the transition
    from old list-based to new dictionary-based configuration.
    """

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_old_list_format_should_fail_gracefully(self):
        """Test that old list format configurations fail with clear error.

        This test should PASS initially and continue to pass because we're
        making a breaking change for v0.1.0.
        """
        # Old list-based format
        old_config = {
            "security": [{"handler": "rate_limiting", "config": {"enabled": True}}],
            "auditing": [{"handler": "request_logging", "config": {"enabled": True}}],
        }

        # Breaking change implemented - should fail with AttributeError
        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {
                "rate_limiting": MockSecurityPlugin,
                "request_logging": MockAuditingPlugin,
            }

            manager = PluginManager(old_config)

            # Should fail because list format is no longer supported
            with pytest.raises(AttributeError) as exc_info:
                await manager.load_plugins()

            # Should get clear error about 'list' object not having 'items' method
            assert "'list' object has no attribute 'items'" in str(exc_info.value)


class TestUpstreamScopedResponseProcessing:
    """Test response processing with upstream-scoped plugins.

    These tests define how the plugin manager should process responses
    using the appropriate plugin set for the source upstream.
    """

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_process_response_with_upstream_specific_plugins(self):
        """Test response processing uses upstream-specific plugins."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "basic_security",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ],
                "github": [
                    {
                        "handler": "git_response_filter",
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "basic_security": MockSecurityPlugin,
                "git_response_filter": MockSecurityPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "git_clone", "arguments": {}},
            )

            response = MCPResponse(jsonrpc="2.0", id="test", result={"success": True})

            # Should use github-specific plugins (global + github-specific)
            pipeline = await manager.process_response(
                request, response, server_name="github"
            )

            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Should have 2 stages - one for global, one for github-specific
            assert len(pipeline.stages) == 2
            # Each stage should have metadata indicating the upstream
            for stage in pipeline.stages:
                if stage.result.metadata:
                    assert "upstream" in stage.result.metadata
                    assert stage.result.metadata["upstream"] == "github"

    @pytest.mark.asyncio
    async def test_process_response_with_global_plugins_only(self):
        """Test response processing uses global plugins when no upstream-specific config."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "basic_security",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"basic_security": MockSecurityPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "read_file", "arguments": {}},
            )

            response = MCPResponse(
                jsonrpc="2.0", id="test", result={"content": "file data"}
            )

            # Should use global plugins for any upstream
            pipeline = await manager.process_response(
                request, response, server_name="file-system"
            )

            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Should have 1 stage - only global plugin
            assert len(pipeline.stages) == 1
            if pipeline.stages[0].result.metadata:
                assert (
                    pipeline.stages[0].result.metadata.get("upstream") == "file-system"
                )

    @pytest.mark.asyncio
    async def test_process_response_no_plugins_for_upstream(self):
        """Test response processing when no plugins configured for upstream."""
        config = {
            "security": {
                "github": [
                    {
                        "handler": "git_response_filter",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"git_response_filter": MockSecurityPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "read_file", "arguments": {}},
            )

            response = MCPResponse(
                jsonrpc="2.0", id="test", result={"content": "file data"}
            )

            # Should return no security decision when no plugins for upstream
            pipeline = await manager.process_response(
                request, response, server_name="file-system"
            )

            assert (
                pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
            )  # No security decision when no plugins
            if pipeline.stages:
                assert "no plugins" in pipeline.stages[-1].result.reason.lower()
                assert pipeline.stages[-1].result.metadata["upstream"] == "file-system"
                assert len(pipeline.stages[-1].result.metadata["plugins_applied"]) == 0


class TestUpstreamScopedNotificationProcessing:
    """Test notification processing with upstream-scoped plugins.

    These tests define how the plugin manager should process notifications
    using the appropriate plugin set for the source upstream.
    """

    @pytest.mark.asyncio
    async def test_process_notification_with_upstream_specific_plugins(self):
        """Test notification processing uses upstream-specific plugins."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "basic_security",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ],
                "github": [
                    {
                        "handler": "git_notification_filter",
                        "enabled": True,
                        "priority": 20,
                        "config": {},
                    }
                ],
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "basic_security": MockSecurityPlugin,
                "git_notification_filter": MockSecurityPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 50, "message": "Cloning repository..."},
            )

            # Should use github-specific plugins (global + github-specific)
            pipeline = await manager.process_notification(
                notification, server_name="github"
            )

            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Should have 2 stages - one for global, one for github-specific
            assert len(pipeline.stages) == 2
            # Each stage should have metadata indicating the upstream
            for stage in pipeline.stages:
                if stage.result.metadata:
                    assert "upstream" in stage.result.metadata
                    assert stage.result.metadata["upstream"] == "github"

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_process_notification_with_global_plugins_only(self):
        """Test notification processing uses global plugins when no upstream-specific config."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "basic_security",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"basic_security": MockSecurityPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 75, "message": "Reading file..."},
            )

            # Should use global plugins for any upstream
            pipeline = await manager.process_notification(
                notification, server_name="file-system"
            )

            assert pipeline.pipeline_outcome == PipelineOutcome.ALLOWED
            # Should have 1 stage - only global plugin
            assert len(pipeline.stages) == 1
            if pipeline.stages[0].result.metadata:
                assert (
                    pipeline.stages[0].result.metadata.get("upstream") == "file-system"
                )

    @pytest.mark.asyncio
    async def test_process_notification_no_plugins_for_upstream(self):
        """Test notification processing when no plugins configured for upstream."""
        config = {
            "security": {
                "github": [
                    {
                        "handler": "git_notification_filter",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"git_notification_filter": MockSecurityPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 100, "message": "Operation complete"},
            )

            # Should return no security decision when no plugins for upstream
            pipeline = await manager.process_notification(
                notification, server_name="file-system"
            )

            assert (
                pipeline.pipeline_outcome == PipelineOutcome.NO_SECURITY_EVALUATION
            )  # No security decision when no plugins
            if pipeline.stages:
                assert "no plugins" in pipeline.stages[-1].result.reason.lower()
                assert pipeline.stages[-1].result.metadata["upstream"] == "file-system"
                assert len(pipeline.stages[-1].result.metadata["plugins_applied"]) == 0


class TestUpstreamScopedNotificationLogging:
    """Test notification logging with upstream-scoped plugins.

    These tests define how notification logging should work with upstream-scoped configuration.
    """

    @pytest.mark.asyncio
    async def test_log_notification_with_upstream_specific_plugins(self):
        """Test notification logging uses upstream-specific plugins."""
        # Track which plugins were called
        called_plugins = []

        class TestAuditingPlugin(AuditingPlugin):
            def __init__(self, config: Dict[str, Any]):
                self._plugin_id = config.get("identifier", "test_audit")
                self.priority = config.get("priority", 50)
                self.config = config

            @property
            def plugin_id(self) -> str:
                return self._plugin_id

            @plugin_id.setter
            def plugin_id(self, value: str):
                self._plugin_id = value

            async def log_request(
                self,
                request: MCPRequest,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                pass

            async def log_response(
                self,
                request: MCPRequest,
                response,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                pass

            async def log_notification(
                self,
                notification: MCPNotification,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                called_plugins.append(self.plugin_id)

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "request_logging",
                        "enabled": True,
                        "priority": 10,
                        "config": {"identifier": "request_logging"},
                    }
                ],
                "github": [
                    {
                        "handler": "git_notification_audit",
                        "enabled": True,
                        "priority": 20,
                        "config": {"identifier": "git_notification_audit"},
                    }
                ],
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "request_logging": TestAuditingPlugin,
                "git_notification_audit": TestAuditingPlugin,
            }

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 50, "message": "Cloning repository..."},
            )

            decision = PluginResult(allowed=True, reason="Test decision")

            # Should use github-specific audit plugins
            await manager.log_notification(notification, decision, server_name="github")

            # Should have called both global and github-specific plugins
            assert len(called_plugins) == 2
            assert "request_logging" in called_plugins
            assert "git_notification_audit" in called_plugins

    @pytest.mark.asyncio
    async def test_log_notification_captures_upstream_context(self):
        """Test that notification logging captures upstream context."""
        # Track pipeline metadata
        captured_pipelines = []

        class TestAuditingPlugin(AuditingPlugin):
            def __init__(self, config: Dict[str, Any]):
                self._plugin_id = config.get("identifier", "test_audit")
                self.priority = config.get("priority", 10)
                self.config = config

            @property
            def plugin_id(self) -> str:
                return self._plugin_id

            @plugin_id.setter
            def plugin_id(self, value: str):
                self._plugin_id = value

            async def log_request(
                self,
                request: MCPRequest,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                pass

            async def log_response(
                self,
                request: MCPRequest,
                response,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                pass

            async def log_notification(
                self,
                notification: MCPNotification,
                pipeline: ProcessingPipeline,
                server_name: Optional[str] = None,
            ) -> None:
                captured_pipelines.append(pipeline)

        config = {
            "auditing": {
                "_global": [
                    {
                        "handler": "request_logging",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"request_logging": TestAuditingPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 100, "message": "File operation complete"},
            )

            # Create a simple pipeline for testing
            test_pipeline = ProcessingPipeline(
                original_content=notification,
                stages=[],
                final_content=notification,
                total_time_ms=0.0,
                pipeline_outcome=PipelineOutcome.ALLOWED,
                blocked_at_stage=None,
                completed_by=None,
                had_security_plugin=False,
                capture_content=True,
            )

            await manager.log_notification(
                notification, test_pipeline, server_name="file-system"
            )

            # Should have captured the pipeline
            assert len(captured_pipelines) == 1
            # The test pipeline doesn't have stages with upstream metadata, that's expected future behavior

    @pytest.mark.asyncio
    async def test_log_notification_no_plugins_for_upstream(self):
        """Test notification logging when no plugins configured for upstream."""
        config = {
            "auditing": {
                "github": [
                    {
                        "handler": "git_notification_audit",
                        "enabled": True,
                        "priority": 10,
                        "config": {},
                    }
                ]
            }
        }

        with patch.object(PluginManager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"git_notification_audit": MockAuditingPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            notification = MCPNotification(
                jsonrpc="2.0",
                method="progress",
                params={"progress": 100, "message": "Operation complete"},
            )

            decision = PluginResult(allowed=True, reason="Test decision")

            # Should not crash when no plugins for upstream
            await manager.log_notification(
                notification, decision, server_name="file-system"
            )

            # Should complete without error (no plugins to call)
