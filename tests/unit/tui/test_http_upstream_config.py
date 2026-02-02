"""Tests for HTTP upstream configuration support in the TUI.

These tests verify that HTTP-based MCP servers can be configured in the TUI
with the same level of support as stdio-based servers:
1. URL input with persistence handlers
2. Transport selection (not disabled)
3. TLS configuration fields serialization
4. Connection testing for HTTP transport
5. HTTP handshake support
6. HTTP connection error handling
"""

import json
import pytest
import httpx
import respx
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from gatekit.config.models import ProxyConfig, TimeoutConfig, UpstreamConfig
from gatekit.config.serialization import config_to_dict
from gatekit.tui.screens.config_editor import ConfigEditorScreen


class TestConfigSerializationTlsFields:
    """Tests for TLS field serialization in config_to_dict."""

    def test_http_upstream_with_default_tls_omits_tls_fields(self):
        """HTTP upstream with default TLS settings should not include TLS fields."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp",
                    # Default TLS settings: tls_verify=True, no client certs
                )
            ],
            timeouts=TimeoutConfig(),
        )

        result = config_to_dict(config)
        upstream_dict = result["proxy"]["upstreams"][0]

        assert upstream_dict["name"] == "http-server"
        assert upstream_dict["transport"] == "http"
        assert upstream_dict["url"] == "https://example.com/mcp"
        # Default TLS settings should be omitted
        assert "tls_verify" not in upstream_dict

    def test_http_upstream_with_disabled_tls_includes_tls_verify(self):
        """HTTP upstream with tls_verify=False should include tls_verify field."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="http://localhost:8080/mcp",
                    tls_verify=False,
                )
            ],
            timeouts=TimeoutConfig(),
        )

        result = config_to_dict(config)
        upstream_dict = result["proxy"]["upstreams"][0]

        assert upstream_dict["tls_verify"] is False

    def test_stdio_upstream_does_not_include_tls_fields(self):
        """Stdio upstream should never include TLS fields even if set."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="stdio-server",
                    transport="stdio",
                    command=["npx", "server"],
                    # TLS fields shouldn't matter for stdio
                    tls_verify=False,
                )
            ],
            timeouts=TimeoutConfig(),
        )

        result = config_to_dict(config)
        upstream_dict = result["proxy"]["upstreams"][0]

        # TLS fields should not appear for stdio transport
        assert "tls_verify" not in upstream_dict


class TestConnectionTestingHttpSupport:
    """Tests for connection testing availability for HTTP transport."""

    def test_http_transport_connection_test_not_blocked(self):
        """HTTP transport should allow connection testing (not return block reason)."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp",
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        upstream = config.upstreams[0]

        # Should NOT return a block reason for HTTP with URL set
        block_reason = screen._get_test_connection_block_reason(upstream)
        assert block_reason is None

    def test_http_transport_without_url_blocks_connection_test(self):
        """HTTP transport without URL should block connection testing."""
        # Create a draft HTTP upstream without URL
        upstream = UpstreamConfig.create_draft("http-server", transport="http")

        config = ProxyConfig(
            transport="stdio",
            upstreams=[upstream],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        block_reason = screen._get_test_connection_block_reason(upstream)
        assert block_reason is not None
        assert "URL" in block_reason or "url" in block_reason.lower()


class TestHttpHandshakeSupport:
    """Tests for HTTP transport support in handshake utility."""

    @pytest.mark.asyncio
    async def test_handshake_upstream_accepts_url_parameter(self):
        """handshake_upstream should accept url parameter for HTTP transport."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        # Mock the HTTP transport to avoid actual network calls
        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_transport_class:
            mock_transport = AsyncMock()
            mock_transport.connect = AsyncMock()
            mock_transport.disconnect = AsyncMock()
            mock_transport.send_and_receive = AsyncMock(return_value=MagicMock(
                result={"serverInfo": {"name": "test-http-server"}}
            ))
            mock_transport.send_notification = AsyncMock()
            mock_transport_class.return_value = mock_transport

            # Should accept url parameter
            identity, tools = await handshake_upstream(
                url="https://example.com/mcp",
                timeout=5.0,
            )

            assert identity == "test-http-server"
            mock_transport_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_handshake_upstream_with_tls_options(self):
        """handshake_upstream should pass TLS options to HTTP transport."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_transport_class:
            mock_transport = AsyncMock()
            mock_transport.connect = AsyncMock()
            mock_transport.disconnect = AsyncMock()
            mock_transport.send_and_receive = AsyncMock(return_value=MagicMock(
                result={"serverInfo": {"name": "test-http-server"}}
            ))
            mock_transport.send_notification = AsyncMock()
            mock_transport_class.return_value = mock_transport

            await handshake_upstream(
                url="https://example.com/mcp",
                tls_verify=False,
            )

            # Verify TLS options were passed to transport constructor
            mock_transport_class.assert_called_once_with(
                url="https://example.com/mcp",
                tls_verify=False,
            )

    @pytest.mark.asyncio
    async def test_handshake_upstream_requires_command_or_url(self):
        """handshake_upstream should raise ValueError if neither command nor url provided."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        with pytest.raises(ValueError, match="command.*url|url.*command"):
            await handshake_upstream()


class TestTransportAutoDetection:
    """Tests for auto-detection of transport type from input."""

    def test_url_input_auto_detects_http_transport(self):
        """Entering a URL should auto-detect HTTP transport."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig.create_draft("new-server")
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "new-server"

        # Enter a URL in the command input
        screen._commit_connection_input("https://example.com/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://example.com/mcp"
        assert upstream.command is None
        assert upstream.is_draft is False

    def test_url_input_auto_detects_http_with_http_scheme(self):
        """HTTP URLs (not just HTTPS) should be detected."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig.create_draft("new-server")
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "new-server"

        screen._commit_connection_input("http://localhost:8080/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "http://localhost:8080/mcp"

    def test_command_input_keeps_stdio_transport(self):
        """Entering a command should keep stdio transport."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig.create_draft("new-server")
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "new-server"

        screen._commit_connection_input("npx @modelcontextprotocol/server-everything")

        upstream = config.upstreams[0]
        assert upstream.transport == "stdio"
        assert upstream.command == ["npx", "@modelcontextprotocol/server-everything"]
        assert upstream.url is None
        assert upstream.is_draft is False

    def test_switching_from_http_to_stdio_clears_url(self):
        """Changing from URL to command should clear URL and set command."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp"
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "http-server"

        # Change to a command
        screen._commit_connection_input("npx server")

        upstream = config.upstreams[0]
        assert upstream.transport == "stdio"
        assert upstream.command == ["npx", "server"]
        assert upstream.url is None

    def test_switching_from_stdio_to_http_clears_command(self):
        """Changing from command to URL should clear command and set URL."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="stdio-server",
                    transport="stdio",
                    command=["npx", "server"]
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "stdio-server"

        # Change to a URL
        screen._commit_connection_input("https://example.com/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://example.com/mcp"
        assert upstream.command is None


class TestTlsFieldPersistence:
    """Tests for TLS configuration field persistence."""

    def test_tls_verify_false_persisted(self):
        """Setting tls_verify to false should update upstream."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp",
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "http-server"

        screen._commit_tls_verify_input("false")

        upstream = config.upstreams[0]
        assert upstream.tls_verify is False

    def test_tls_verify_true_is_default(self):
        """Setting tls_verify to true or empty should set True (default)."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp",
                    tls_verify=False,  # Start with non-default
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "http-server"

        screen._commit_tls_verify_input("true")

        upstream = config.upstreams[0]
        assert upstream.tls_verify is True

class TestTlsErrorDetection:
    """Tests for TLS error detection and 'connect anyway' functionality."""

    def test_tls_error_detected_from_certificate_message(self):
        """Messages containing 'certificate' should be detected as TLS errors."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp",
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        assert screen._is_tls_error("TLS certificate verification failed")
        assert screen._is_tls_error("SSL handshake failed")
        assert screen._is_tls_error("Certificate expired")
        assert screen._is_tls_error("unable to verify the first certificate")

    def test_non_tls_errors_not_detected(self):
        """Regular connection errors should not be detected as TLS errors."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="http-server",
                    transport="http",
                    url="https://example.com/mcp",
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)

        assert not screen._is_tls_error("Connection refused")
        assert not screen._is_tls_error("Timeout after 30s")
        assert not screen._is_tls_error("Server did not report an identity")
        assert not screen._is_tls_error("")
        assert not screen._is_tls_error(None)


class TestTransportAutoDetectionEdgeCases:
    """Stress tests for transport auto-detection edge cases."""

    def test_command_starting_with_http_is_not_url(self):
        """Command like 'http-server' should NOT be detected as HTTP URL."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # 'http-server' is a common npm package, not a URL
        screen._commit_connection_input("http-server ./public")

        upstream = config.upstreams[0]
        assert upstream.transport == "stdio"
        assert upstream.command == ["http-server", "./public"]
        assert upstream.url is None

    def test_https_prefix_without_host_is_url(self):
        """'https://' alone is detected as URL (connection will fail, which is appropriate)."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # Scheme prefix triggers URL detection (Firefox-style heuristic)
        screen._commit_connection_input("https://")

        upstream = config.upstreams[0]
        # Detected as URL - connection will fail with clear error
        assert upstream.transport == "http"
        assert upstream.url == "https://"
        assert upstream.command is None

    def test_localhost_without_scheme_is_url(self):
        """'localhost:8080/mcp' without scheme is detected as URL and normalized with https://."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # localhost without scheme is detected as URL (like browsers do)
        # and normalized with https:// prefix
        screen._commit_connection_input("localhost:8080/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://localhost:8080/mcp"
        assert upstream.command is None

    def test_domain_without_scheme_is_url(self):
        """'hf.co/mcp' without scheme is detected as URL and normalized with https://."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # Domain with path but no scheme - should be detected as URL and normalized
        screen._commit_connection_input("hf.co/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://hf.co/mcp"
        assert upstream.command is None

    def test_url_with_port_is_valid(self):
        """URL with explicit port should be valid HTTP."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        screen._commit_connection_input("https://localhost:8443/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://localhost:8443/mcp"

    def test_url_with_query_string_is_valid(self):
        """URL with query string should be valid HTTP."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        screen._commit_connection_input("https://api.example.com/mcp?token=abc123")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://api.example.com/mcp?token=abc123"

    def test_http_url_case_insensitive(self):
        """URL detection should be case-insensitive for scheme."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        screen._commit_connection_input("HTTPS://Example.Com/MCP")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        # URL should be preserved with original case
        assert upstream.url == "HTTPS://Example.Com/MCP"

    def test_url_with_leading_whitespace(self):
        """URL with leading/trailing whitespace should be trimmed and detected."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        screen._commit_connection_input("  https://example.com/mcp  ")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        assert upstream.url == "https://example.com/mcp"

    def test_file_url_is_not_http(self):
        """file:// URLs should NOT be treated as HTTP transport."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # file:// URLs are not HTTP
        screen._commit_connection_input("file:///path/to/something")

        upstream = config.upstreams[0]
        assert upstream.transport == "stdio"
        assert upstream.command == ["file:///path/to/something"]
        assert upstream.url is None


class TestTransportSwitchStateManagement:
    """Tests for state management when switching between transports."""

    def test_switch_http_to_stdio_preserves_tls_settings(self):
        """TLS settings should be preserved when switching from HTTP to stdio.

        This allows users to switch back to HTTP without losing their TLS config.
        """
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test-server",
                    transport="http",
                    url="https://example.com/mcp",
                    tls_verify=False,
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # Switch to stdio
        screen._commit_connection_input("npx some-server")

        upstream = config.upstreams[0]
        assert upstream.transport == "stdio"
        # TLS settings should still be on the model (just not serialized for stdio)
        assert upstream.tls_verify is False

    def test_switch_stdio_to_http_gets_default_tls(self):
        """Switching from stdio to HTTP should use default TLS settings."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="test-server",
                    transport="stdio",
                    command=["npx", "some-server"],
                )
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        # Switch to HTTP
        screen._commit_connection_input("https://example.com/mcp")

        upstream = config.upstreams[0]
        assert upstream.transport == "http"
        # Should have default TLS settings
        assert upstream.tls_verify is True

    def test_multiple_transport_switches_preserve_data(self):
        """Multiple switches between transports should preserve the last config."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig.create_draft("test-server")],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "test-server"

        upstream = config.upstreams[0]

        # Start with URL
        screen._commit_connection_input("https://example.com/mcp")
        assert upstream.transport == "http"
        assert upstream.url == "https://example.com/mcp"

        # Switch to command
        screen._commit_connection_input("npx server-a")
        assert upstream.transport == "stdio"
        assert upstream.command == ["npx", "server-a"]
        assert upstream.url is None

        # Switch back to URL (different URL)
        screen._commit_connection_input("https://other.com/mcp")
        assert upstream.transport == "http"
        assert upstream.url == "https://other.com/mcp"
        assert upstream.command is None


class TestConfigRoundTrip:
    """Tests for config serialization and deserialization round-trips."""

    def test_http_with_disabled_tls_round_trip(self):
        """HTTP with TLS disabled should serialize correctly."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig(
                    name="insecure-server",
                    transport="http",
                    url="https://example.com/mcp",
                    tls_verify=False,
                )
            ],
            timeouts=TimeoutConfig(),
        )

        result = config_to_dict(config)
        upstream_dict = result["proxy"]["upstreams"][0]

        assert upstream_dict["tls_verify"] is False


