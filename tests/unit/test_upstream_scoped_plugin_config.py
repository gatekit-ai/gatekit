"""Unit tests for upstream-scoped plugin configuration (TDD - RED phase).

This test file contains failing tests that define the requirements for the new
upstream-scoped plugin configuration feature.
"""

import pytest
from pydantic import ValidationError

from gatekit.config.models import (
    PluginsConfigSchema,
    PluginsConfig,
    ProxyConfigSchema,
)


class TestUpstreamScopedPluginsConfigSchema:
    """Test upstream-scoped plugins configuration schema validation.

    These tests define the new dictionary-based configuration format where:
    - `_global` key contains policies for all upstreams (optional)
    - Individual upstream names are keys with their specific policies
    - Upstream-specific policies override global ones with same name
    """

    def test_dictionary_structure_with_global_and_upstream_specific(self):
        """Test dictionary structure with _global and upstream-specific policies.

        This test should FAIL initially because the current PluginsConfigSchema
        expects List[PluginConfigSchema] instead of Dict[str, List[PluginConfigSchema]].
        """
        # New dictionary-based format
        data = {
            "security": {
                "_global": [
                    {
                        "handler": "rate_limiting",
                        "config": {"enabled": True, "max_requests": 100},
                    }
                ],
                "github": [{"handler": "git_token_validation", "config": {"enabled": True}}],
                "file-system": [
                    {
                        "handler": "path_restrictions",
                        "config": {"enabled": True, "allowed_paths": ["/safe"]},
                    }
                ],
            },
            "auditing": {
                "_global": [{"handler": "request_logging", "config": {"enabled": True}}],
                "github": [{"handler": "git_operation_audit", "config": {"enabled": True}}],
            },
        }

        # This should work with the new schema
        schema = PluginsConfigSchema(**data)

        # Validate dictionary structure exists
        assert isinstance(schema.security, dict)
        assert isinstance(schema.auditing, dict)

        # Validate _global section
        assert "_global" in schema.security
        assert len(schema.security["_global"]) == 1
        assert schema.security["_global"][0].handler == "rate_limiting"

        # Validate upstream-specific sections
        assert "github" in schema.security
        assert len(schema.security["github"]) == 1
        assert schema.security["github"][0].handler == "git_token_validation"

        assert "file-system" in schema.security
        assert len(schema.security["file-system"]) == 1
        assert schema.security["file-system"][0].handler == "path_restrictions"

        # Validate auditing dictionary structure
        assert "_global" in schema.auditing
        assert "github" in schema.auditing

    def test_upstream_specific_only_no_global(self):
        """Test upstream-specific configuration without _global section.

        This test should FAIL initially because the current schema doesn't support
        dictionary format.
        """
        data = {
            "security": {
                "github": [
                    {"handler": "git_token_validation", "config": {"enabled": True}},
                    {
                        "handler": "rate_limiting",
                        "config": {"enabled": True, "max_requests": 50},
                    },
                ],
                "file-system": [
                    {
                        "handler": "path_restrictions",
                        "config": {"enabled": True, "allowed_paths": ["/safe"]},
                    },
                    {
                        "handler": "rate_limiting",
                        "config": {"enabled": True, "max_requests": 100},
                    },
                ],
            }
        }

        schema = PluginsConfigSchema(**data)

        # Should work without _global section
        assert isinstance(schema.security, dict)
        assert "_global" not in schema.security
        assert "github" in schema.security
        assert "file-system" in schema.security

        # Should have empty auditing dict by default
        assert isinstance(schema.auditing, dict)
        assert len(schema.auditing) == 0

    def test_empty_dictionary_configuration(self):
        """Test empty dictionary configuration is valid.

        This test should FAIL initially because the current schema expects lists.
        """
        data = {"security": {}, "auditing": {}}

        schema = PluginsConfigSchema(**data)

        assert isinstance(schema.security, dict)
        assert isinstance(schema.auditing, dict)
        assert len(schema.security) == 0
        assert len(schema.auditing) == 0

    def test_default_empty_dictionary_configuration(self):
        """Test default configuration creates empty dictionaries.

        This test should FAIL initially because current defaults are empty lists.
        """
        schema = PluginsConfigSchema()

        assert isinstance(schema.security, dict)
        assert isinstance(schema.auditing, dict)
        assert len(schema.security) == 0
        assert len(schema.auditing) == 0


