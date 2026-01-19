"""Test that server-aware plugins cannot be configured in _global section."""

import pytest
from gatekit.config.models import ProxyConfigSchema
from gatekit.config.loader import ConfigLoader
from pydantic import ValidationError
import tempfile
from pathlib import Path


class TestServerAwarePluginValidation:
    """Test that server-aware plugins are properly validated."""

    def test_server_aware_plugin_rejected_in_global(self):
        """Server-aware plugins like tool_manager should not be allowed in _global."""
        config_dict = {
            "transport": "stdio",
            "upstreams": [{"name": "filesystem", "command": ["npx", "test"]}],
            "plugins": {
                "middleware": {
                    "_global": [
                        {
                            "handler": "tool_manager",
                            "config": {"enabled": True, "tools": [{"tool": "read_file"}]},
                        }
                    ]
                }
            },
        }

        # Should raise validation error
        with pytest.raises(ValidationError) as exc_info:
            ProxyConfigSchema(**config_dict)

        error_msg = str(exc_info.value)
        assert "server_aware" in error_msg
        assert "cannot be configured in the _global section" in error_msg
        assert "tool_manager" in error_msg

    def test_server_aware_plugin_allowed_in_server_section(self):
        """Server-aware plugins should be allowed in specific server sections."""
        config_dict = {
            "transport": "stdio",
            "upstreams": [{"name": "filesystem", "command": ["npx", "test"]}],
            "plugins": {
                "middleware": {
                    "filesystem": [  # Server-specific, not _global
                        {
                            "handler": "tool_manager",
                            "config": {"enabled": True, "tools": [{"tool": "read_file"}]},
                        }
                    ]
                }
            },
        }

        # Should NOT raise validation error
        schema = ProxyConfigSchema(**config_dict)
        assert schema.plugins is not None
        assert "filesystem" in schema.plugins.middleware

    def test_global_plugin_allowed_in_global(self):
        """Global plugins like PII filter should be allowed in _global."""
        config_dict = {
            "transport": "stdio",
            "upstreams": [{"name": "filesystem", "command": ["npx", "test"]}],
            "plugins": {
                "security": {
                    "_global": [
                        {
                            "handler": "basic_pii_filter",
                            "config": {"enabled": True,
                                "action": "redact",
                                "pii_types": {"email": {"enabled": True}},
                            },
                        }
                    ]
                }
            },
        }

        # Should NOT raise validation error
        schema = ProxyConfigSchema(**config_dict)
        assert schema.plugins is not None
        assert "_global" in schema.plugins.security

    def test_config_loader_validates_server_aware_plugins(self):
        """Test that ConfigLoader properly validates server-aware plugins."""
        config_yaml = """
proxy:
  transport: stdio
  upstreams:
    - name: filesystem
      command: ["npx", "test"]

plugins:
  middleware:
    _global:
      - handler: tool_manager
        config:
          enabled: true
          tools:
            - tool: read_file
"""

        # Create temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_yaml)
            temp_path = Path(f.name)

        try:
            loader = ConfigLoader()

            # Should raise error about server_aware plugin in _global
            with pytest.raises(Exception) as exc_info:
                loader.load_from_file(temp_path)

            error_msg = str(exc_info.value)
            assert "server_aware" in error_msg
            assert "tool_manager" in error_msg

        finally:
            # Clean up temp file
            temp_path.unlink()

    def test_middleware_discovery_works(self):
        """Test that middleware plugins are discovered for validation."""
        from gatekit.config.models import ProxyConfigSchema

        # Create a schema instance to test the discovery method
        schema = ProxyConfigSchema(
            transport="stdio", upstreams=[{"name": "test", "command": ["test"]}]
        )

        # Test that middleware plugins can be discovered
        plugin_class = schema._discover_plugin_class("tool_manager", "middleware")

        assert (
            plugin_class is not None
        ), "tool_manager should be discoverable in middleware"
        assert hasattr(
            plugin_class, "DISPLAY_SCOPE"
        ), "Plugin should have DISPLAY_SCOPE"
        assert (
            plugin_class.DISPLAY_SCOPE == "server_aware"
        ), "tool_manager should be server_aware"
