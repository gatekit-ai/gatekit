"""Tests that enforce dictionary-only plugin configuration format.

This test file ensures that:
1. List format is completely rejected (no conversion)
2. Dictionary format works correctly
3. Clear error messages are provided for invalid formats
"""

import pytest
from pydantic import ValidationError

from gatekit.config.models import PluginsConfigSchema, PluginsConfig


class TestDictionaryOnlyConfiguration:
    """Test that plugin configuration only accepts dictionary format."""

    def test_list_format_rejected_for_security(self):
        """🔴 RED: List format should be rejected for security plugins."""
        # This should FAIL because we still have list-to-dict conversion
        with pytest.raises(ValidationError) as exc_info:
            PluginsConfigSchema(
                security=[{"handler": "tool_allowlist", "config": {"enabled": True}}]
            )

        # Ensure it's not silently converted to dictionary format
        error_message = str(exc_info.value)
        assert "list" in error_message.lower() or "dict" in error_message.lower()

    def test_list_format_rejected_for_auditing(self):
        """🔴 RED: List format should be rejected for auditing plugins."""
        # This should FAIL because we still have list-to-dict conversion
        with pytest.raises(ValidationError) as exc_info:
            PluginsConfigSchema(
                auditing=[{"handler": "file_auditing", "config": {"enabled": True}}]
            )

        # Ensure it's not silently converted to dictionary format
        error_message = str(exc_info.value)
        assert "list" in error_message.lower() or "dict" in error_message.lower()

    def test_dictionary_format_works_correctly(self):
        """Dictionary format with _global key should work correctly."""
        config = PluginsConfigSchema(
            security={"_global": [{"handler": "tool_allowlist", "config": {"enabled": True}}]},
            auditing={"_global": [{"handler": "file_auditing", "config": {"enabled": True}}]},
        )

        assert config.security["_global"][0].handler == "tool_allowlist"
        assert config.auditing["_global"][0].handler == "file_auditing"

    def test_empty_config_is_valid(self):
        """Empty plugin configuration should be valid."""
        config = PluginsConfigSchema()
        assert config.security == {}
        assert config.auditing == {}

    def test_upstream_specific_configuration(self):
        """Upstream-specific configuration should work."""
        config = PluginsConfigSchema(
            security={
                "_global": [{"handler": "rate_limiting", "config": {"enabled": True}}],
                "filesystem": [{"handler": "path_restrictions", "config": {"enabled": True}}],
            }
        )

        assert config.security["_global"][0].handler == "rate_limiting"
        assert config.security["filesystem"][0].handler == "path_restrictions"

    def test_plugins_config_internal_class_rejects_lists(self):
        """🔴 RED: Internal PluginsConfig class should fail with list format."""
        # This should FAIL because the to_dict() method calls .items() on lists
        # We need to create PluginConfig objects first
        from gatekit.config.models import PluginConfig

        plugins_config = PluginsConfig(
            security=[  # This should cause AttributeError when to_dict() is called
                PluginConfig(handler="tool_allowlist", config={"enabled": True})
            ]
        )

        with pytest.raises(AttributeError) as exc_info:
            plugins_config.to_dict()

        assert "'list' object has no attribute 'items'" in str(exc_info.value)

    def test_clear_error_message_for_invalid_format(self):
        """Error messages should clearly indicate dictionary format is required."""
        with pytest.raises(ValidationError) as exc_info:
            PluginsConfigSchema(security="invalid_string")

        error_message = str(exc_info.value)
        # Should mention dictionary or proper format
        assert any(
            word in error_message.lower()
            for word in ["dict", "object", "format", "invalid"]
        )


class TestUpstreamKeyValidation:
    """Test upstream key validation rules."""

    def test_valid_upstream_keys(self):
        """Valid upstream keys should be accepted."""
        valid_keys = ["filesystem", "github", "web_server", "data-store", "my_service"]

        for key in valid_keys:
            config = PluginsConfigSchema(
                security={key: [{"handler": "test", "config": {"enabled": True}}]}
            )
            assert key in config.security

    def test_invalid_upstream_keys_rejected(self):
        """Invalid upstream keys should be rejected."""
        invalid_keys = ["UPPERCASE", "space key", "key__with__double", "123numeric", ""]

        for key in invalid_keys:
            with pytest.raises(ValidationError) as exc_info:
                PluginsConfigSchema(
                    security={key: [{"handler": "test", "config": {"enabled": True}}]}
                )

            error_message = str(exc_info.value)
            assert "Invalid upstream key" in error_message or "pattern" in error_message

    def test_global_key_is_always_valid(self):
        """The _global key should always be valid."""
        config = PluginsConfigSchema(
            security={"_global": [{"handler": "test", "config": {"enabled": True}}]}
        )
        assert "_global" in config.security

    def test_ignored_keys_are_filtered_out(self):
        """Keys starting with _ (except _global) should be filtered out."""
        config = PluginsConfigSchema(
            security={
                "_global": [{"handler": "test", "config": {"enabled": True}}],
                "_yaml_anchor": [{"handler": "ignored", "config": {"enabled": True}}],
                "_template": [{"handler": "ignored", "config": {"enabled": True}}],
            }
        )

        # Only _global should remain, other _ keys should be filtered
        assert "_global" in config.security
        assert "_yaml_anchor" not in config.security
        assert "_template" not in config.security
