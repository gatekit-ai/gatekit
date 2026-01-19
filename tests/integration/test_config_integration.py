"""Integration tests for configuration management."""

import tempfile
import pytest
from pathlib import Path

from gatekit.config import ConfigLoader, ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.config.errors import ConfigError
from gatekit.transport import StdioTransport


class TestConfigIntegration:
    """Test integration scenarios with configuration and transport layers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_load_stdio_config_and_create_transport(self):
        """Test loading stdio configuration and using it to create transport."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["python", "-m", "test_server"]
      restart_on_failure: true
      max_restart_attempts: 3
  timeouts:
    connection_timeout: 30
    request_timeout: 60
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # Load configuration
            config = self.loader.load_from_file(Path(f.name))

            # Verify configuration loaded correctly
            assert config.transport == "stdio"
            assert config.upstreams[0].command == ["python", "-m", "test_server"]
            assert config.timeouts.connection_timeout == 30
            assert config.timeouts.request_timeout == 60
            assert config.http is None

            # Test integration with transport layer
            transport = StdioTransport(command=config.upstreams[0].command)

            # Verify transport was created with correct configuration
            assert transport.command == config.upstreams[0].command

    def test_load_http_config_validates_requirements(self):
        """Test that HTTP configuration validates all requirements."""
        yaml_content = """
proxy:
  transport: http
  upstreams:
    - name: "node_server"
      command: ["node", "server.js"]
  timeouts:
    connection_timeout: 45
    request_timeout: 90
  http:
    host: "0.0.0.0"
    port: 9090
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # Load configuration
            config = self.loader.load_from_file(Path(f.name))

            # Verify all components loaded correctly
            assert config.transport == "http"
            assert config.upstreams[0].command == ["node", "server.js"]
            assert config.timeouts.connection_timeout == 45
            assert config.timeouts.request_timeout == 90
            assert config.http is not None
            assert config.http.host == "0.0.0.0"
            assert config.http.port == 9090

    def test_end_to_end_minimal_configuration(self):
        """Test complete end-to-end loading of minimal configuration."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "simple_server"
      command: ["python", "-m", "simple_server"]
  timeouts:
    connection_timeout: 30
    request_timeout: 60
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # Load configuration
            config = self.loader.load_from_file(Path(f.name))

            # Verify configuration structure is complete
            assert isinstance(config, ProxyConfig)
            assert isinstance(config.upstreams[0], UpstreamConfig)
            assert isinstance(config.timeouts, TimeoutConfig)

            # Verify defaults were applied correctly
            assert config.upstreams[0].restart_on_failure is True
            assert config.upstreams[0].max_restart_attempts == 3

    def test_configuration_with_transport_layer_integration(self):
        """Test that configuration integrates properly with existing transport layer."""
        # Create configuration directly
        upstream = UpstreamConfig(
            name="test_upstream",
            command=["echo", "test"],
            restart_on_failure=True,
            max_restart_attempts=2,
        )

        timeouts = TimeoutConfig(connection_timeout=15, request_timeout=30)

        config = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        # Test that we can create transport from config
        transport = StdioTransport(command=config.upstreams[0].command)

        # Verify integration works
        assert transport.command == config.upstreams[0].command

    def test_configuration_error_handling_integration(self):
        """Test that configuration errors integrate with existing error handling."""
        # Test with invalid YAML that should trigger error handling
        invalid_yaml = """
proxy:
  transport: invalid_transport_type
  upstreams:
    - name: "invalid_server"
      command: []  # Empty command should trigger validation error
  timeouts:
    connection_timeout: -1  # Invalid negative timeout
    request_timeout: 60
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_yaml)
            f.flush()

            # Should raise validation errors from the configuration models
            from gatekit.config.errors import ConfigError

            with pytest.raises(ConfigError):
                self.loader.load_from_file(Path(f.name))

    def test_configuration_without_timeouts_section(self):
        """Test that configuration without timeouts section uses defaults."""
        # Create configuration without timeouts section
        config_content = """
# Gatekit MCP Gateway Configuration
proxy:
  transport: stdio
  upstreams:
    - name: "my_mcp_server"
      command: ["python", "-m", "my_mcp_server"]
      restart_on_failure: true
      max_restart_attempts: 3
# No timeouts section - should use defaults
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            f.flush()

            # Test file loading
            config = self.loader.load_from_file(Path(f.name))

            # Verify defaults are applied
            assert config.transport == "stdio"
            assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]
            assert config.timeouts.connection_timeout == 60
            assert config.timeouts.request_timeout == 60

            # Verify we can create transport with default timeouts
            transport = StdioTransport(command=config.upstreams[0].command)
            assert transport is not None


