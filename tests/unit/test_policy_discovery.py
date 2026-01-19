"""Tests for policy discovery and loading functionality."""

import pytest
from typing import Optional
from unittest.mock import patch, MagicMock
from gatekit.plugins.manager import PluginManager
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult


class TestPolicyDiscovery:
    """Test policy discovery functionality."""

    def test_policy_discovery_scans_security_directory(self):
        """Test that policy discovery scans the security plugin directory."""
        config = {"security": {"_global": []}, "auditing": {"_global": []}}

        manager = PluginManager(config)

        # This should discover policies from gatekit/plugins/security/
        policies = manager._discover_handlers("security")

        # Should find security plugins like pii, secrets, prompt_injection
        assert "basic_pii_filter" in policies
        assert "basic_secrets_filter" in policies
        assert "basic_prompt_injection_defense" in policies

    def test_policy_discovery_scans_middleware_directory(self):
        """Test that policy discovery scans the middleware plugin directory."""
        config = {
            "middleware": {"_global": []},
            "security": {"_global": []},
            "auditing": {"_global": []},
        }

        manager = PluginManager(config)

        # This should discover policies from gatekit/plugins/middleware/
        policies = manager._discover_handlers("middleware")

        # Should find the tool_manager middleware plugin
        assert "tool_manager" in policies
        assert callable(policies["tool_manager"])

    def test_policy_discovery_scans_auditing_directory(self):
        """Test that policy discovery scans the auditing plugin directory."""
        config = {
            "security": {"_global": []},
            "auditing": {
                "_global": [{"handler": "audit_jsonl", "config": {"enabled": True}}]
            },
        }

        manager = PluginManager(config)

        # This should discover policies from gatekit/plugins/auditing/
        policies = manager._discover_handlers("auditing")

        # Should find at least the json_auditing policy
        assert "audit_jsonl" in policies
        assert callable(policies["audit_jsonl"])

    def test_policy_discovery_handles_missing_directory(self):
        """Test policy discovery handles missing plugin directories gracefully."""
        config = {"security": {"_global": []}, "auditing": {"_global": []}}
        manager = PluginManager(config)

        # Should return empty dict for non-existent category
        policies = manager._discover_handlers("nonexistent")
        assert policies == {}

    def test_policy_discovery_ignores_files_without_policies_manifest(self):
        """Test that files without HANDLERS manifest are ignored."""
        config = {"security": {"_global": []}, "auditing": {"_global": []}}
        manager = PluginManager(config)

        with patch("pathlib.Path.glob") as mock_glob:
            # Mock finding a Python file
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.suffix = ".py"
            mock_file.__str__ = lambda: "test_file.py"
            mock_glob.return_value = [mock_file]

            with patch("importlib.util.spec_from_file_location") as mock_spec:
                mock_module = MagicMock()
                # Module without HANDLERS attribute
                del mock_module.HANDLERS  # Ensure no HANDLERS attribute
                mock_spec.return_value.loader.exec_module.return_value = None

                policies = manager._discover_handlers("security")

                # Should be empty since no HANDLERS manifest found
                assert policies == {}


