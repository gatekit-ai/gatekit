"""Unit tests for sandbox configuration models and serialization."""

import pytest

from gatekit.config.models import (
    SandboxConfig,
    SandboxConfigSchema,
    UpstreamConfig,
    UpstreamConfigSchema,
)
from gatekit.config.serialization import config_to_dict
from gatekit.config.models import ProxyConfig, TimeoutConfig


class TestSandboxConfigSchema:
    """Test SandboxConfigSchema Pydantic validation."""

    def test_defaults(self):
        schema = SandboxConfigSchema()
        assert schema.enabled is False
        assert schema.paths is None
        assert schema.network is True

    def test_enabled(self):
        schema = SandboxConfigSchema(enabled=True)
        assert schema.enabled is True

    def test_paths(self):
        schema = SandboxConfigSchema(
            enabled=True,
            paths=["~/docs", "/data"],
        )
        assert schema.paths == ["~/docs", "/data"]

    def test_network_deny(self):
        schema = SandboxConfigSchema(enabled=True, network=False)
        assert schema.network is False

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            SandboxConfigSchema(enabled=True, unknown_field="bad")

    def test_glob_star_rejected(self):
        with pytest.raises(Exception, match="glob"):
            SandboxConfigSchema(enabled=True, paths=["~/projects/*"])

    def test_glob_question_mark_rejected(self):
        with pytest.raises(Exception, match="glob"):
            SandboxConfigSchema(enabled=True, paths=["/data/dir?"])

    def test_glob_brackets_rejected(self):
        with pytest.raises(Exception, match="glob"):
            SandboxConfigSchema(enabled=True, paths=["/data/[abc]"])

    def test_glob_braces_rejected(self):
        with pytest.raises(Exception, match="glob"):
            SandboxConfigSchema(enabled=True, paths=["/data/{a,b}"])

    def test_normal_paths_accepted(self):
        schema = SandboxConfigSchema(
            enabled=True,
            paths=["~/docs", "/data/workspace", "/tmp"],
        )
        assert schema.paths == ["~/docs", "/data/workspace", "/tmp"]


class TestSandboxConfig:
    """Test SandboxConfig dataclass."""

    def test_defaults(self):
        cfg = SandboxConfig()
        assert cfg.enabled is False
        assert cfg.paths == []
        assert cfg.network is True

    def test_from_schema_none(self):
        assert SandboxConfig.from_schema(None) is None

    def test_from_schema_enabled(self):
        schema = SandboxConfigSchema(
            enabled=True,
            paths=["~/docs"],
            network=False,
        )
        cfg = SandboxConfig.from_schema(schema)
        assert cfg is not None
        assert cfg.enabled is True
        assert cfg.paths == ["~/docs"]
        assert cfg.network is False

    def test_from_schema_empty_paths(self):
        schema = SandboxConfigSchema(enabled=True)
        cfg = SandboxConfig.from_schema(schema)
        assert cfg.paths == []

    def test_from_schema_resolves_relative_paths_against_config_dir(self, tmp_path):
        """Relative paths should be resolved against config_directory."""
        schema = SandboxConfigSchema(
            enabled=True,
            paths=["data/workspace", "~/docs"],
        )
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        cfg = SandboxConfig.from_schema(schema, config_directory=config_dir)
        assert cfg is not None
        # Relative path should be resolved against config_dir
        assert str(config_dir / "data" / "workspace") in cfg.paths[0]
        # ~ path should be expanded to home dir
        assert "~" not in cfg.paths[1]

    def test_from_schema_absolute_paths_unchanged(self, tmp_path):
        """Absolute paths should remain absolute regardless of config_directory."""
        schema = SandboxConfigSchema(
            enabled=True,
            paths=["/data/workspace"],
        )
        cfg = SandboxConfig.from_schema(schema, config_directory=tmp_path)
        assert cfg.paths == ["/data/workspace"]

    def test_from_schema_no_config_dir_keeps_paths_as_is(self):
        """Without config_directory, paths should be kept as-is."""
        schema = SandboxConfigSchema(
            enabled=True,
            paths=["relative/path"],
        )
        cfg = SandboxConfig.from_schema(schema)
        assert cfg.paths == ["relative/path"]


class TestUpstreamConfigWithSandbox:
    """Test UpstreamConfig includes sandbox field."""

    def test_default_no_sandbox(self):
        upstream = UpstreamConfig(name="test", command=["echo", "hello"])
        assert upstream.sandbox is None

    def test_sandbox_roundtrip_schema(self):
        schema = UpstreamConfigSchema(
            name="test",
            command=["npx", "server", "/tmp"],
            sandbox=SandboxConfigSchema(enabled=True, network=False),
        )
        upstream = UpstreamConfig.from_schema(schema)
        assert upstream.sandbox is not None
        assert upstream.sandbox.enabled is True
        assert upstream.sandbox.network is False

    def test_sandbox_in_draft(self):
        sbx = SandboxConfig(enabled=True, paths=["~/data"])
        draft = UpstreamConfig.create_draft("my-server", sandbox=sbx)
        assert draft.sandbox is not None
        assert draft.sandbox.enabled is True
        assert draft.sandbox.paths == ["~/data"]


