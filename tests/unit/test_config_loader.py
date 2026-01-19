"""Unit tests for configuration loader."""

import pytest
import tempfile
from pathlib import Path

from gatekit.config.loader import ConfigLoader
from gatekit.config.errors import ConfigError
from gatekit.utils.exceptions import ConfigValidationError
from gatekit.config.models import (
    ProxyConfig,
    UpstreamConfig,
    TimeoutConfig,
)


class TestConfigLoader:
    """Test ConfigLoader YAML loading and validation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_load_minimal_config_from_dict(self, minimal_proxy_config_dict):
        """Test loading minimal valid configuration from dictionary."""
        config = self.loader.load_from_dict(minimal_proxy_config_dict)

        assert isinstance(config, ProxyConfig)
        assert config.transport == "stdio"
        assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]
        assert config.timeouts.connection_timeout == 30
        assert config.timeouts.request_timeout == 60
        assert config.http is None

    def test_load_complete_config_from_dict(self, complete_proxy_config_dict):
        """Test loading complete configuration from dictionary."""
        config = self.loader.load_from_dict(complete_proxy_config_dict)

        assert isinstance(config, ProxyConfig)
        assert config.transport == "http"
        assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]
        assert config.upstreams[0].restart_on_failure is True
        assert config.upstreams[0].max_restart_attempts == 5
        assert config.timeouts.connection_timeout == 45
        assert config.timeouts.request_timeout == 90
        assert config.http.host == "0.0.0.0"
        assert config.http.port == 9090

        assert isinstance(config, ProxyConfig)
        assert config.transport == "http"
        assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]
        assert config.upstreams[0].restart_on_failure is True
        assert config.upstreams[0].max_restart_attempts == 5
        assert config.timeouts.connection_timeout == 45
        assert config.timeouts.request_timeout == 90
        assert config.http.host == "0.0.0.0"
        assert config.http.port == 9090

    def test_load_from_yaml_file(self):
        """Test loading configuration from YAML file."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["python", "-m", "test_server"]
  timeouts:
    connection_timeout: 30
    request_timeout: 60
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = self.loader.load_from_file(Path(f.name))

            assert isinstance(config, ProxyConfig)
            assert config.transport == "stdio"
            assert config.upstreams[0].command == ["python", "-m", "test_server"]

    def test_missing_required_proxy_section(self):
        """Test handling of missing proxy section."""
        config_dict = {"other_section": {"some_key": "some_value"}}

        with pytest.raises(
            ConfigError, match="Configuration must contain 'proxy' section"
        ):
            self.loader.load_from_dict(config_dict)

    def test_missing_required_upstream_section(self):
        """Test handling of missing upstream configuration."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(
            ConfigError, match="Missing required 'upstreams' configuration"
        ):
            self.loader.load_from_dict(config_dict)

    def test_missing_timeouts_section_uses_defaults(self):
        """Test that missing timeout configuration uses defaults."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "my_server"]}
                ],
            }
        }

        config = self.loader.load_from_dict(config_dict)

        # Should use default timeout values
        assert config.timeouts.connection_timeout == 60
        assert config.timeouts.request_timeout == 60

    def test_invalid_yaml_syntax(self):
        """Test handling of malformed YAML."""
        invalid_yaml = """
proxy:
  transport: stdio
  upstreams:
    - command: ["python", "-m", "test_server"
    # Missing closing bracket and proper indentation
  invalid_syntax_here
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_yaml)
            f.flush()

            with pytest.raises(ConfigError, match="YAML syntax error"):
                self.loader.load_from_file(Path(f.name))

    def test_file_not_found(self):
        """Test handling of missing configuration file."""
        non_existent_path = Path("/non/existent/config.yaml")

        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            self.loader.load_from_file(non_existent_path)

    def test_config_validation_validates_upstream(self):
        """Test that config validation calls upstream validation."""
        upstream = UpstreamConfig(name="test", command=["python", "server.py"])
        timeouts = TimeoutConfig()

        config = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        # Should not raise any errors for valid config
        self.loader.validate_config(config)

    def test_config_validation_catches_invalid_transport(self):
        """Test that config validation catches invalid transport types."""
        upstream = UpstreamConfig(name="test", command=["python", "server.py"])
        timeouts = TimeoutConfig()

        # Create config with invalid transport bypassing normal validation
        # This tests our additional validation layer
        config = ProxyConfig.__new__(ProxyConfig)
        config.transport = "websocket"  # Invalid transport
        config.upstreams = [upstream]
        config.timeouts = timeouts
        config.http = None

        with pytest.raises(
            ConfigValidationError, match="Transport must be 'stdio' or 'http'"
        ):
            self.loader.validate_config(config)

    def test_loads_with_defaults_when_optional_fields_missing(self):
        """Test loading configuration with optional fields missing uses defaults."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": ["python", "-m", "my_server"],
                        # Missing optional fields
                    }
                ],
                "timeouts": {
                    # Missing optional timeout values - should use defaults
                },
            }
        }

        config = self.loader.load_from_dict(config_dict)

        # Check defaults are applied
        assert config.upstreams[0].restart_on_failure is True
        assert config.upstreams[0].max_restart_attempts == 3
        assert config.timeouts.connection_timeout == 60
        assert config.timeouts.request_timeout == 60

    def test_partial_timeout_config_uses_defaults(self):
        """Test that partial timeout configuration uses defaults for missing values."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "my_server"]}
                ],
                "timeouts": {
                    "connection_timeout": 45
                    # Missing request_timeout - should use default
                },
            }
        }

        config = self.loader.load_from_dict(config_dict)

        # Check custom value is used
        assert config.timeouts.connection_timeout == 45
        # Check default is used for missing value
        assert config.timeouts.request_timeout == 60

    def test_http_transport_requires_http_config_in_yaml(self):
        """Test that HTTP transport requires HTTP configuration in YAML."""
        config_dict = {
            "proxy": {
                "transport": "http",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "my_server"]}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
                # Missing http section for http transport
            }
        }

        with pytest.raises(
            ConfigError, match="HTTP transport requires http configuration"
        ):
            self.loader.load_from_dict(config_dict)

    def test_stdio_transport_works_without_http_config(self):
        """Test that stdio transport works without HTTP configuration."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "my_server"]}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
                # No http section - should be fine for stdio
            }
        }

        config = self.loader.load_from_dict(config_dict)

        assert config.transport == "stdio"
        assert config.http is None