class TestConfigFileSystemIntegration:
    """Test configuration integration with file system operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_real_yaml_file_loading(self):
        """Test loading actual YAML files from the file system."""
        # Create a realistic configuration file
        config_content = """
# Gatekit MCP Gateway Configuration
proxy:
  # Transport type: stdio or http
  transport: stdio
  # Upstream server configuration
  upstreams:
    - name: "my_mcp_server"
      command: ["python", "-m", "my_mcp_server", "--verbose"]
      restart_on_failure: true
      max_restart_attempts: 5
  # Timeout configuration
  timeouts:
    connection_timeout: 30  # seconds
    request_timeout: 120    # seconds
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            f.flush()

            # Test file loading
            config = self.loader.load_from_file(Path(f.name))

            # Verify complete configuration
            assert config.transport == "stdio"
            assert config.upstreams[0].command == [
                "python",
                "-m",
                "my_mcp_server",
                "--verbose",
            ]
            assert config.upstreams[0].restart_on_failure is True
            assert config.upstreams[0].max_restart_attempts == 5
            assert config.timeouts.connection_timeout == 30
            assert config.timeouts.request_timeout == 120

    def test_configuration_with_multiple_file_formats(self):
        """Test configuration loading with different YAML formatting styles."""
        # Test compact YAML format
        compact_yaml = """
proxy: {transport: stdio, upstreams: [{name: "python_server", command: ["python", "server.py"]}], timeouts: {connection_timeout: 30, request_timeout: 60}}
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(compact_yaml)
            f.flush()

            config = self.loader.load_from_file(Path(f.name))

            assert config.transport == "stdio"
            assert config.upstreams[0].command == ["python", "server.py"]
            assert config.timeouts.connection_timeout == 30
            assert config.timeouts.request_timeout == 60

    def test_configuration_file_permissions_and_errors(self):
        """Test configuration loading with file system errors."""
        # Test non-existent file
        non_existent = Path("/tmp/non_existent_config_file.yaml")

        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            self.loader.load_from_file(non_existent)

    def test_configuration_without_timeouts_section(self):
        """Test that configuration without timeouts section uses defaults."""
        # Create configuration without timeouts section
        config_content = """
# Gatekit MCP Gateway Configuration
proxy:
  transport: stdio
  upstreams:
    - name: "my_mcp_server"
      command: ["python", "-m", "my_mcp_server"]
      restart_on_failure: true
      max_restart_attempts: 3
# No timeouts section - should use defaults
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            f.flush()

            # Test file loading
            config = self.loader.load_from_file(Path(f.name))

            # Verify defaults are applied
            assert config.transport == "stdio"
            assert config.upstreams[0].command == ["python", "-m", "my_mcp_server"]
            assert config.timeouts.connection_timeout == 60
            assert config.timeouts.request_timeout == 60

            # Verify we can create transport with default timeouts
            transport = StdioTransport(command=config.upstreams[0].command)
            assert transport is not None


class TestCommandFormatIntegration:
    """Test command argument handling for stdio transports."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    def test_string_command_format_rejected(self):
        """String command format should now raise a validation error."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: "python -m test_server"
  timeouts:
    connection_timeout: 30
    request_timeout: 60
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            with pytest.raises(ConfigError) as exc_info:
                self.loader.load_from_file(Path(f.name))

            # Ensure validation failed on upstream command parsing
            assert exc_info.value.field_path is not None
            assert exc_info.value.field_path.startswith("upstreams")

    def test_list_command_format_integration(self):
        """List command format continues to work with transport."""
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

            # Load configuration with array command
            config = self.loader.load_from_file(Path(f.name))

            # Verify command remains as array
            assert config.upstreams[0].command == ["python", "-m", "test_server"]

            # Verify transport can be created with array command
            transport = StdioTransport(command=config.upstreams[0].command)
            assert transport is not None

    def test_list_command_with_spaces_preserves_arguments(self):
        """List command format handles arguments containing spaces."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "spaced_server"
      command: ["python", "/path with spaces/server.py", "--config", "/another path/config.json"]
  timeouts:
    connection_timeout: 30
    request_timeout: 60
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            config = self.loader.load_from_file(Path(f.name))

            expected_command = [
                "python",
                "/path with spaces/server.py",
                "--config",
                "/another path/config.json",
            ]
            assert config.upstreams[0].command == expected_command

            transport = StdioTransport(command=config.upstreams[0].command)
            assert transport is not None
