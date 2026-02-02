"""Unit tests for configuration models."""

import pytest

from gatekit.config.models import (
    UpstreamConfig,
    UpstreamConfigSchema,
    TimeoutConfig,
    HttpConfig,
    ProxyConfig,
)


class TestUpstreamConfig:
    """Test UpstreamConfig dataclass creation and validation."""

    def test_minimal_config(self):
        """Test minimal upstream configuration."""
        upstream = UpstreamConfig(
            name="test", command=["python", "-m", "my_mcp_server"]
        )

        assert upstream.command == ["python", "-m", "my_mcp_server"]
        assert upstream.restart_on_failure is True
        assert upstream.max_restart_attempts == 3

    def test_full_config(self):
        """Test complete upstream configuration."""
        upstream = UpstreamConfig(
            name="test",
            command=["python", "-m", "my_mcp_server", "--config", "test.yaml"],
            restart_on_failure=False,
            max_restart_attempts=5,
        )

        assert upstream.command == [
            "python",
            "-m",
            "my_mcp_server",
            "--config",
            "test.yaml",
        ]
        assert upstream.restart_on_failure is False
        assert upstream.max_restart_attempts == 5

    def test_default_values(self):
        """Test default value assignment."""
        upstream = UpstreamConfig(name="test", command=["node", "server.js"])

        # Check defaults are applied correctly
        assert upstream.restart_on_failure is True
        assert upstream.max_restart_attempts == 3

    def test_empty_command_raises_error(self):
        """Test that empty command list raises appropriate error."""
        with pytest.raises(ValueError, match="stdio transport requires 'command'"):
            UpstreamConfig(name="test", command=[])

    def test_command_required_fields(self):
        """Test that all required fields are present."""
        upstream = UpstreamConfig(name="test", command=["python", "server.py"])

        # Should have all required fields
        assert hasattr(upstream, "command")
        assert hasattr(upstream, "restart_on_failure")
        assert hasattr(upstream, "max_restart_attempts")

    def test_create_draft_allows_missing_command(self):
        """Draft upstreams should bypass command validation until completed."""
        draft = UpstreamConfig.create_draft("draft-server")

        assert draft.is_draft is True
        assert draft.command is None
        assert draft.transport == "stdio"

    def test_server_identity_normalization(self):
        """Server identity should be normalized and stripped."""
        upstream = UpstreamConfig(
            name="test",
            command=["python", "-m", "my_mcp_server"],
            server_identity="  secure-filesystem-server  ",
        )

        assert upstream.server_identity == "secure-filesystem-server"

        draft = UpstreamConfig.create_draft(
            "draft-server", server_identity="  pending-identity  "
        )
        assert draft.server_identity == "pending-identity"


class TestUpstreamConfigHttpTransport:
    """Test UpstreamConfig HTTP transport configuration."""

    def test_http_transport_valid_config(self):
        """Valid HTTP transport configuration should be accepted."""
        upstream = UpstreamConfig(
            name="remote_api",
            transport="http",
            url="https://api.example.com/mcp",
        )

        assert upstream.transport == "http"
        assert upstream.url == "https://api.example.com/mcp"
        assert upstream.tls_verify is True

    def test_http_transport_requires_url(self):
        """HTTP transport without URL should raise error."""
        with pytest.raises(ValueError, match="http transport requires 'url'"):
            UpstreamConfig(
                name="remote_api",
                transport="http",
            )

    def test_http_transport_with_tls_disabled(self):
        """HTTP transport with TLS verification disabled should be accepted."""
        upstream = UpstreamConfig(
            name="remote_api",
            transport="http",
            url="https://localhost:8443/mcp",
            tls_verify=False,
        )

        assert upstream.tls_verify is False

    def test_stdio_transport_still_requires_command(self):
        """Stdio transport should still require command (regression)."""
        with pytest.raises(ValueError, match="stdio transport requires 'command'"):
            UpstreamConfig(
                name="local_server",
                transport="stdio",
            )


