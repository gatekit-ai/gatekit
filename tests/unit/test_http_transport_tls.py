"""Unit tests for TLS support in StreamableHttpTransport.

Tests TLS verification and disabling verification.
"""

import ssl
from unittest.mock import patch

import httpx
import pytest
import respx

from gatekit.transport.http import StreamableHttpTransport
from gatekit.transport.errors import HttpConnectionError


# Test URLs
TEST_HTTPS_URL = "https://localhost:8443/mcp"
TEST_HTTP_URL = "http://localhost:8123/mcp"


class TestDefaultHttpsWithSystemCA:
    """Tests for default HTTPS with system CA verification."""

    @pytest.mark.asyncio
    async def test_default_https_uses_system_ca(self, respx_mock: respx.MockRouter):
        """tls_verify=True (default) uses system CA bundle."""
        # Mock SSE endpoint
        respx_mock.get(TEST_HTTPS_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        transport = StreamableHttpTransport(url=TEST_HTTPS_URL)

        # Verify default tls_verify is True
        assert transport._tls_verify is True

        await transport.connect()

        try:
            # Client should be created with verify=True
            assert transport._client is not None
            # In httpx, verify=True uses the system CA bundle
        finally:
            await transport.disconnect()


class TestDisableVerification:
    """Tests for disabling TLS verification."""

    @pytest.mark.asyncio
    async def test_disable_verification(
        self, respx_mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
    ):
        """tls_verify=False creates client with verify=False and logs warning."""
        import logging

        caplog.set_level(logging.WARNING)

        # Mock SSE endpoint
        respx_mock.get(TEST_HTTPS_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        transport = StreamableHttpTransport(url=TEST_HTTPS_URL, tls_verify=False)

        assert transport._tls_verify is False

        await transport.connect()

        try:
            assert transport._client is not None
            # Should log a warning about insecurity
            warning_found = any(
                "TLS verification disabled" in record.message
                or "insecure" in record.message.lower()
                for record in caplog.records
            )
            assert warning_found, (
                "Expected warning about TLS verification disabled. "
                f"Log records: {[r.message for r in caplog.records]}"
            )
        finally:
            await transport.disconnect()


class TestTlsVerifyTypeValidation:
    """Tests for tls_verify parameter type validation."""

    def test_non_boolean_tls_verify_raises_type_error(self):
        """tls_verify must be boolean, not a string path."""
        with pytest.raises(TypeError) as exc_info:
            StreamableHttpTransport(
                url=TEST_HTTPS_URL,
                tls_verify="/path/to/ca.crt",  # type: ignore
            )

        error_msg = str(exc_info.value)
        assert "must be a boolean" in error_msg
        assert "Custom CA certificate paths are not supported" in error_msg

    def test_integer_tls_verify_raises_type_error(self):
        """tls_verify doesn't accept integer values."""
        with pytest.raises(TypeError) as exc_info:
            StreamableHttpTransport(
                url=TEST_HTTPS_URL,
                tls_verify=1,  # type: ignore
            )

        assert "must be a boolean" in str(exc_info.value)

    def test_none_tls_verify_raises_type_error(self):
        """tls_verify doesn't accept None."""
        with pytest.raises(TypeError) as exc_info:
            StreamableHttpTransport(
                url=TEST_HTTPS_URL,
                tls_verify=None,  # type: ignore
            )

        assert "must be a boolean" in str(exc_info.value)


class TestCertificateVerificationFailures:
    """Tests for certificate verification failure handling."""

    @pytest.mark.asyncio
    async def test_certificate_verification_failure(self):
        """SSLError from httpx is wrapped in HttpConnectionError with clear message."""
        transport = StreamableHttpTransport(url=TEST_HTTPS_URL)

        # Mock httpx.AsyncClient constructor to raise an SSL error
        ssl_error = ssl.SSLError(1, "certificate verify failed: unable to get local issuer certificate")

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.side_effect = ssl_error

            with pytest.raises(HttpConnectionError) as exc_info:
                await transport.connect()

            error_msg = str(exc_info.value).lower()
            # The error should mention TLS/SSL/certificate
            assert any(term in error_msg for term in ["ssl", "tls", "certificate", "verify"])

    @pytest.mark.asyncio
    async def test_hostname_mismatch(self):
        """Hostname mismatch error has clear message."""
        transport = StreamableHttpTransport(url=TEST_HTTPS_URL)

        # Simulate hostname mismatch SSL error during client creation
        ssl_error = ssl.SSLCertVerificationError(
            1, "hostname 'localhost' doesn't match 'example.com'"
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.side_effect = ssl_error

            with pytest.raises(HttpConnectionError) as exc_info:
                await transport.connect()

            error_msg = str(exc_info.value).lower()
            # Should mention hostname or certificate verification
            assert any(term in error_msg for term in ["hostname", "mismatch", "ssl", "tls", "certificate", "verify"])


class TestTLSConfigurationIntegration:
    """Integration tests for TLS configuration."""

    @pytest.mark.asyncio
    async def test_http_url_ignores_tls_settings(self, respx_mock: respx.MockRouter):
        """HTTP URLs work regardless of TLS settings (no TLS used)."""
        # Mock SSE endpoint for HTTP
        respx_mock.get(TEST_HTTP_URL).mock(
            return_value=httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=b"",
            )
        )

        # TLS settings provided but URL is HTTP
        transport = StreamableHttpTransport(
            url=TEST_HTTP_URL,
            tls_verify=False,  # This shouldn't matter for HTTP
        )

        await transport.connect()

        try:
            assert transport.is_connected()
        finally:
            await transport.disconnect()