class TestUrlInputPersistence:
    """Tests for URL input field persistence in server management (legacy tests)."""

    def test_url_input_commit_updates_upstream(self):
        """Committing URL input should update the upstream config."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig.create_draft("http-server", transport="http")
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "http-server"

        # Simulate connection input commit with URL (auto-detected)
        screen._commit_connection_input("https://example.com/mcp")

        upstream = config.upstreams[0]
        assert upstream.url == "https://example.com/mcp"
        assert upstream.transport == "http"
        assert upstream.is_draft is False  # Should no longer be draft

    def test_connection_input_non_url_becomes_command(self):
        """Non-URL input should be treated as a command and switch to stdio."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig.create_draft("http-server", transport="http")
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "http-server"

        # Simulate non-URL input - should be treated as command and switch to stdio
        screen._commit_connection_input("npx some-server")

        upstream = config.upstreams[0]
        # Should now be stdio transport with command
        assert upstream.transport == "stdio"
        assert upstream.command == ["npx", "some-server"]
        assert upstream.url is None
        assert upstream.is_draft is False

    def test_connection_input_empty_keeps_draft(self):
        """Committing empty connection input should keep upstream as draft."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[
                UpstreamConfig.create_draft("http-server", transport="http")
            ],
            timeouts=TimeoutConfig(),
        )

        screen = ConfigEditorScreen(Path("test.yaml"), config)
        screen.selected_server = "http-server"

        # Simulate empty connection input commit
        screen._commit_connection_input("")

        upstream = config.upstreams[0]
        assert upstream.url is None
        assert upstream.is_draft is True


class TestHttpConnectionErrorHandling:
    """Tests for HTTP connection error handling in handshake.

    These tests verify that the handshake utility properly handles
    various HTTP error conditions and returns appropriate error messages.
    """

    TEST_URL = "http://localhost:8123/mcp"

    def _create_http_transport_mock(self, **overrides):
        """Create a mock transport without stdio-specific methods.

        HTTP transport doesn't have get_stderr_output, so we use spec
        to prevent auto-creation of that method.
        """
        mock_transport = MagicMock()
        mock_transport.connect = AsyncMock()
        mock_transport.disconnect = AsyncMock()
        mock_transport.send_and_receive = AsyncMock()
        mock_transport.send_notification = AsyncMock()
        # Explicitly remove get_stderr_output (HTTP doesn't have it)
        if hasattr(mock_transport, "get_stderr_output"):
            del mock_transport.get_stderr_output
        for key, value in overrides.items():
            setattr(mock_transport, key, value)
        return mock_transport

    @pytest.mark.asyncio
    async def test_handshake_handles_connection_refused(self):
        """Connection refused should return error status with message."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            mock_transport = self._create_http_transport_mock(
                connect=AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url=self.TEST_URL)

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "Connection refused" in tools["message"]

    @pytest.mark.asyncio
    async def test_handshake_handles_dns_resolution_failure(self):
        """DNS resolution failure should return error status."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            mock_transport = self._create_http_transport_mock(
                connect=AsyncMock(side_effect=httpx.ConnectError("Name or service not known"))
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url="https://nonexistent.invalid/mcp")

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "not known" in tools["message"].lower() or "Name" in tools["message"]

    @pytest.mark.asyncio
    async def test_handshake_handles_http_404_error(self):
        """HTTP 404 response should return error status."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream
        from gatekit.transport.errors import HttpRequestError

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            mock_transport = self._create_http_transport_mock(
                send_and_receive=AsyncMock(
                    side_effect=HttpRequestError("Not Found", status_code=404)
                )
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url=self.TEST_URL)

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "404" in tools["message"] or "Not Found" in tools["message"]

    @pytest.mark.asyncio
    async def test_handshake_handles_http_500_error(self):
        """HTTP 500 response should return error status."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream
        from gatekit.transport.errors import HttpRequestError

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            mock_transport = self._create_http_transport_mock(
                send_and_receive=AsyncMock(
                    side_effect=HttpRequestError("Internal Server Error", status_code=500)
                )
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url=self.TEST_URL)

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "500" in tools["message"] or "Internal Server Error" in tools["message"]

    @pytest.mark.asyncio
    async def test_handshake_handles_invalid_json_response(self):
        """Invalid JSON response should return error status."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream
        from gatekit.transport.errors import TransportProtocolError

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            mock_transport = self._create_http_transport_mock(
                send_and_receive=AsyncMock(
                    side_effect=TransportProtocolError("Invalid JSON: <html>Not MCP</html>")
                )
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url=self.TEST_URL)

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "Invalid JSON" in tools["message"] or "Not MCP" in tools["message"]

    @pytest.mark.asyncio
    async def test_handshake_handles_timeout(self):
        """Timeout should return error status with timeout message."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream
        import asyncio

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            # Simulate timeout during send_and_receive
            async def slow_response(*args, **kwargs):
                await asyncio.sleep(100)  # Will be cancelled by timeout

            mock_transport = self._create_http_transport_mock(
                send_and_receive=slow_response
            )
            mock_cls.return_value = mock_transport

            # Use very short timeout
            identity, tools = await handshake_upstream(url=self.TEST_URL, timeout=0.01)

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "timeout" in tools["message"].lower() or "Timeout" in tools["message"]

    @pytest.mark.asyncio
    async def test_handshake_handles_ssl_certificate_error(self):
        """SSL certificate error should return error status."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream
        import ssl

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            ssl_error = ssl.SSLCertVerificationError(
                1, "certificate verify failed: unable to get local issuer certificate"
            )
            mock_transport = self._create_http_transport_mock(
                connect=AsyncMock(side_effect=ssl_error)
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url="https://self-signed.example.com/mcp")

            assert identity is None
            assert tools is not None
            assert tools["status"] == "error"
            assert "certificate" in tools["message"].lower()

    @pytest.mark.asyncio
    async def test_handshake_handles_server_identity_missing(self):
        """Server response without identity should return None identity."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            # Response without serverInfo
            mock_response = MagicMock()
            mock_response.result = {"capabilities": {}}

            mock_transport = self._create_http_transport_mock(
                send_and_receive=AsyncMock(return_value=mock_response)
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url=self.TEST_URL)

            # Identity should be None when serverInfo is missing
            assert identity is None

    @pytest.mark.asyncio
    async def test_handshake_handles_empty_response(self):
        """Empty/null response should return None."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        with patch("gatekit.tui.utils.mcp_handshake.StreamableHttpTransport") as mock_cls:
            mock_transport = self._create_http_transport_mock(
                send_and_receive=AsyncMock(return_value=None)
            )
            mock_cls.return_value = mock_transport

            identity, tools = await handshake_upstream(url=self.TEST_URL)

            assert identity is None


