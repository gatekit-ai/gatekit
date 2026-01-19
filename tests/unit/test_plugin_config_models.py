"""Tests for plugin configuration models."""

import pytest
from pydantic import ValidationError

from gatekit.config.models import (
    PluginConfigSchema,
    PluginsConfigSchema,
    PluginConfig,
    PluginsConfig,
    ProxyConfig,
    ProxyConfigSchema,
)


class TestPluginConfigSchema:
    """Test PluginConfigSchema Pydantic validation."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_valid_plugin_config_schema(self):
        """Test valid plugin configuration schema validation."""
        data = {
            "handler": "tool_manager",
            "config": {"enabled": True, "tools": [{"tool": "read_file"}, {"tool": "list_directory"}]},
        }

        schema = PluginConfigSchema(**data)

        assert schema.handler == "tool_manager"
        assert schema.config["enabled"] is True
        assert schema.config["tools"] == [{"tool": "read_file"}, {"tool": "list_directory"}]

    def test_plugin_config_schema_defaults(self):
        """Test default values for plugin configuration."""
        data = {"handler": "tool_manager"}

        schema = PluginConfigSchema(**data)

        assert schema.handler == "tool_manager"
        assert schema.config == {}  # Default empty dict
        # Note: enabled and priority are now in the config dict, not top-level fields

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_plugin_config_schema_validation_errors(self):
        """Test validation errors for invalid plugin configuration."""
        # Missing required handler field
        with pytest.raises(ValidationError) as exc_info:
            PluginConfigSchema(config={})

        error = exc_info.value
        assert "handler" in str(error).lower()
        assert (
            "field required" in str(error).lower()
            or "either 'policy' or 'name' field must be provided" in str(error).lower()
        )

        # Extra fields not permitted (old format with top-level enabled)
        with pytest.raises(ValidationError) as exc_info:
            PluginConfigSchema(handler="tool_manager", enabled=True)

        error = exc_info.value
        assert "extra" in str(error).lower() or "permitted" in str(error).lower()

        # Invalid config type
        with pytest.raises(ValidationError) as exc_info:
            PluginConfigSchema(handler="tool_manager", config="invalid")

        error = exc_info.value
        assert "config" in str(error)


class TestPluginsConfigSchema:
    """Test PluginsConfigSchema Pydantic validation."""

    def test_valid_plugins_config_schema(self):
        """Test valid plugins configuration schema validation."""
        data = {
            "security": {
                "_global": [
                    {
                        "handler": "tool_manager",
                        "config": {"enabled": True, "tools": []},
                    }
                ]
            },
            "auditing": {
                "_global": [
                    {
                        "handler": "audit_jsonl",
                        "config": {"enabled": True, "file": "test.log"},
                    }
                ]
            },
        }

        schema = PluginsConfigSchema(**data)

        assert len(schema.security["_global"]) == 1
        assert len(schema.auditing["_global"]) == 1
        assert schema.security["_global"][0].handler == "tool_manager"
        assert schema.auditing["_global"][0].handler == "audit_jsonl"

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_plugins_config_schema_defaults(self):
        """Test default values for plugins configuration."""
        schema = PluginsConfigSchema()

        assert schema.security == {}  # Default empty dict
        assert schema.auditing == {}  # Default empty dict

    def test_plugins_config_schema_partial(self):
        """Test plugins configuration with only one plugin type."""
        data = {"security": {"_global": [{"handler": "tool_manager"}]}}

        schema = PluginsConfigSchema(**data)

        assert len(schema.security["_global"]) == 1
        assert len(schema.auditing) == 0  # Uses default


class TestPluginConfig:
    """Test PluginConfig dataclass."""

    def test_plugin_config_from_schema(self):
        """Test conversion from schema to dataclass."""
        schema = PluginConfigSchema(
            handler="tool_manager",
            config={"enabled": True, "tools": [{"tool": "read_file"}]},
        )

        config = PluginConfig.from_schema(schema)

        assert config.handler == "tool_manager"
        assert config.enabled is True
        assert config.config == {"enabled": True, "tools": [{"tool": "read_file"}]}

    def test_plugin_config_policy_field(self):
        """Test that plugin config uses 'handler' field (not 'path')."""
        config = PluginConfig(handler="tool_manager", config={"enabled": True})

        assert hasattr(config, "handler")
        assert not hasattr(config, "path")
        assert config.handler == "tool_manager"

    def test_plugin_config_defaults(self):
        """Test default values for plugin configuration."""
        config = PluginConfig(handler="tool_manager")

        assert config.handler == "tool_manager"
        assert config.enabled is True
        assert config.config == {}


class TestPluginsConfig:
    """Test PluginsConfig dataclass."""

    def test_plugins_config_from_schema(self):
        """Test conversion of full plugins configuration."""
        schema = PluginsConfigSchema(
            security={
                "_global": [
                    PluginConfigSchema(
                        handler="tool_manager", config={"enabled": True, "tools": []}
                    )
                ]
            },
            auditing={
                "_global": [
                    PluginConfigSchema(
                        handler="audit_jsonl",
                        config={"enabled": True, "file": "test.log"},
                    )
                ]
            },
        )

        config = PluginsConfig.from_schema(schema)

        assert len(config.security["_global"]) == 1
        assert len(config.auditing["_global"]) == 1
        assert config.security["_global"][0].handler == "tool_manager"
        assert config.auditing["_global"][0].handler == "audit_jsonl"

    def test_empty_plugins_config(self):
        """Test empty plugin configuration (should use defaults)."""
        schema = PluginsConfigSchema()
        config = PluginsConfig.from_schema(schema)

        assert config.security == {}
        assert config.auditing == {}

    def test_plugins_config_defaults(self):
        """Test default values for plugins configuration."""
        config = PluginsConfig()

        assert config.security == {}
        assert config.auditing == {}


class TestProxyConfigWithPlugins:
    """Test ProxyConfig with plugin configuration support."""

    def test_proxy_config_with_plugins(self):
        """Test ProxyConfig with plugin configuration."""
        from gatekit.config.models import UpstreamConfig, TimeoutConfig

        upstream = UpstreamConfig(name="test", command=["python", "-m", "test"])
        timeouts = TimeoutConfig(connection_timeout=30, request_timeout=60)
        plugins = PluginsConfig(
            security={
                "_global": [
                    PluginConfig(
                        handler="tool_manager", config={"enabled": True, "tools": []}
                    )
                ]
            }
        )

        config = ProxyConfig(
            transport="stdio", upstreams=[upstream], timeouts=timeouts, plugins=plugins
        )

        assert config.transport == "stdio"
        assert config.upstreams[0] == upstream
        assert config.timeouts == timeouts
        assert config.plugins == plugins
        assert len(config.plugins.security["_global"]) == 1

    def test_proxy_config_without_plugins(self):
        """Test ProxyConfig without plugin configuration (backwards compatibility)."""
        from gatekit.config.models import UpstreamConfig, TimeoutConfig

        upstream = UpstreamConfig(name="test", command=["python", "-m", "test"])
        timeouts = TimeoutConfig(connection_timeout=30, request_timeout=60)

        config = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        assert config.transport == "stdio"
        assert config.upstreams[0] == upstream
        assert config.timeouts == timeouts
        assert config.plugins is None  # Should be None when not provided


class TestServerAwareToolConfiguration:
    """Test new server-aware tool configuration format."""

    def test_tool_allowlist_server_aware_config_schema(self):
        """Test server-aware tool configuration schema validation (should fail initially)."""
        # This test should fail until we implement the new server-aware format
        server_aware_config = {
            "handler": "tool_manager",
            "config": {
                "tools": {
                    "filesystem": [{"tool": "read_file"}, {"tool": "write_file"}],
                    "fetch": [{"tool": "fetch"}],
                }
            },
        }

        # This should pass when server-aware config is implemented
        schema = PluginConfigSchema(**server_aware_config)

        # Validate the nested structure
        assert schema.config["tools"]["filesystem"] == [
            {"tool": "read_file"},
            {"tool": "write_file"},
        ]
        assert schema.config["tools"]["fetch"] == [{"tool": "fetch"}]

    def test_tool_allowlist_old_format_still_works(self):
        """Test that old list format still works for now (but server-aware is preferred)."""
        # Simple list format still works (no __ in tool names since we never shipped that)
        old_config = {
            "handler": "tool_manager",
            "config": {"tools": [{"tool": "read_file"}, {"tool": "fetch"}]},
        }

        # This should still work - simple validation
        schema = PluginConfigSchema(**old_config)
        assert schema.config["tools"] == [{"tool": "read_file"}, {"tool": "fetch"}]

    def test_tool_allowlist_server_name_validation(self):
        """Test server name validation against upstream configs."""
        # This should validate server names exist in upstream configuration

        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "filesystem", "command": ["python", "-m", "filesystem"]},
                {"name": "fetch", "command": ["python", "-m", "fetch"]},
            ],
            "plugins": {
                "middleware": {
                    "nonexistent": [
                        {  # This upstream doesn't exist
                            "handler": "tool_manager",
                            "config": {"tools": [{"tool": "some_tool"}]},
                        }
                    ]
                }
            },
        }

        # Should fail validation due to nonexistent upstream
        with pytest.raises(ValidationError) as exc_info:
            ProxyConfigSchema(**proxy_config)

        error = str(exc_info.value)
        assert "nonexistent" in error

    def test_single_server_requires_name(self):
        """Test that all servers require names."""
        # All servers should require names
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"command": ["python", "-m", "filesystem"]}  # No name provided
            ],
            "plugins": {
                "middleware": {
                    "_global": [
                        {
                            "handler": "tool_manager",
                            "config": {
                                "tools": {
                                    "filesystem": [
                                        {"tool": "read_file"}
                                    ]  # Can't reference server without name
                                }
                            },
                        }
                    ]
                }
            },
        }

        # Should fail because upstream has no name but plugin references "filesystem"
        with pytest.raises(ValidationError) as exc_info:
            ProxyConfigSchema(**proxy_config)

        error = str(exc_info.value)
        assert "name" in error.lower()

    def test_pii_filter_server_aware_config(self):
        """Test server-aware configuration for PII filter plugin (should fail initially)."""
        # Test basic plugin configuration without exemptions
        pii_config = {
            "handler": "pii_filter",
            "config": {"action": "redact", "pii_types": {"email": {"enabled": True}}},
        }

        schema = PluginConfigSchema(**pii_config)
        assert schema.handler == "pii_filter"
        assert schema.config["action"] == "redact"


class TestPluginScopeValidation:
    """Test plugin scope validation in configuration models."""

    def test_server_aware_plugin_in_global_section_fails(self):
        """Test that server_aware plugins cannot be configured in _global section."""
        # Tool allowlist is a server_aware plugin that requires per-server configuration
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "filesystem", "command": ["test-command", "--arg"], "args": []}
            ],
            "plugins": {
                "middleware": {
                    "_global": [
                        {
                            "handler": "tool_manager",
                            "config": {
                                "tools": {"filesystem": [{"tool": "read_file"}]}
                            },
                        }
                    ]
                }
            },
        }

        # This should fail because tool_allowlist is server_aware and cannot be in _global
        with pytest.raises(ValueError) as exc_info:
            ProxyConfigSchema(**proxy_config)

        error_msg = str(exc_info.value)
        assert "server_aware" in error_msg
        assert "_global" in error_msg
        assert "tool_manager" in error_msg

    def test_global_plugin_in_global_section_succeeds(self):
        """Test that global plugins can be configured in _global section."""
        # PII filter is a global plugin that can be configured globally
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "filesystem", "command": ["test-command", "--arg"], "args": []}
            ],
            "plugins": {
                "security": {
                    "_global": [
                        {
                            "handler": "pii_filter",
                            "config": {
                                "action": "redact",
                                "pii_types": {"email": {"enabled": True}},
                            },
                        }
                    ]
                }
            },
        }

        # This should succeed because pii_filter is a global plugin
        schema = ProxyConfigSchema(**proxy_config)
        assert len(schema.plugins.security["_global"]) == 1
        assert schema.plugins.security["_global"][0].handler == "pii_filter"

    def test_server_aware_plugin_in_server_section_succeeds(self):
        """Test that server_aware plugins can be configured in individual server sections."""
        # Tool allowlist should work in server-specific sections
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "filesystem", "command": ["test-command", "--arg"], "args": []}
            ],
            "plugins": {
                "middleware": {
                    "filesystem": [
                        {
                            "handler": "tool_manager",
                            "config": {"tools": [{"tool": "read_file"}]},
                        }
                    ]
                }
            },
        }

        # This should succeed because tool_allowlist is in a server section
        schema = ProxyConfigSchema(**proxy_config)
        assert len(schema.plugins.middleware["filesystem"]) == 1
        assert schema.plugins.middleware["filesystem"][0].handler == "tool_manager"