class TestUpstreamKeyValidation:
    """Test validation rules for upstream keys in plugin configuration.

    These tests define validation requirements for upstream key naming and existence.
    """

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_valid_upstream_key_patterns(self):
        """Test valid upstream key naming patterns.

        This test should FAIL initially because upstream key validation doesn't exist.
        """
        valid_keys = [
            "github",
            "gitlab",
            "file-system",
            "docker_registry",
            "my-api",
            "test123",
            "api_v2",
            "server-name",
        ]

        for key in valid_keys:
            data = {"security": {key: [{"handler": "test_policy", "config": {"enabled": True}}]}}

            # Should validate successfully
            schema = PluginsConfigSchema(**data)
            assert key in schema.security

    def test_invalid_upstream_key_patterns(self):
        """Test invalid upstream key naming patterns.

        This test should FAIL initially because upstream key validation doesn't exist.
        """
        invalid_keys = [
            "GitHub",  # uppercase
            "git-Hub",  # mixed case
            "123server",  # starts with number
            "git hub",  # contains space
            "git@hub",  # contains special char
            "",  # empty string
            "server__name",  # double underscore
        ]

        for key in invalid_keys:
            data = {"security": {key: [{"handler": "test_policy", "config": {"enabled": True}}]}}

            with pytest.raises(ValidationError) as exc_info:
                PluginsConfigSchema(**data)

            error = str(exc_info.value)
            assert "upstream key" in error.lower() or "pattern" in error.lower()

    def test_global_key_is_reserved(self):
        """Test that _global is a reserved key that works correctly.

        This test should FAIL initially because _global key handling doesn't exist.
        """
        data = {
            "security": {"_global": [{"handler": "rate_limiting", "config": {"enabled": True}}]}
        }

        # Should work - _global is reserved and valid
        schema = PluginsConfigSchema(**data)
        assert "_global" in schema.security

    def test_ignored_underscore_keys(self):
        """Test that keys starting with _ (except _global) are ignored.

        This test should FAIL initially because ignored key handling doesn't exist.
        """
        data = {
            "security": {
                "_git_policies": [  # Should be ignored
                    {"handler": "git_token_validation", "config": {"enabled": True}}
                ],
                "_anchor_definition": [  # Should be ignored
                    {"handler": "test_policy", "config": {"enabled": True}}
                ],
                "github": [{"handler": "git_token_validation", "config": {"enabled": True}}],
            }
        }

        schema = PluginsConfigSchema(**data)

        # Ignored keys should not appear in validated result
        assert "_git_policies" not in schema.security
        assert "_anchor_definition" not in schema.security

        # Valid upstream keys should remain
        assert "github" in schema.security