class TestHttpConnectionErrorsWithRespx:
    """Integration tests using respx to simulate real HTTP error responses."""

    TEST_URL = "http://localhost:8123/mcp"

    @pytest.mark.asyncio
    async def test_real_http_404_response(self, respx_mock: respx.MockRouter):
        """Test handling of actual HTTP 404 response."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        # Mock SSE endpoint (GET) to return 404
        respx_mock.get(self.TEST_URL).mock(
            return_value=httpx.Response(404, content=b"Not Found")
        )

        identity, tools = await handshake_upstream(url=self.TEST_URL, timeout=5.0)

        assert identity is None
        assert tools is not None
        assert tools["status"] == "error"

    @pytest.mark.asyncio
    async def test_real_http_500_response(self, respx_mock: respx.MockRouter):
        """Test handling of actual HTTP 500 response."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        # Mock SSE endpoint to return 500
        respx_mock.get(self.TEST_URL).mock(
            return_value=httpx.Response(500, content=b"Internal Server Error")
        )

        identity, tools = await handshake_upstream(url=self.TEST_URL, timeout=5.0)

        assert identity is None
        assert tools is not None
        assert tools["status"] == "error"

    @pytest.mark.asyncio
    async def test_non_mcp_html_response(self, respx_mock: respx.MockRouter):
        """Test handling of HTML response instead of MCP."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        # Mock SSE endpoint with HTML response
        respx_mock.get(self.TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                content=b"<html><body>Welcome to our website</body></html>",
            )
        )

        identity, tools = await handshake_upstream(url=self.TEST_URL, timeout=5.0)

        assert identity is None
        # Should get error or empty response
        assert tools is None or tools.get("status") in ("error", "empty")

    @pytest.mark.asyncio
    async def test_successful_mcp_handshake(self, respx_mock: respx.MockRouter):
        """Test successful MCP handshake via HTTP for completeness."""
        from gatekit.tui.utils.mcp_handshake import handshake_upstream

        # Mock SSE endpoint
        respx_mock.get(self.TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # Mock POST for initialize request
        init_response = json.dumps({
            "jsonrpc": "2.0",
            "id": "gatekit-handshake",
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "serverInfo": {"name": "test-mcp-server", "version": "1.0.0"}
            }
        })
        respx_mock.post(self.TEST_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=init_response.encode(),
            )
        )

        identity, tools = await handshake_upstream(url=self.TEST_URL, timeout=5.0)

        assert identity == "test-mcp-server"
        assert tools is not None