class TestUpstreamConfigSchemaHttpTransport:
    """Test UpstreamConfigSchema HTTP transport validation."""

    def test_schema_http_transport_valid(self):
        """Valid HTTP transport in schema should be accepted."""
        schema = UpstreamConfigSchema(
            name="remote_api",
            transport="http",
            url="https://api.example.com/mcp",
        )

        assert schema.transport == "http"
        assert str(schema.url) == "https://api.example.com/mcp"

    def test_schema_http_transport_requires_url(self):
        """HTTP transport in schema without URL should raise error."""
        with pytest.raises(ValueError, match="http transport requires 'url'"):
            UpstreamConfigSchema(
                name="remote_api",
                transport="http",
            )

    def test_schema_stdio_transport_requires_command(self):
        """Stdio transport in schema should require command."""
        with pytest.raises(ValueError, match="stdio transport requires 'command'"):
            UpstreamConfigSchema(
                name="local_server",
                transport="stdio",
            )

    def test_schema_from_schema_preserves_tls_config(self):
        """TLS config should be preserved when converting from schema."""
        schema = UpstreamConfigSchema(
            name="remote_api",
            transport="http",
            url="https://api.example.com/mcp",
            tls_verify=False,
        )

        upstream = UpstreamConfig.from_schema(schema)

        assert upstream.transport == "http"
        assert upstream.url == "https://api.example.com/mcp"
        assert upstream.tls_verify is False


class TestTimeoutConfig:
    """Test TimeoutConfig dataclass creation and validation."""

    def test_default_values(self):
        """Test default timeout values."""
        timeouts = TimeoutConfig()

        assert timeouts.connection_timeout == 60
        assert timeouts.request_timeout == 60

    def test_custom_values(self):
        """Test custom timeout values."""
        timeouts = TimeoutConfig(connection_timeout=45, request_timeout=120)

        assert timeouts.connection_timeout == 45
        assert timeouts.request_timeout == 120

    def test_negative_timeout_raises_error(self):
        """Test that negative timeout values raise appropriate error."""
        with pytest.raises(TypeError, match="Timeout values must be positive"):
            TimeoutConfig(connection_timeout=-1)

        with pytest.raises(TypeError, match="Timeout values must be positive"):
            TimeoutConfig(request_timeout=0)

    def test_timeout_required_fields(self):
        """Test that all required fields are present."""
        timeouts = TimeoutConfig()

        # Should have all required fields
        assert hasattr(timeouts, "connection_timeout")
        assert hasattr(timeouts, "request_timeout")


class TestHttpConfig:
    """Test HttpConfig dataclass creation and validation."""

    def test_default_values(self):
        """Test default HTTP configuration values."""
        http = HttpConfig()

        assert http.host == "127.0.0.1"
        assert http.port == 8080

    def test_custom_values(self):
        """Test custom HTTP configuration values."""
        http = HttpConfig(host="0.0.0.0", port=9090)

        assert http.host == "0.0.0.0"
        assert http.port == 9090

    def test_invalid_port_raises_error(self):
        """Test that invalid port values raise appropriate error."""
        with pytest.raises(TypeError, match="Port must be between 1 and 65535"):
            HttpConfig(port=0)

        with pytest.raises(TypeError, match="Port must be between 1 and 65535"):
            HttpConfig(port=65536)

    def test_http_required_fields(self):
        """Test that all required fields are present."""
        http = HttpConfig()

        # Should have all required fields
        assert hasattr(http, "host")
        assert hasattr(http, "port")