class TestUpstreamExistenceValidation:
    """Test validation that upstream keys exist in the upstreams configuration.

    These tests define validation requirements for upstream existence checking.
    """

    def test_upstream_keys_must_exist_in_upstreams_config(self):
        """Test that plugin upstream keys must exist in upstreams configuration.

        This test should FAIL initially because upstream existence validation doesn't exist.
        """
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "github", "command": ["python", "-m", "github_server"]},
                {"name": "file-system", "command": ["python", "-m", "file_server"]},
            ],
            "plugins": {
                "security": {
                    "github": [{"handler": "git_token_validation", "config": {"enabled": True}}],
                    "nonexistent": [  # This upstream doesn't exist
                        {"handler": "test_policy", "config": {"enabled": True}}
                    ],
                }
            },
        }

        with pytest.raises(ValidationError) as exc_info:
            ProxyConfigSchema(**proxy_config)

        error = str(exc_info.value)
        assert "nonexistent" in error
        assert "upstream" in error.lower() or "server" in error.lower()

    def test_valid_upstream_references_pass_validation(self):
        """Test that valid upstream references pass validation.

        This test should FAIL initially because upstream validation doesn't exist
        in the new dictionary format.
        """
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "github", "command": ["python", "-m", "github_server"]},
                {"name": "file-system", "command": ["python", "-m", "file_server"]},
            ],
            "plugins": {
                "security": {
                    "_global": [{"handler": "rate_limiting", "config": {"enabled": True}}],
                    "github": [{"handler": "git_token_validation", "config": {"enabled": True}}],
                    "file-system": [{"handler": "path_restrictions", "config": {"enabled": True}}],
                }
            },
        }

        # Should validate successfully
        schema = ProxyConfigSchema(**proxy_config)

        assert isinstance(schema.plugins.security, dict)
        assert "github" in schema.plugins.security
        assert "file-system" in schema.plugins.security

    def test_global_key_does_not_require_upstream_existence(self):
        """Test that _global key does not require upstream existence.

        This test should FAIL initially because _global key handling doesn't exist.
        """
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "github", "command": ["python", "-m", "github_server"]}
            ],
            "plugins": {
                "security": {"_global": [{"handler": "rate_limiting", "config": {"enabled": True}}]}
            },
        }

        # Should validate successfully - _global doesn't need upstream existence
        schema = ProxyConfigSchema(**proxy_config)
        assert "_global" in schema.plugins.security


class TestUpstreamScopedPluginsConfig:
    """Test PluginsConfig dataclass with upstream-scoped configuration.

    These tests define the internal representation for upstream-scoped plugin configs.
    """

    def test_plugins_config_from_dictionary_schema(self):
        """Test conversion from dictionary schema to dataclass.

        This test should FAIL initially because PluginsConfig.from_schema()
        doesn't handle dictionary format.
        """
        schema = PluginsConfigSchema(
            **{
                "security": {
                    "_global": [
                        {
                            "handler": "rate_limiting",
                            "config": {"enabled": True, "max_requests": 100},
                        }
                    ],
                    "github": [{"handler": "git_token_validation", "config": {"enabled": True}}],
                }
            }
        )

        config = PluginsConfig.from_schema(schema)

        # Should create appropriate internal structure
        # (Implementation details to be determined during GREEN phase)
        assert hasattr(config, "security")
        assert hasattr(config, "auditing")

    def test_plugins_config_to_dict_with_upstream_scoping(self):
        """Test conversion from dataclass to dictionary representation.

        This test should FAIL initially because to_dict() doesn't handle
        upstream-scoped structure.
        """
        # Create config with upstream-scoped data
        # (Exact creation method to be determined during implementation)
        config = PluginsConfig()  # This will change during implementation

        result = config.to_dict()

        # Should return upstream-scoped dictionary structure
        assert isinstance(result, dict)
        assert "security" in result
        assert "auditing" in result


class TestYAMLAnchorSupport:
    """Test YAML anchor support with upstream-scoped configuration.

    These tests ensure YAML anchors work correctly with the new dictionary format.
    """

    def test_yaml_anchor_keys_are_ignored(self):
        """Test that keys starting with _ (except _global) are ignored for YAML anchors.

        This test should FAIL initially because ignored key handling doesn't exist.
        """
        data = {
            "security": {
                "_git_policies": [  # YAML anchor definition - should be ignored
                    {"handler": "git_token_validation", "config": {"enabled": True}}
                ],
                "_file_policies": [  # YAML anchor definition - should be ignored
                    {"handler": "path_restrictions", "config": {"enabled": True}}
                ],
                "github": [{"handler": "git_token_validation", "config": {"enabled": True}}],
                "gitlab": [{"handler": "git_token_validation", "config": {"enabled": True}}],
            }
        }

        schema = PluginsConfigSchema(**data)

        # Anchor definitions should be ignored
        assert "_git_policies" not in schema.security
        assert "_file_policies" not in schema.security

        # Actual upstream configurations should remain
        assert "github" in schema.security
        assert "gitlab" in schema.security


