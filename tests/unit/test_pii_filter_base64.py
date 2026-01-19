"""Tests for BasicPIIFilterPlugin scan_base64 functionality.

These tests verify the scan_base64 configuration option behavior.

The scan_base64 option controls base64 decoding and scanning:
- scan_base64: false (default) - Skip base64-looking strings to avoid
  corrupting binary data during redaction
- scan_base64: true - Decode base64 strings and scan decoded content for PII
  (with DoS protection: candidate limits, size limits, data URL skipping)
"""

import base64

import pytest

from gatekit.plugins.security.pii import BasicPIIFilterPlugin
from gatekit.protocol.messages import MCPRequest


class TestPIIFilterBase64Configuration:
    """Test scan_base64 configuration option."""

    def test_scan_base64_defaults_to_false(self):
        """Test that scan_base64 defaults to False (skip base64 content)."""
        config = {
            "action": "redact",
            "pii_types": {"email": {"enabled": True}},
        }
        plugin = BasicPIIFilterPlugin(config)
        assert plugin.scan_base64 is False

    def test_scan_base64_can_be_enabled(self):
        """Test that scan_base64 can be explicitly enabled."""
        config = {
            "action": "redact",
            "pii_types": {"email": {"enabled": True}},
            "scan_base64": True,
        }
        plugin = BasicPIIFilterPlugin(config)
        assert plugin.scan_base64 is True

    def test_scan_base64_can_be_explicitly_disabled(self):
        """Test that scan_base64 can be explicitly disabled."""
        config = {
            "action": "redact",
            "pii_types": {"email": {"enabled": True}},
            "scan_base64": False,
        }
        plugin = BasicPIIFilterPlugin(config)
        assert plugin.scan_base64 is False


