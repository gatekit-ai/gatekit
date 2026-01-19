"""Integration tests for policy-based plugin system."""

import tempfile
import pytest
from pathlib import Path

from gatekit.config import ConfigLoader
from gatekit.plugins.manager import PluginManager


class TestPolicyIntegration:
    """Test end-to-end integration of policy-based plugin system."""

    def setup_method(self):
        """Set up test fixtures."""
        self.loader = ConfigLoader()

    @pytest.mark.asyncio
    async def test_load_config_and_initialize_plugins(self, tmp_path):
        """Test loading policy-based configuration and initializing plugins."""
        audit_file = tmp_path / "test_audit.log"
        # Use forward slashes for YAML - backslashes are escape sequences in YAML
        audit_file_str = audit_file.as_posix()
        yaml_content = f"""
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["python", "-m", "test_server"]

plugins:
  middleware:
    test_server:
      - handler: "tool_manager"
        config:
          enabled: true
          tools:
            - tool: "read_file"
            - tool: "write_file"

  auditing:
    _global:
      - handler: "audit_jsonl"
        config:
          enabled: true
          output_file: "{audit_file_str}"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # Load configuration
            config = self.loader.load_from_file(Path(f.name))

            # Verify configuration loaded correctly
            assert config.plugins is not None
            assert len(config.plugins.middleware["test_server"]) == 1
            assert len(config.plugins.auditing["_global"]) == 1
            assert config.plugins.middleware["test_server"][0].handler == "tool_manager"
            assert config.plugins.auditing["_global"][0].handler == "audit_jsonl"

            # Convert to format expected by PluginManager (dictionary format)
            plugins_config = {
                "middleware": {
                    "test_server": [
                        plugin.to_dict()
                        for plugin in config.plugins.middleware["test_server"]
                    ]
                },
                "auditing": {
                    "_global": [
                        plugin.to_dict()
                        for plugin in config.plugins.auditing.get("_global", [])
                    ]
                },
            }

            # Initialize plugin manager with policy-based configuration
            manager = PluginManager(plugins_config)
            await manager.load_plugins()

            # Verify plugins were loaded successfully
            assert len(manager.upstream_middleware_plugins["test_server"]) == 1
            assert len(manager.auditing_plugins) == 1

            # Verify the loaded plugins are of the correct types
            middleware_plugin = manager.upstream_middleware_plugins["test_server"][0]
            auditing_plugin = manager.auditing_plugins[0]

            # Check class names instead of isinstance due to import path issues
            assert middleware_plugin.__class__.__name__ == "ToolManagerPlugin"
            assert auditing_plugin.__class__.__name__ == "JsonAuditingPlugin"

            # Verify plugin configuration was applied correctly
            assert middleware_plugin.policy == "allowlist"
            assert "read_file" in middleware_plugin.tools
            assert "write_file" in middleware_plugin.tools

            # Compare paths in a cross-platform way
            # Plugin may convert to native format, so normalize both paths
            assert Path(auditing_plugin.output_file) == Path(audit_file_str)

    @pytest.mark.asyncio
    async def test_policy_not_found_error_integration(self):
        """Test error handling when a policy is not found."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["python", "-m", "test_server"]
    
plugins:
  security:
    _global:
      - handler: "nonexistent_policy"
        config:
          enabled: true
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # ConfigLoader should now catch nonexistent policy during path validation
            from gatekit.config.errors import ConfigError

            with pytest.raises(ConfigError) as exc_info:
                self.loader.load_from_file(Path(f.name))

            error_msg = str(exc_info.value)
            assert "nonexistent_policy" in error_msg and "not found" in error_msg

    @pytest.mark.asyncio
    async def test_multiple_policies_same_category(self):
        """Test loading multiple policies from the same category."""
        yaml_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["python", "-m", "test_server"]
    
plugins:
  middleware:
    test_server:
      - handler: "tool_manager"
        config:
          enabled: true
          tools:
            - tool: "read_file"
      - handler: "tool_manager"  # Same policy, different config
        config:
          enabled: true
          tools:
            - tool: "delete_file"
  
  auditing:
    _global: []
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()

            # Load configuration
            config = self.loader.load_from_file(Path(f.name))

            # Convert to format expected by PluginManager (dictionary format)
            plugins_config = {
                "middleware": {
                    "test_server": [
                        plugin.to_dict()
                        for plugin in config.plugins.middleware["test_server"]
                    ]
                },
                "auditing": {
                    "_global": [
                        plugin.to_dict()
                        for plugin in config.plugins.auditing.get("_global", [])
                    ]
                },
            }

            # Initialize plugin manager
            manager = PluginManager(plugins_config)
            await manager.load_plugins()

            # Should have loaded two instances of the same policy class
            assert len(manager.upstream_middleware_plugins["test_server"]) == 2
            assert len(manager.auditing_plugins) == 0

            # Verify both instances have different configurations
            plugin1 = manager.upstream_middleware_plugins["test_server"][0]
            plugin2 = manager.upstream_middleware_plugins["test_server"][1]

            assert plugin1.policy == "allowlist"
            assert plugin2.policy == "allowlist"
            assert plugin1.tools == ["read_file"]
            assert plugin2.tools == ["delete_file"]