class TestProxyConfig:
    """Test ProxyConfig dataclass creation and validation."""

    def test_stdio_transport_config(self):
        """Test stdio transport configuration."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        proxy = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        assert proxy.transport == "stdio"
        assert proxy.upstreams[0] == upstream
        assert proxy.timeouts == timeouts
        assert proxy.http is None

    def test_http_transport_config(self):
        """Test HTTP transport configuration."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()
        http = HttpConfig(host="0.0.0.0", port=9090)

        proxy = ProxyConfig(
            transport="http", upstreams=[upstream], timeouts=timeouts, http=http
        )

        assert proxy.transport == "http"
        assert proxy.upstreams[0] == upstream
        assert proxy.timeouts == timeouts
        assert proxy.http == http

    def test_invalid_transport_type(self):
        """Test handling of invalid transport types."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        with pytest.raises(TypeError, match="Transport must be 'stdio' or 'http'"):
            ProxyConfig(transport="websocket", upstreams=[upstream], timeouts=timeouts)

    def test_http_transport_requires_http_config(self):
        """Test that HTTP transport requires HTTP configuration."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        with pytest.raises(
            ValueError, match="HTTP transport requires http configuration"
        ):
            ProxyConfig(
                transport="http", upstreams=[upstream], timeouts=timeouts, http=None
            )

    def test_stdio_transport_ignores_http_config(self):
        """Test that stdio transport can have HTTP config but ignores it."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()
        http = HttpConfig()

        # Should not raise error - stdio transport ignores http config
        proxy = ProxyConfig(
            transport="stdio", upstreams=[upstream], timeouts=timeouts, http=http
        )

        assert proxy.transport == "stdio"
        assert proxy.http == http  # Present but ignored for stdio

    def test_proxy_required_fields(self):
        """Test that all required fields are present."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        proxy = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        # Should have all required fields
        assert hasattr(proxy, "transport")
        assert hasattr(proxy, "upstreams")
        assert hasattr(proxy, "timeouts")
        assert hasattr(proxy, "http")

    def test_hot_reload_defaults_to_disabled(self):
        """Test that hot_reload defaults to 'disabled'."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        proxy = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        assert proxy.hot_reload == "disabled"

    def test_hot_reload_can_be_set_to_enabled(self):
        """Test that hot_reload can be set to 'enabled'."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        proxy = ProxyConfig(
            transport="stdio", upstreams=[upstream], timeouts=timeouts, hot_reload="enabled"
        )

        assert proxy.hot_reload == "enabled"

    def test_hot_reload_can_be_set_to_disabled(self):
        """Test that hot_reload can be set to 'disabled'."""
        upstream = UpstreamConfig(name="test", command=["python", "-m", "my_server"])
        timeouts = TimeoutConfig()

        proxy = ProxyConfig(
            transport="stdio", upstreams=[upstream], timeouts=timeouts, hot_reload="disabled"
        )

        assert proxy.hot_reload == "disabled"


class TestConfigModelIntegration:
    """Test integration scenarios with multiple configuration objects."""

    def test_complete_stdio_configuration(self):
        """Test complete stdio configuration creation."""
        upstream = UpstreamConfig(
            name="test",
            command=["python", "-m", "my_mcp_server"],
            restart_on_failure=True,
            max_restart_attempts=5,
        )

        timeouts = TimeoutConfig(connection_timeout=45, request_timeout=90)

        proxy = ProxyConfig(transport="stdio", upstreams=[upstream], timeouts=timeouts)

        # Verify all components are properly linked
        assert proxy.upstreams[0].command == ["python", "-m", "my_mcp_server"]
        assert proxy.timeouts.connection_timeout == 45
        assert proxy.timeouts.request_timeout == 90
        assert proxy.http is None

    def test_complete_http_configuration(self):
        """Test complete HTTP configuration creation."""
        upstream = UpstreamConfig(
            name="test", command=["node", "mcp-server.js", "--port", "3000"]
        )

        timeouts = TimeoutConfig(connection_timeout=60, request_timeout=120)

        http = HttpConfig(host="0.0.0.0", port=8888)

        proxy = ProxyConfig(
            transport="http", upstreams=[upstream], timeouts=timeouts, http=http
        )

        # Verify all components are properly linked
        assert proxy.upstreams[0].command == ["node", "mcp-server.js", "--port", "3000"]
        assert proxy.timeouts.connection_timeout == 60
        assert proxy.http.host == "0.0.0.0"
        assert proxy.http.port == 8888