class TestPIIFilterBase64Disabled:
    """Test behavior when scan_base64 is disabled (default)."""

    @pytest.fixture
    def plugin(self):
        """Create plugin with base64 scanning disabled (default)."""
        return BasicPIIFilterPlugin({
            "action": "block",
            "pii_types": {
                "email": {"enabled": True},
                "national_id": {"enabled": True},
                "phone": {"enabled": True},
                "credit_card": {"enabled": True},
            },
            "scan_base64": False,
        })

    @pytest.mark.asyncio
    async def test_plaintext_pii_still_detected(self, plugin):
        """Test that plaintext PII is detected normally when base64 scanning is disabled."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-plaintext",
            params={"name": "test", "arguments": {"data": "Contact: test@example.com"}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False  # block mode
        assert result.metadata.get("pii_detected") is True

    @pytest.mark.asyncio
    async def test_base64_encoded_pii_not_detected(self, plugin):
        """Test that base64-encoded PII is NOT detected when scan_base64 is False.

        This is the primary use case for scan_base64: false - when a tool
        returns base64-encoded binary data (like images), we don't want to
        falsely detect patterns or corrupt the data during redaction.
        """
        # Base64-encoded email: "john.smith@company.com"
        encoded_email = "am9obi5zbWl0aEBjb21wYW55LmNvbQ=="

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-encoded",
            params={"name": "test", "arguments": {"data": encoded_email}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be ALLOWED because base64 is skipped (not decoded)
        assert result.allowed is True
        assert result.metadata.get("pii_detected") is False

    @pytest.mark.asyncio
    async def test_binary_data_preserved(self, plugin):
        """Test that base64 binary data (like images) is preserved intact."""
        # Simulate base64-encoded binary data (like a PNG image header)
        binary_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-binary",
            params={"name": "test", "arguments": {"image": binary_b64}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be allowed (no PII detected since base64 is skipped)
        assert result.allowed is True


class TestPIIFilterBase64Enabled:
    """Test behavior when scan_base64 is enabled."""

    @pytest.fixture
    def plugin_block(self):
        """Create plugin with base64 scanning enabled (block mode)."""
        return BasicPIIFilterPlugin({
            "action": "block",
            "pii_types": {
                "email": {"enabled": True},
                "national_id": {"enabled": True},
                "phone": {"enabled": True},
                "credit_card": {"enabled": True},
            },
            "scan_base64": True,
        })

    @pytest.fixture
    def plugin_redact(self):
        """Create plugin with base64 scanning enabled (redact mode)."""
        return BasicPIIFilterPlugin({
            "action": "redact",
            "pii_types": {
                "email": {"enabled": True},
                "national_id": {"enabled": True},
                "phone": {"enabled": True},
                "credit_card": {"enabled": True},
            },
            "scan_base64": True,
        })

    @pytest.mark.asyncio
    async def test_base64_encoded_email_detected(self, plugin_block):
        """Test detection of base64-encoded email."""
        # Base64-encoded email: "john.smith@company.com"
        encoded_email = "am9obi5zbWl0aEBjb21wYW55LmNvbQ=="

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-email",
            params={"name": "test", "arguments": {"data": encoded_email}},
        )

        result = await plugin_block.process_request(request, "test-server")
        # Should be BLOCKED because base64 is decoded and email is detected
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True

        # Verify detection includes encoding metadata
        detections = result.metadata.get("detections", [])
        assert len(detections) > 0
        assert detections[0].get("encoding") == "base64"
        assert detections[0].get("type") == "EMAIL"

    @pytest.mark.asyncio
    async def test_base64_encoded_ssn_detected(self, plugin_block):
        """Test detection of base64-encoded SSN."""
        # Base64-encoded SSN: "123-45-6789"
        encoded_ssn = base64.b64encode(b"123-45-6789").decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-ssn",
            params={"name": "test", "arguments": {"data": encoded_ssn}},
        )

        result = await plugin_block.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True

        # Verify encoding metadata
        detections = result.metadata.get("detections", [])
        assert len(detections) > 0
        assert detections[0].get("encoding") == "base64"
        assert detections[0].get("type") == "NATIONAL_ID"

    @pytest.mark.asyncio
    async def test_base64_encoded_phone_detected(self, plugin_block):
        """Test detection of base64-encoded phone number."""
        # Base64-encoded phone: "(555) 123-4567"
        encoded_phone = base64.b64encode(b"(555) 123-4567").decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-phone",
            params={"name": "test", "arguments": {"data": encoded_phone}},
        )

        result = await plugin_block.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True

        # Verify encoding metadata
        detections = result.metadata.get("detections", [])
        assert len(detections) > 0
        assert detections[0].get("encoding") == "base64"
        assert detections[0].get("type") == "PHONE"

    @pytest.mark.asyncio
    async def test_base64_encoded_credit_card_detected(self, plugin_block):
        """Test detection of base64-encoded credit card."""
        # Base64-encoded credit card: "4532 0151 1283 0366" (Luhn valid)
        encoded_cc = base64.b64encode(b"4532 0151 1283 0366").decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-cc",
            params={"name": "test", "arguments": {"data": encoded_cc}},
        )

        result = await plugin_block.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True

        # Verify encoding metadata
        detections = result.metadata.get("detections", [])
        assert len(detections) > 0
        assert detections[0].get("encoding") == "base64"
        assert detections[0].get("type") == "CREDIT_CARD"

    @pytest.mark.asyncio
    async def test_mixed_content_with_inline_base64(self, plugin_block):
        """Test detection in mixed content with inline base64 (from test data)."""
        # From base64-encoded.txt: "The user's email is stored as am9obi5zbWl0aEBjb21wYW55LmNvbQ== in the database."
        mixed_content = "The user's email is stored as am9obi5zbWl0aEBjb21wYW55LmNvbQ== in the database."

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-mixed",
            params={"name": "test", "arguments": {"data": mixed_content}},
        )

        result = await plugin_block.process_request(request, "test-server")
        # Should detect the base64-encoded email
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True

    @pytest.mark.asyncio
    async def test_redact_mode_forces_block_for_base64_encoded_pii(self, plugin_redact):
        """Test that base64-encoded PII forces blocking even in redact mode.

        Base64 content cannot be redacted without corrupting the binary data,
        so the plugin must block instead. See ADR-025.
        """
        # Base64-encoded email: "secret@hidden.com"
        email = "secret@hidden.com"
        encoded_email = base64.b64encode(email.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-redact",
            params={"name": "test", "arguments": {"data": encoded_email}},
        )

        result = await plugin_redact.process_request(request, "test-server")
        # Should be BLOCKED because base64 content cannot be redacted
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True
        assert result.metadata.get("base64_force_block") is True
        assert "base64" in result.reason.lower()


class TestPIIFilterBase64DataUrls:
    """Test data URL handling with scan_base64 setting."""

    @pytest.fixture
    def plugin(self):
        """Create plugin with base64 scanning disabled."""
        return BasicPIIFilterPlugin({
            "action": "block",
            "pii_types": {"email": {"enabled": True}},
            "scan_base64": False,
        })

    def test_data_urls_not_skipped(self, plugin):
        """Test that data URLs are not skipped even when scan_base64 is False.

        Data URLs get special handling - they should not be skipped just
        because they look like base64.
        """
        data_url = "data:text/plain;base64,SGVsbG8gV29ybGQ="
        # Data URLs should NOT be skipped
        assert plugin._should_skip_base64_content(data_url) is False

    @pytest.mark.asyncio
    async def test_data_url_with_clean_content(self, plugin):
        """Test that data URLs without PII are allowed."""
        data_url = "data:text/plain;base64,SGVsbG8gV29ybGQ="  # "Hello World"

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-data-url",
            params={"name": "test", "arguments": {"data": data_url}},
        )

        result = await plugin.process_request(request, "test-server")
        # No PII in "Hello World", should be allowed
        assert result.allowed is True


class TestPIIFilterBase64EdgeCases:
    """Test edge cases for base64 detection and decoding."""

    @pytest.fixture
    def plugin(self):
        """Create plugin with base64 scanning enabled."""
        return BasicPIIFilterPlugin({
            "action": "block",
            "pii_types": {"email": {"enabled": True}},
            "scan_base64": True,
        })

    @pytest.mark.asyncio
    async def test_short_base64_string_not_decoded(self, plugin):
        """Test that short base64 strings (< 12 chars) are not decoded."""
        # Very short base64 string (8 chars)
        short_b64 = "SGVsbG8="  # "Hello"

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-short",
            params={"name": "test", "arguments": {"data": short_b64}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be allowed (too short to decode)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_invalid_base64_ignored(self, plugin):
        """Test that invalid base64 strings are ignored."""
        # Invalid base64 (wrong padding, invalid chars)
        invalid_b64 = "This is not valid base64!!!"

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-invalid",
            params={"name": "test", "arguments": {"data": invalid_b64}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be allowed (invalid base64 is not decoded)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_plaintext_pii_takes_precedence(self, plugin):
        """Test that plaintext PII is detected before base64 decoding."""
        # String contains both plaintext email and base64
        mixed = "Contact: admin@example.com or use am9obi5zbWl0aEBjb21wYW55LmNvbQ=="

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-precedence",
            params={"name": "test", "arguments": {"data": mixed}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be blocked due to plaintext email
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True


class TestPIIFilterBase64ForcedBlocking:
    """Test forced blocking behavior for base64-encoded PII.

    Base64 content cannot be redacted without corrupting binary data.
    When action=redact and base64 PII is detected, the plugin must block.
    When action=audit_only, the plugin should allow through (no modification attempted).
    See ADR-025.
    """

    @pytest.fixture
    def plugin_redact(self):
        """Create plugin with base64 scanning enabled (redact mode)."""
        return BasicPIIFilterPlugin({
            "action": "redact",
            "pii_types": {"email": {"enabled": True}},
            "scan_base64": True,
        })

    @pytest.fixture
    def plugin_audit_only(self):
        """Create plugin with base64 scanning enabled (audit_only mode)."""
        return BasicPIIFilterPlugin({
            "action": "audit_only",
            "pii_types": {"email": {"enabled": True}},
            "scan_base64": True,
        })

    @pytest.mark.asyncio
    async def test_redact_mode_forces_block_for_base64_response(self, plugin_redact):
        """Test that base64-encoded PII in response forces blocking in redact mode."""
        from gatekit.protocol.messages import MCPResponse

        email = "secret@hidden.com"
        encoded_email = base64.b64encode(email.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-response",
            params={"name": "test"},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id="test-response",
            result={"content": encoded_email},
        )

        result = await plugin_redact.process_response(request, response, "test-server")
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True
        assert result.metadata.get("base64_force_block") is True
        assert "base64" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_redact_mode_forces_block_for_base64_notification(self, plugin_redact):
        """Test that base64-encoded PII in notification forces blocking in redact mode."""
        from gatekit.protocol.messages import MCPNotification

        email = "secret@hidden.com"
        encoded_email = base64.b64encode(email.encode()).decode()

        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/test",
            params={"data": encoded_email},
        )

        result = await plugin_redact.process_notification(notification, "test-server")
        assert result.allowed is False
        assert result.metadata.get("pii_detected") is True
        assert result.metadata.get("base64_force_block") is True
        assert "base64" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_audit_only_allows_base64_pii_request(self, plugin_audit_only):
        """Test that audit_only mode allows base64 PII through (no modification attempted)."""
        email = "secret@hidden.com"
        encoded_email = base64.b64encode(email.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-audit",
            params={"name": "test", "arguments": {"data": encoded_email}},
        )

        result = await plugin_audit_only.process_request(request, "test-server")
        # audit_only should allow through - no modification attempted
        assert result.allowed is True
        assert result.metadata.get("pii_detected") is True
        # Should NOT have base64_force_block since audit_only doesn't force block
        assert result.metadata.get("base64_force_block") is not True

    @pytest.mark.asyncio
    async def test_audit_only_allows_base64_pii_response(self, plugin_audit_only):
        """Test that audit_only mode allows base64 PII in response through."""
        from gatekit.protocol.messages import MCPResponse

        email = "secret@hidden.com"
        encoded_email = base64.b64encode(email.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-audit-response",
            params={"name": "test"},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id="test-audit-response",
            result={"content": encoded_email},
        )

        result = await plugin_audit_only.process_response(request, response, "test-server")
        assert result.allowed is True
        assert result.metadata.get("pii_detected") is True

    @pytest.mark.asyncio
    async def test_audit_only_allows_base64_pii_notification(self, plugin_audit_only):
        """Test that audit_only mode allows base64 PII in notification through."""
        from gatekit.protocol.messages import MCPNotification

        email = "secret@hidden.com"
        encoded_email = base64.b64encode(email.encode()).decode()

        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/test",
            params={"data": encoded_email},
        )

        result = await plugin_audit_only.process_notification(notification, "test-server")
        assert result.allowed is True
        assert result.metadata.get("pii_detected") is True