class TestConfigLoaderEdgeCases:
    """Test edge cases and error conditions for ConfigLoader."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_empty_config_dict(self):
        """Test handling of empty configuration dictionary."""
        config_dict = {}

        with pytest.raises(
            ConfigError, match="Configuration must contain 'proxy' section"
        ):
            self.loader.load_from_dict(config_dict)

    def test_empty_yaml_file(self):
        """Test handling of empty YAML file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")  # Empty file
            f.flush()

            with pytest.raises(ConfigError, match="Configuration file is empty"):
                self.loader.load_from_file(Path(f.name))

    def test_yaml_file_with_only_comments(self):
        """Test handling of YAML file with only comments."""
        yaml_content = """
# This is a comment
# Another comment
# No actual configuration
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            with pytest.raises(ConfigError, match="Configuration file is empty"):
                self.loader.load_from_file(Path(f.name))

    def test_invalid_command_type_in_yaml(self):
        """Test handling of invalid command type in YAML."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": 123,  # Should be string or list, not int
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_invalid_timeout_type_in_yaml(self):
        """Test handling of invalid timeout type in YAML."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "my_server"]}
                ],
                "timeouts": {
                    "connection_timeout": "thirty",  # Should be int, not string
                    "request_timeout": 60,
                },
            }
        }

        from gatekit.config.errors import ConfigError

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_upstream_missing_command_field(self):
        """Test that upstream configuration must contain a command field."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        # Missing required 'command' field
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_upstream_empty_command_list(self):
        """Test that upstream command cannot be an empty list."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": []}  # Empty command list
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_upstream_command_string_format_rejected(self):
        """Test that upstream command string format is rejected (only list format supported)."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": "python -m my_mcp_server",  # String format no longer supported
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        # Should raise an exception since string format is not supported
        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_upstream_none_type_when_malformed_yaml(self):
        """Test that upstream configuration handles None values gracefully when YAML is malformed."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": None,  # Malformed YAML might result in None value
                "command": [
                    "python",
                    "-m",
                    "my_mcp_server",
                ],  # Incorrectly placed as sibling
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_upstream_invalid_type_when_malformed_yaml(self):
        """Test that upstream configuration handles non-dict types gracefully when YAML is malformed."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": "invalid string",  # Should be a list, not string
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_upstream_list_type_when_malformed_yaml(self):
        """Test that upstream configuration handles list types gracefully when YAML is malformed."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    "python",
                    "-m",
                    "my_server",
                ],  # Should be a list of dict, not list of strings
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)


class TestConfigLoaderPluginSupport:
    """Test ConfigLoader plugin configuration support."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_load_config_with_plugins(self):
        """Test loading configuration with plugins section."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": ["python", "-m", "my_mcp_server"],
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            },
            "plugins": {
                "middleware": {
                    "test_server": [  # Changed from _global since tool_manager is server-aware
                        {
                            "handler": "tool_manager",
                            "config": {"enabled": True, 
                                "tools": [
                                    {"tool": "read_file"},
                                    {"tool": "list_directory"},
                                ]
                            },
                        }
                    ]
                },
                "auditing": {
                    "_global": [
                        {
                            "handler": "audit_jsonl",
                            "config": {"enabled": True, "output_file": "logs/audit.jsonl"},
                        }
                    ]
                },
            },
        }

        config = self.loader.load_from_dict(config_dict)

        # Verify basic proxy config
        assert config.transport == "stdio"
        assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]

        # Verify plugin config was parsed
        assert config.plugins is not None
        assert len(config.plugins.middleware["test_server"]) == 1
        assert len(config.plugins.auditing["_global"]) == 1

        # Verify middleware plugin config
        middleware_plugin = config.plugins.middleware["test_server"][0]
        assert middleware_plugin.handler == "tool_manager"
        assert middleware_plugin.enabled is True
        assert middleware_plugin.config["tools"] == [
            {"tool": "read_file"},
            {"tool": "list_directory"},
        ]

        # Verify auditing plugin config
        auditing_plugin = config.plugins.auditing["_global"][0]
        assert auditing_plugin.handler == "audit_jsonl"
        assert auditing_plugin.enabled is True
        assert auditing_plugin.config["output_file"] == "logs/audit.jsonl"

    def test_load_config_without_plugins(self):
        """Test loading configuration without plugins (backwards compatibility)."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": ["python", "-m", "my_mcp_server"],
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        config = self.loader.load_from_dict(config_dict)

        # Verify basic proxy config
        assert config.transport == "stdio"
        assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]

        # Verify no plugin config
        assert config.plugins is None

    def test_plugin_config_validation_errors(self):
        """Test handling of invalid plugin configuration."""
        # Missing required policy field
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": ["python", "-m", "my_mcp_server"],
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            },
            "plugins": {
                "security": {
                    "_global": [
                        {
                            "enabled": True,  # Missing required 'policy' field
                            "config": {"tools": []},
                        }
                    ]
                }
            },
        }

        with pytest.raises(Exception) as exc_info:
            self.loader.load_from_dict(config_dict)

        error_msg = str(exc_info.value)
        # Should fail due to missing policy field
        assert "field required" in error_msg.lower() or "policy" in error_msg.lower()