class TestSandboxHttpValidationWarning:
    """Test that sandbox on HTTP upstreams emits a warning."""

    def test_sandbox_on_http_upstream_warns(self):
        """Sandbox enabled on HTTP transport should emit UserWarning."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            UpstreamConfigSchema(
                name="test-http",
                transport="http",
                url="https://example.com/mcp",
                sandbox=SandboxConfigSchema(enabled=True),
            )
            # Should have emitted a warning
            sandbox_warnings = [x for x in w if "sandbox" in str(x.message).lower()]
            assert len(sandbox_warnings) == 1
            assert "only applies to stdio" in str(sandbox_warnings[0].message)

    def test_sandbox_on_stdio_upstream_no_warning(self):
        """Sandbox enabled on stdio transport should NOT emit a warning."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            UpstreamConfigSchema(
                name="test-stdio",
                transport="stdio",
                command=["echo", "test"],
                sandbox=SandboxConfigSchema(enabled=True),
            )
            sandbox_warnings = [x for x in w if "sandbox" in str(x.message).lower()]
            assert len(sandbox_warnings) == 0

    def test_disabled_sandbox_on_http_no_warning(self):
        """Disabled sandbox on HTTP transport should NOT emit a warning."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            UpstreamConfigSchema(
                name="test-http",
                transport="http",
                url="https://example.com/mcp",
                sandbox=SandboxConfigSchema(enabled=False),
            )
            sandbox_warnings = [x for x in w if "sandbox" in str(x.message).lower()]
            assert len(sandbox_warnings) == 0


class TestSandboxSerialization:
    """Test config_to_dict handles sandbox correctly."""

    def _make_proxy(self, upstream: UpstreamConfig) -> ProxyConfig:
        """Helper to wrap an upstream in a minimal ProxyConfig."""
        return ProxyConfig(
            transport="stdio",
            upstreams=[upstream],
            timeouts=TimeoutConfig(),
        )

    def test_sandbox_omitted_when_disabled(self):
        upstream = UpstreamConfig(name="test", command=["echo", "hi"])
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        upstream_dict = result["proxy"]["upstreams"][0]
        assert "sandbox" not in upstream_dict

    def test_sandbox_omitted_when_none(self):
        upstream = UpstreamConfig(name="test", command=["echo", "hi"], sandbox=None)
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        upstream_dict = result["proxy"]["upstreams"][0]
        assert "sandbox" not in upstream_dict

    def test_sandbox_omitted_when_default_disabled(self):
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(enabled=False),
        )
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        upstream_dict = result["proxy"]["upstreams"][0]
        assert "sandbox" not in upstream_dict

    def test_sandbox_minimal_enabled(self):
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(enabled=True),
        )
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        sandbox_dict = result["proxy"]["upstreams"][0]["sandbox"]
        assert sandbox_dict == {"enabled": True}

    def test_sandbox_with_paths(self):
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(
                enabled=True,
                paths=["~/docs", "/data"],
            ),
        )
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        sandbox_dict = result["proxy"]["upstreams"][0]["sandbox"]
        assert sandbox_dict["enabled"] is True
        assert sandbox_dict["paths"] == ["~/docs", "/data"]
        # network defaults to True, so should be omitted
        assert "network" not in sandbox_dict

    def test_sandbox_with_network_denied(self):
        upstream = UpstreamConfig(
            name="test",
            command=["echo", "hi"],
            sandbox=SandboxConfig(enabled=True, network=False),
        )
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        sandbox_dict = result["proxy"]["upstreams"][0]["sandbox"]
        assert sandbox_dict["network"] is False

    def test_sandbox_full_roundtrip(self):
        """Verify schema -> dataclass -> dict preserves all fields."""
        schema = UpstreamConfigSchema(
            name="fs",
            command=["npx", "@modelcontextprotocol/server-filesystem", "/tmp"],
            sandbox=SandboxConfigSchema(
                enabled=True,
                paths=["~/docs"],
                network=False,
            ),
        )
        upstream = UpstreamConfig.from_schema(schema)
        proxy = self._make_proxy(upstream)
        result = config_to_dict(proxy)
        sandbox_dict = result["proxy"]["upstreams"][0]["sandbox"]
        assert sandbox_dict == {
            "enabled": True,
            "paths": ["~/docs"],
            "network": False,
        }