class TestPolicyBasedLoading:
    """Test policy-based plugin loading."""

    @pytest.mark.asyncio
    async def test_load_plugin_by_policy_name(self):
        """Test loading a plugin by handler name."""
        config = {
            "security": {
                "filesystem": [
                    {
                        "handler": "tool_allowlist",
                        "enabled": True,
                        "config": {"tools": ["read_file"]},
                    }
                ]
            },
            "auditing": {"_global": []},
        }

        manager = PluginManager(config)

        # Create a proper mock plugin class that inherits from SecurityPlugin
        class MockSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                self.config = config

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test")

        # Mock policy discovery
        with patch.object(manager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"tool_allowlist": MockSecurityPlugin}

            await manager.load_plugins()

            # Should have loaded one security plugin for filesystem server
            assert len(manager.upstream_security_plugins["filesystem"]) == 1
            assert isinstance(
                manager.upstream_security_plugins["filesystem"][0], MockSecurityPlugin
            )
            assert manager.upstream_security_plugins["filesystem"][0].config == {
                "tools": ["read_file"]
            }

    @pytest.mark.asyncio
    async def test_load_plugin_policy_not_found_error(self):
        """Test error when requested policy is not found."""
        config = {
            "security": {
                "_global": [
                    {"handler": "nonexistent_policy", "config": {"enabled": True}}
                ]
            },
            "auditing": {},
        }

        manager = PluginManager(config)

        # Create a proper mock plugin class
        class MockSecurityPlugin(SecurityPlugin):
            def __init__(self, config):
                self.config = config

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="test")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test")

        # Mock policy discovery returning only tool_allowlist
        with patch.object(manager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {"tool_allowlist": MockSecurityPlugin}

            with pytest.raises(ValueError) as exc_info:
                await manager.load_plugins()

            error_msg = str(exc_info.value)
            assert "Handler 'nonexistent_policy' not found" in error_msg
            assert "Available handlers: tool_allowlist" in error_msg

    @pytest.mark.asyncio
    async def test_load_multiple_policies_from_same_file(self):
        """Test loading multiple policies from the same plugin file."""
        config = {
            "security": {
                "_global": [
                    {"handler": "policy_one", "config": {"enabled": True}},
                    {"handler": "policy_two", "config": {"enabled": True}},
                ]
            },
            "auditing": {"_global": []},
        }

        manager = PluginManager(config)

        # Create proper mock plugin classes
        class MockSecurityPlugin1(SecurityPlugin):
            def __init__(self, config):
                self.config = config

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="test1")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test1")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test1")

        class MockSecurityPlugin2(SecurityPlugin):
            def __init__(self, config):
                self.config = config

            async def process_request(self, request, server_name: Optional[str] = None):
                return PluginResult(allowed=True, reason="test2")

            async def process_response(
                self, request, response, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test2")

            async def process_notification(
                self, notification, server_name: Optional[str] = None
            ):
                return PluginResult(allowed=True, reason="test2")

        # Mock policy discovery with multiple policies
        with patch.object(manager, "_discover_handlers") as mock_discover:
            mock_discover.return_value = {
                "policy_one": MockSecurityPlugin1,
                "policy_two": MockSecurityPlugin2,
            }

            await manager.load_plugins()

            # Should have loaded two security plugins
            assert len(manager.security_plugins) == 2
            assert isinstance(manager.security_plugins[0], MockSecurityPlugin1)
            assert isinstance(manager.security_plugins[1], MockSecurityPlugin2)


class TestPolicyConfigurationValidation:
    """Test policy-based configuration validation."""

    def test_policy_field_required(self):
        """Test that policy field is required in plugin configuration."""
        from gatekit.config.models import PluginConfigSchema
        from pydantic import ValidationError

        # Should raise validation error for missing handler field
        with pytest.raises(ValidationError) as exc_info:
            PluginConfigSchema(config={})

        assert "handler" in str(exc_info.value)

    def test_policy_field_validation(self):
        """Test policy field validation."""
        from gatekit.config.models import PluginConfigSchema

        # Valid policy configuration
        config = PluginConfigSchema(
            handler="tool_allowlist", config={"enabled": True, "tools": ["read_file"]}
        )

        assert config.handler == "tool_allowlist"
        assert config.config["enabled"] is True
        assert config.config["tools"] == ["read_file"]

    def test_policy_config_backwards_compatibility_removed(self):
        """Test that path field is no longer supported."""
        from gatekit.config.models import PluginConfigSchema
        from pydantic import ValidationError

        # Should raise validation error for old path field
        with pytest.raises(ValidationError):
            PluginConfigSchema(
                path="./plugins/security/tool_allowlist.py",  # Old format
                enabled=True,
                config={},
            )