class TestCommandFormatSupport:
    """Test command format validation (only array format supported)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_string_command_simple_rejected(self):
        """Test that simple string command format is rejected."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test_server", "command": "python -m server"}],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_string_command_with_quoted_paths_rejected(self):
        """Test that string command with quoted arguments is rejected."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": "python '/path with spaces/server.py'",
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_string_command_with_complex_quotes_rejected(self):
        """Test that string command with complex quoting is rejected."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test_server",
                        "command": "python -c 'print(\"hello world\")'",
                    }
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_string_command_empty_string(self):
        """Test that empty string command raises error."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test_server", "command": ""}],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_string_command_whitespace_only(self):
        """Test that whitespace-only string command raises error."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test_server", "command": "   "}],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_string_command_malformed_quotes(self):
        """Test that malformed quotes in string command raise error."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": "python 'unclosed quote"}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_array_command_continues_working(self):
        """Test that existing array format continues to work unchanged."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "-m", "server"]}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        config = self.loader.load_from_dict(config_dict)
        assert config.upstreams[0].command == ["python", "-m", "server"]

    def test_array_command_empty_array(self):
        """Test that empty array command raises error."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test_server", "command": []}],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_array_command_non_string_elements(self):
        """Test that array with non-string elements raises error."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", 123, "server"]}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_array_command_empty_string_element(self):
        """Test that array with empty string element is currently allowed (may be enhanced in future)."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": ["python", "", "server"]}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        # Current behavior: empty strings in command arrays are allowed
        # This may be enhanced in future to reject empty strings
        config = self.loader.load_from_dict(config_dict)
        assert config.upstreams[0].command == ["python", "", "server"]

    def test_command_invalid_type(self):
        """Test that invalid command type raises appropriate error."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [{"name": "test_server", "command": 123}],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)

    def test_string_command_with_environment_variables_rejected(self):
        """Test that string commands with environment variables are rejected."""
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {"name": "test_server", "command": "python $HOME/server.py"}
                ],
                "timeouts": {"connection_timeout": 30, "request_timeout": 60},
            }
        }

        with pytest.raises(ConfigError):
            self.loader.load_from_dict(config_dict)