class TestBackwardCompatibility:
    """Test backward compatibility handling for old configuration format.

    These tests define how the new system should handle old configurations.
    Note: For v0.1.0, we're making a breaking change, so these tests define
    the expected behavior (which is to NOT support old format).
    """

    def test_old_list_format_backward_compatibility(self):
        """Test that old list format configurations are REJECTED for v0.1.0.

        For v0.1.0, we're making a breaking change - old list format should
        be rejected with clear validation errors (no backward compatibility).
        """
        # Old list-based format
        old_format_data = {
            "security": [{"handler": "rate_limiting", "config": {"enabled": True}}],
            "auditing": [{"handler": "request_logging", "config": {"enabled": True}}],
        }

        # Should FAIL with validation error for v0.1.0 breaking change
        with pytest.raises(ValidationError) as exc_info:
            PluginsConfigSchema(**old_format_data)

        # Should get clear error about expecting dictionary format
        error_message = str(exc_info.value)
        assert "Input should be a valid dictionary" in error_message


class TestComplexUpstreamScopedScenarios:
    """Test complex scenarios with multiple upstreams and plugin combinations.

    These tests define advanced use cases for upstream-scoped configuration.
    """

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_multiple_upstreams_with_global_and_specific_policies(self):
        """Test complex configuration with multiple upstreams.

        This test should FAIL initially due to lack of dictionary support.
        """
        proxy_config = {
            "transport": "stdio",
            "upstreams": [
                {"name": "github", "command": ["python", "-m", "github_server"]},
                {"name": "gitlab", "command": ["python", "-m", "gitlab_server"]},
                {"name": "file-system", "command": ["python", "-m", "file_server"]},
                {
                    "name": "docker-registry",
                    "command": ["python", "-m", "docker_server"],
                },
            ],
            "plugins": {
                "security": {
                    "_global": [
                        {
                            "handler": "rate_limiting",
                            "config": {"enabled": True, "max_requests": 100},
                        },
                        {"handler": "basic_secrets_filter", "config": {"enabled": True}},
                    ],
                    "github": [
                        {"handler": "github_token_validation", "config": {"enabled": True}},
                        {"handler": "repository_access_control", "config": {"enabled": True}},
                    ],
                    "gitlab": [
                        {"handler": "gitlab_token_validation", "config": {"enabled": True}},
                        {"handler": "repository_access_control", "config": {"enabled": True}},
                    ],
                    "file-system": [
                        {
                            "handler": "path_restrictions",
                            "config": {"enabled": True, "allowed_paths": ["/safe", "/public"]},
                        },
                        {"handler": "file_type_validation", "config": {"enabled": True}},
                    ],
                },
                "auditing": {
                    "_global": [{"handler": "request_logging", "config": {"enabled": True}}],
                    "github": [{"handler": "git_operation_audit", "config": {"enabled": True}}],
                    "file-system": [{"handler": "file_access_audit", "config": {"enabled": True}}],
                },
            },
        }

        schema = ProxyConfigSchema(**proxy_config)

        # Validate complex structure
        assert isinstance(schema.plugins.security, dict)
        assert isinstance(schema.plugins.auditing, dict)

        # Validate all upstreams are represented correctly
        assert "_global" in schema.plugins.security
        assert "github" in schema.plugins.security
        assert "gitlab" in schema.plugins.security
        assert "file-system" in schema.plugins.security

        # docker-registry should not be in security (only in upstreams)
        assert "docker-registry" not in schema.plugins.security

        # Validate policy counts
        assert len(schema.plugins.security["_global"]) == 2
        assert len(schema.plugins.security["github"]) == 2
        assert len(schema.plugins.security["file-system"]) == 2

    def test_empty_upstream_sections_are_valid(self):
        """Test that empty upstream sections are valid.

        This test should FAIL initially due to lack of dictionary support.
        """
        data = {
            "security": {
                "_global": [{"handler": "rate_limiting", "config": {"enabled": True}}],
                "github": [],  # Empty section should be valid
                "file-system": [{"handler": "path_restrictions", "config": {"enabled": True}}],
            }
        }

        schema = PluginsConfigSchema(**data)

        assert "github" in schema.security
        assert len(schema.security["github"]) == 0
        assert len(schema.security["file-system"]) == 1
