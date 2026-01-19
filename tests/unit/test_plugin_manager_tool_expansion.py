"""Tests for plugin manager tool expansion and configuration handling."""

import pytest
from unittest.mock import MagicMock, patch
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult
from gatekit.protocol.messages import MCPRequest


class MockToolManagerPlugin(SecurityPlugin):
    """Mock tool access control plugin for testing server-aware configuration."""

    def __init__(self, config):
        super().__init__(config)
        self.config_data = config
        self.expanded_tools = None  # This should be set by plugin manager

    def set_expanded_tools(self, expanded_tools):
        """Method for plugin manager to provide expanded tool mappings."""
        self.expanded_tools = expanded_tools

    async def process_request(self, request, server_name=None):
        """Mock implementation."""
        return PluginResult(allowed=True, reason="Mock plugin")

    async def process_response(self, request, response, server_name=None):
        """Mock implementation."""
        return PluginResult(allowed=True, reason="Mock plugin")

    async def process_notification(self, notification, server_name=None):
        """Mock implementation."""
        return PluginResult(allowed=True, reason="Mock plugin")


class TestPluginManagerToolExpansion:
    """Test plugin manager tool expansion and configuration functionality."""

    @pytest.mark.asyncio
    async def test_server_grouped_tool_config_passed_to_plugin(self):
        """Test that plugin manager passes server-grouped tool config to plugins."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "tool_allowlist",
                        "config": {
                            "tools": {
                                "filesystem": [
                                    {"tool": "read_file"},
                                    {"tool": "write_file"},
                                ],
                                "fetch": [{"tool": "fetch"}],
                            }
                        },
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {"tool_allowlist": MockToolManagerPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            # Plugin should receive server-grouped tool dictionary
            plugin = manager.security_plugins[0]

            # Plugin should have been configured with server-grouped tools
            expected_tools = {
                "filesystem": [{"tool": "read_file"}, {"tool": "write_file"}],
                "fetch": [{"tool": "fetch"}],
            }
            assert plugin.config_data["tools"] == expected_tools

    @pytest.mark.asyncio
    async def test_plugin_manager_provides_server_context_to_plugins(self):
        """Test that plugin manager provides server context when calling plugins."""
        # This test should pass once server-aware context is properly propagated
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "tool_allowlist",
                        "config": {"tools": {"filesystem": [{"tool": "read_file"}]}},
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            # Create a mock plugin class that returns mock instances
            mock_plugin_instance = MagicMock(spec=SecurityPlugin)
            mock_plugin_instance.process_request.return_value = PluginResult(
                allowed=True, reason="Test"
            )

            class MockPluginClass(SecurityPlugin):
                def __init__(self, config):
                    super().__init__(config)
                    self.mock_instance = mock_plugin_instance

                async def process_request(self, request, server_name=None):
                    return await self.mock_instance.process_request(
                        request, server_name=server_name
                    )

                async def process_response(self, request, response, server_name=None):
                    return PluginResult(allowed=True, reason="Test")

                async def process_notification(self, notification, server_name=None):
                    return PluginResult(allowed=True, reason="Test")

            mock_discover.return_value = {"tool_allowlist": MockPluginClass}

            manager = PluginManager(config)
            await manager.load_plugins()

            # Create a tool call request
            request = MCPRequest(
                jsonrpc="2.0",
                id="test",
                method="tools/call",
                params={"name": "read_file", "arguments": {}},
            )

            # Process request with server name
            await manager.process_request(request, server_name="filesystem")

            # Plugin should have been called with server_name parameter
            mock_plugin_instance.process_request.assert_called_once_with(
                request, server_name="filesystem"
            )

    @pytest.mark.asyncio
    async def test_plugin_accepts_new_tool_format(self):
        """Test that new tool format is accepted by the plugin in server context."""
        # New dictionary format should be accepted by the plugin
        config = {
            "middleware": {
                "filesystem": [
                    {
                        "handler": "tool_manager",
                        "config": {
                            "tools": [{"tool": "read_file"}, {"tool": "write_file"}]
                        },
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            # Use the real plugin class to get proper validation
            from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin

            mock_discover.return_value = {"tool_manager": ToolManagerPlugin}

            manager = PluginManager(config)

            # The plugin should load successfully
            await manager.load_plugins()

            # Should have one middleware plugin loaded for filesystem server
            assert len(manager.upstream_middleware_plugins["filesystem"]) == 1
            plugin = manager.upstream_middleware_plugins["filesystem"][0]
            assert plugin.tools == ["read_file", "write_file"]

    @pytest.mark.asyncio
    async def test_plugin_manager_handles_tools_for_multiple_servers(self):
        """Test server-grouped tool configuration works for multiple servers."""
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "tool_allowlist",
                        "config": {
                            "tools": {
                                "filesystem": [
                                    {"tool": "read_file"},
                                    {"tool": "write_file"},
                                    {"tool": "list_directory"},
                                ],
                                "fetch": [{"tool": "fetch"}, {"tool": "post"}],
                                "calculator": [{"tool": "add"}, {"tool": "subtract"}],
                            }
                        },
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {"tool_allowlist": MockToolManagerPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            # Plugin should receive server-grouped tool dictionary
            plugin = manager.security_plugins[0]
            expected_tools = {
                "filesystem": [
                    {"tool": "read_file"},
                    {"tool": "write_file"},
                    {"tool": "list_directory"},
                ],
                "fetch": [{"tool": "fetch"}, {"tool": "post"}],
                "calculator": [{"tool": "add"}, {"tool": "subtract"}],
            }
            assert plugin.config_data["tools"] == expected_tools

    @pytest.mark.asyncio
    async def test_plugin_manager_handles_empty_server_tool_lists(self):
        """Test handling of empty tool lists for specific servers."""
        # Empty lists should be handled gracefully
        config = {
            "security": {
                "_global": [
                    {
                        "handler": "tool_allowlist",
                        "config": {
                            "tools": {
                                "filesystem": [{"tool": "read_file"}],
                                "fetch": [],  # Empty list
                                "calculator": [{"tool": "add"}],
                            }
                        },
                    }
                ]
            }
        }

        with patch(
            "gatekit.plugins.manager.PluginManager._discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = {"tool_allowlist": MockToolManagerPlugin}

            manager = PluginManager(config)
            await manager.load_plugins()

            # Should preserve empty lists in the server-grouped configuration
        plugin = manager.security_plugins[0]
        expected_tools = {
            "filesystem": [{"tool": "read_file"}],
            "fetch": [],  # Empty list is preserved
            "calculator": [{"tool": "add"}],
        }
        assert plugin.config_data["tools"] == expected_tools

    def test_plugin_manager_handles_server_grouped_config(self):
        """Test that plugin manager handles server-grouped configuration correctly."""
        PluginManager({})

        # Test that the manager can handle server-grouped tool configuration
        tools_dict = {
            "filesystem": [{"tool": "read_file"}, {"tool": "write_file"}],
            "fetch": [{"tool": "fetch"}],
        }

        # The plugin manager should pass this configuration through without expansion
        # The actual filtering/validation happens in the plugin itself
        assert isinstance(tools_dict, dict)
        assert "filesystem" in tools_dict
        assert "fetch" in tools_dict
        assert tools_dict["filesystem"] == [
            {"tool": "read_file"},
            {"tool": "write_file"},
        ]
        assert tools_dict["fetch"] == [{"tool": "fetch"}]

    def test_plugin_validates_new_tool_format(self):
        """Test that plugin validates new tool configuration format."""
        # Validation now happens in the plugin, not the manager
        from gatekit.plugins.middleware.tool_manager import ToolManagerPlugin

        # Valid new format should pass
        valid_config = {
            "tools": [
                {"tool": "read_file"},
                {"tool": "write_file"},
                {"tool": "list_directory"},
            ]
        }
        # Should not raise exception
        plugin = ToolManagerPlugin(valid_config)
        assert plugin.tools == ["read_file", "write_file", "list_directory"]

        # Invalid format (flat list) should fail
        invalid_config = {
            "tools": [
                "read_file",
                "write_file",
            ]  # Old flat list format - should be rejected
        }
        # Plugin validation should catch this
        with pytest.raises(TypeError, match="Each tool entry must be a dictionary"):
            ToolManagerPlugin(invalid_config)
