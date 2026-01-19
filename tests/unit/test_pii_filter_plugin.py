"""Tests for the BasicPIIFilterPlugin security plugin."""

import base64
import pytest
from gatekit.plugins.security.pii import BasicPIIFilterPlugin
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestBasicPIIFilterPluginConfiguration:
    """Test configuration validation for BasicPIIFilterPlugin."""

    def test_valid_configuration_parsing(self):
        """Test valid configuration is parsed correctly."""
        config = {
            "action": "redact",
            "pii_types": {
                "credit_card": {"enabled": True},
                "email": {"enabled": True},
                "phone": {"enabled": True},
                "national_id": {"enabled": True},
            },
        }

        plugin = BasicPIIFilterPlugin(config)
        assert plugin.action == "redact"
        assert plugin.pii_types["credit_card"]["enabled"] is True
        assert plugin.pii_types["phone"]["enabled"] is True

    # Note: test_invalid_action_configuration removed - schema validates action enum
    # See tests/unit/test_schema_validation_coverage.py

    def test_invalid_pii_type_configuration(self):
        """Test invalid PII type configuration raises ValueError."""
        config = {
            "action": "redact",
            "pii_types": {"eye_color": {"enabled": True}},  # Invalid PII type
        }

        with pytest.raises(ValueError, match="Unsupported PII type 'eye_color'"):
            BasicPIIFilterPlugin(config)

    def test_typo_in_pii_type_configuration(self):
        """Test typo in PII type name is caught by validation."""
        config = {
            "action": "redact",
            "pii_types": {"emial": {"enabled": True}},  # Typo: should be 'email'
        }

        with pytest.raises(ValueError, match="Unsupported PII type 'emial'"):
            BasicPIIFilterPlugin(config)

    def test_multiple_invalid_pii_types_configuration(self):
        """Test that validation catches the first invalid PII type."""
        config = {
            "action": "redact",
            "pii_types": {
                "hair_color": {"enabled": True},  # Invalid
                "favorite_food": {"enabled": True},  # Also invalid
            },
        }

        with pytest.raises(ValueError, match="Unsupported PII type"):
            BasicPIIFilterPlugin(config)

    def test_missing_action_uses_default(self):
        """Test missing action configuration uses default."""
        config = {"pii_types": {}}

        plugin = BasicPIIFilterPlugin(config)
        assert plugin.action == "redact"  # Default action for PII plugin

    # Note: test_invalid_custom_pattern_configuration removed - custom_patterns feature removed
    # See tests/unit/test_schema_validation_coverage.py

    def test_patterns_compiled_when_pii_types_enabled(self):
        """Test that patterns are compiled for enabled types and not for disabled."""
        config = {
            "action": "redact",
            "pii_types": {
                "credit_card": {"enabled": True},
                "phone": {"enabled": True},
                "national_id": {"enabled": True},
                "email": {"enabled": True},
                "ip_address": {"enabled": False},  # Explicitly disabled
            },
        }

        plugin = BasicPIIFilterPlugin(config)

        # Verify patterns were compiled for all enabled types
        assert "credit_card" in plugin.compiled_patterns
        assert "phone" in plugin.compiled_patterns
        assert "national_id" in plugin.compiled_patterns
        assert "email" in plugin.compiled_patterns
        # ip_address explicitly disabled, so should not be compiled
        assert "ip_address" not in plugin.compiled_patterns

    def test_all_pii_types_enabled_by_default(self):
        """Test that all PII types are enabled by default per ADR-024."""
        # Minimal config - no pii_types specified
        config = {"action": "redact"}

        plugin = BasicPIIFilterPlugin(config)

        # All PII types should be enabled by default
        for pii_type in plugin.PII_TYPES.keys():
            assert pii_type in plugin.compiled_patterns, f"{pii_type} should be compiled by default"

class TestPIIDetectionCreditCard:
    """Test credit card PII detection.

    Tests credit card detection for major card types using Luhn-validated test numbers.
    Covers: Visa, MasterCard, American Express, and Discover cards.

    Specific test values:
    - Visa: 4532015112830366 (16 digits, starts with 4)
    - MasterCard: 5555555555554444 (16 digits, starts with 5)
    - American Express: 378282246310005 (15 digits, starts with 34/37)
    - Discover: 6011111111111117 (16 digits, starts with 6011)
    - Invalid Luhn: 4532015112830367 (should not be detected)
    """

    @pytest.fixture
    def plugin(self):
        """Create plugin for credit card testing."""
        config = {"action": "block", "pii_types": {"credit_card": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_visa_credit_card_detection(self, plugin):
        """Test Visa credit card detection with Luhn validation.

        Tests: 4532015112830366 (valid Visa test number)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "My card is 4532015112830366"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert "PII detected" in decision.reason
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "CREDIT_CARD" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_mastercard_detection(self, plugin):
        """Test MasterCard detection with Luhn validation.

        Tests: 5555555555554444 (valid MasterCard test number)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={
                "name": "test_tool",
                "arguments": {"data": "Card: 5555555555554444"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_amex_detection(self, plugin):
        """Test American Express detection with Luhn validation.

        Tests: 378282246310005 (valid AmEx test number)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-3",
            params={
                "name": "test_tool",
                "arguments": {"data": "AmEx: 378282246310005"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_discover_detection(self, plugin):
        """Test Discover card detection with Luhn validation.

        Tests: 6011111111111117 (valid Discover test number)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-4",
            params={
                "name": "test_tool",
                "arguments": {"data": "Discover: 6011111111111117"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_invalid_luhn_not_detected(self, plugin):
        """Test invalid Luhn checksum is not detected as credit card.

        Tests: 4532015112830367 (invalid Luhn checksum - last digit changed from 6 to 7)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-5",
            params={
                "name": "test_tool",
                "arguments": {"data": "Invalid: 4532015112830367"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is True

    @pytest.mark.asyncio
    async def test_visa_spaced_format_detection(self, plugin):
        """Test Visa credit card detection with spaces.

        Tests: 4532 0151 1283 0366 (valid Visa with spaces)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-6",
            params={
                "name": "test_tool",
                "arguments": {"data": "Card: 4532 0151 1283 0366"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert "PII detected" in decision.reason
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "CREDIT_CARD" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_mastercard_dashed_format_detection(self, plugin):
        """Test MasterCard detection with dashes.

        Tests: 5555-5555-5555-4444 (valid MasterCard with dashes)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-7",
            params={
                "name": "test_tool",
                "arguments": {"data": "MC: 5555-5555-5555-4444"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "CREDIT_CARD" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_amex_spaced_format_detection(self, plugin):
        """Test American Express detection with spaces (4-6-5 format).

        Tests: 3782 822463 10005 (valid Amex with spaces)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-8",
            params={
                "name": "test_tool",
                "arguments": {"data": "Amex: 3782 822463 10005"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "CREDIT_CARD" for d in decision.metadata["detections"])


class TestPIIDetectionEmail:
    """Test email address PII detection.

    Tests RFC 5322 compliant email detection for various formats.

    Specific test values:
    - Simple email: user@example.com
    - Complex email: user.name+tag@sub.domain.co.uk
    """

    @pytest.fixture
    def plugin(self):
        """Create plugin for email testing."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_simple_email_detection(self, plugin):
        """Test simple email address detection.

        Tests: user@example.com
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Contact user@example.com for help"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "EMAIL" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_complex_email_detection(self, plugin):
        """Test complex email address detection.

        Tests: user.name+tag@sub.domain.co.uk (complex format with subdomain and country TLD)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={
                "name": "test_tool",
                "arguments": {"data": "Email: user.name+tag@sub.domain.co.uk"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_email_in_url_parameter(self, plugin):
        """Test email detection in URL parameters.

        Tests: https://example.com/user?email=user@example.com
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-3",
            params={
                "name": "test_tool",
                "arguments": {
                    "data": "URL: https://example.com/user?email=user@example.com"
                },
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "EMAIL" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_email_concatenated_with_text(self, plugin):
        """Test email detection when concatenated with other text.

        Tests: userid:user@example.com,active
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-4",
            params={
                "name": "test_tool",
                "arguments": {"data": "userid:user@example.com,active"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "EMAIL" for d in decision.metadata["detections"])


class TestPIIDetectionPhone:
    """Test US phone number PII detection.

    Tests US phone number formats only (parentheses, dash, dot).
    UK/international formats removed due to false positive issues.

    Specific test values:
    - US parentheses: (555) 123-4567
    - US dash: 555-123-4567
    - US dot: 555.123.4567
    """

    @pytest.fixture
    def plugin_phone(self):
        """Create plugin for phone testing."""
        config = {
            "action": "block",
            "pii_types": {"phone": {"enabled": True}},
        }
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_us_phone_parentheses_format(self, plugin_phone):
        """Test US phone number in (xxx) xxx-xxxx format.

        Tests: (555) 123-4567
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Call me at (555) 123-4567"},
            },
        )

        decision = await plugin_phone.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "PHONE" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_us_phone_dash_format(self, plugin_phone):
        """Test US phone number in xxx-xxx-xxxx format.

        Tests: 555-123-4567
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={"name": "test_tool", "arguments": {"data": "Phone: 555-123-4567"}},
        )

        decision = await plugin_phone.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_us_phone_dots_format(self, plugin_phone):
        """Test US phone number with dots instead of dashes.

        Tests: 555.123.4567 (xxx.xxx.xxxx format) - should be detected as PII
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-4",
            params={
                "name": "test_tool",
                "arguments": {"data": "Call me at 555.123.4567"},
            },
        )

        decision = await plugin_phone.process_request(request, "test-server")
        # Dot format should be detected as PII
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_us_phone_mixed_separators(self, plugin_phone):
        """Test US phone number with mixed separators.

        Tests: (555)123-4567 (parentheses without space after)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-5",
            params={"name": "test_tool", "arguments": {"data": "Phone: (555)123-4567"}},
        )

        decision = await plugin_phone.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "PHONE" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_us_phone_dot_format(self, plugin_phone):
        """Test US phone number dot format detection.

        Tests: 555.123.4567 (dot-separated format)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-dot",
            params={
                "name": "test_tool",
                "arguments": {"data": "Call us at 555.123.4567 for support"},
            },
        )

        decision = await plugin_phone.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "PHONE" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_max_safe_integer_not_detected_as_phone(self, plugin_phone):
        """MAX_SAFE_INTEGER in JSON schemas should not trigger phone detection.

        This is a regression test for a false positive where the UK phone pattern
        0\\d{4}\\s?\\d{6} matched inside 9007199254740991 (JS MAX_SAFE_INTEGER),
        corrupting MCP tool schemas. UK/international patterns were removed to fix this.
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-fp",
            params={"schema": {"maximum": 9007199254740991}},
        )
        decision = await plugin_phone.process_request(request, "test-server")
        assert decision.allowed is True
        assert decision.metadata["pii_detected"] is False


class TestPIIDetectionIPAddress:
    """Test IP address PII detection.

    Tests IPv4 and IPv6 address detection.

    Specific test values:
    - IPv4: 192.168.1.100 (private IP)
    - IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334 (full format)
    """

    @pytest.fixture
    def plugin_email_only(self):
        """Create plugin for testing (IP address detection removed)."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.fixture
    def plugin_ip(self):
        """Create plugin for IP address testing."""
        config = {
            "action": "block",
            "pii_types": {"ip_address": {"enabled": True}},
        }
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_ipv4_detection(self, plugin_ip):
        """Test IPv4 addresses are detected as PII.

        Tests detection of IPv4 address patterns.
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Server IP: 192.168.1.100"},
            },
        )

        decision = await plugin_ip.process_request(request, "test-server")
        # Should be blocked - IP addresses are now detected as PII again
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "IP_ADDRESS" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_ipv6_detection(self, plugin_ip):
        """Test IPv6 addresses are detected as PII.

        Tests detection of IPv6 address patterns.
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={
                "name": "test_tool",
                "arguments": {"data": "IPv6: 2001:0db8:85a3:0000:0000:8a2e:0370:7334"},
            },
        )

        decision = await plugin_ip.process_request(request, "test-server")
        # Should be blocked - IP addresses are now detected as PII again
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "IP_ADDRESS" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_mixed_ip_formats_detected(self, plugin_ip):
        """Test that both IPv4 and IPv6 formats are detected.

        Both IPv4 and IPv6 formats are supported.
        """
        # Test IPv4 detection
        ipv4_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-ipv4",
            params={
                "name": "test_tool",
                "arguments": {"data": "Config server: 192.168.1.1"},
            },
        )

        decision = await plugin_ip.process_request(ipv4_request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "IP_ADDRESS" for d in decision.metadata["detections"])

        # Test IPv6 detection
        ipv6_request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-ipv6",
            params={
                "name": "test_tool",
                "arguments": {
                    "data": "IPv6 addr: 2001:0db8:85a3:0000:0000:8a2e:0370:7334"
                },
            },
        )

        decision = await plugin_ip.process_request(ipv6_request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "IP_ADDRESS" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_data_url_should_be_skipped(self):
        """Test that data URLs are skipped during PII detection."""
        config = {
            "action": "block",
            "pii_types": {
                "credit_card": {"enabled": True},
                "email": {"enabled": True},
                "phone": {"enabled": True},
            },
        }
        plugin = BasicPIIFilterPlugin(config)

        # Test various data URLs that should be skipped
        data_urls = [
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAAXNSR0IArs4c6QAAAAtJREFUGFdjYAACAAAFAAGq1chRAAAAAElFTkSuQmCC",
            "data:text/plain;base64,SGVsbG8gV29ybGQ=",
            "data:application/json;base64,eyJtZXNzYWdlIjogIkhlbGxvIFdvcmxkIn0=",
            "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAK==",
            "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAAAAGlzb21tcDQx",
            "data:font/woff;base64,d09GRgABAAAAAC4AAAA=",
        ]

        for data_url in data_urls:
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id="test-data-url",
                params={"name": "test_tool", "arguments": {"data": data_url}},
            )

            decision = await plugin.process_request(request, "test-server")
            assert (
                decision.allowed is True
            ), f"Data URL should be allowed: {data_url[:50]}..."
            assert decision.metadata["pii_detected"] is False

    @pytest.mark.asyncio
    async def test_data_url_with_pii_in_content_should_be_skipped(self):
        """Test that data URLs with PII in base64 content are skipped (as intended)."""
        config = {"action": "block", "pii_types": {"credit_card": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Credit card embedded in data URL base64 content - should be skipped
        credit_card = "4532015112830366"  # Valid test Visa number
        malicious_data_url = (
            f"data:text/plain;base64,{base64.b64encode(credit_card.encode()).decode()}"
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-pii-in-data-url-content",
            params={"name": "test_tool", "arguments": {"data": malicious_data_url}},
        )

        decision = await plugin.process_request(request, "test-server")
        # Should NOT detect PII since it's in base64 content (legitimate file data)
        assert decision.allowed is True
        assert decision.metadata["pii_detected"] is False

    @pytest.mark.asyncio
    async def test_data_url_with_pii_outside_content_should_detect(self):
        """Test that PII outside data URL content is still detected."""
        config = {"action": "block", "pii_types": {"credit_card": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Credit card outside the data URL
        credit_card = "4532015112830366"  # Valid test Visa number
        text_with_pii = (
            f"Card: {credit_card} and image: data:image/png;base64,iVBORw0KGgo="
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-pii-outside-data-url",
            params={"name": "test_tool", "arguments": {"data": text_with_pii}},
        )

        decision = await plugin.process_request(request, "test-server")
        # Should detect the PII since it's outside the data URL
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True


class TestPIIDetectionNationalID:
    """Test national ID PII detection.

    Tests various national ID formats including US SSN and UK National Insurance.

    Specific test values:
    - US SSN (dashed): 123-45-6789
    - US SSN (no dashes): 123456789
    - UK National Insurance: AB 12 34 56 C
    """

    @pytest.fixture
    def plugin_national_id(self):
        """Create plugin for national ID testing."""
        config = {
            "action": "block",
            "pii_types": {"national_id": {"enabled": True}},
        }
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_us_ssn_dashed_format(self, plugin_national_id):
        """Test US SSN in xxx-xx-xxxx format.

        Tests: 123-45-6789
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_tool", "arguments": {"data": "SSN: 123-45-6789"}},
        )

        decision = await plugin_national_id.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "NATIONAL_ID" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_us_ssn_no_dashes_format_no_longer_detected(self, plugin_national_id):
        """Test US SSN in xxxxxxxxx format is no longer detected (Requirement 8).

        Unformatted 9-digit SSNs cause too many false positives and are
        no longer detected. Only formatted SSNs (xxx-xx-xxxx) are detected.

        Tests: 123456789 (should NOT be detected)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={"name": "test_tool", "arguments": {"data": "Social: 123456789"}},
        )

        decision = await plugin_national_id.process_request(request, "test-server")
        # Should be allowed - unformatted SSNs no longer detected
        assert decision.allowed is True
        assert decision.metadata["pii_detected"] is False

    @pytest.mark.asyncio
    async def test_uk_ni_format(self, plugin_national_id):
        """Test UK National Insurance number format.

        Tests: AB 12 34 56 C
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-3",
            params={
                "name": "test_tool",
                "arguments": {"data": "NI Number: AB 12 34 56 C"},
            },
        )

        decision = await plugin_national_id.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_canadian_sin_format(self, plugin_national_id):
        """Test Canadian Social Insurance Number format.

        Tests: 123-456-789
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-4",
            params={"name": "test_tool", "arguments": {"data": "SIN: 123-456-789"}},
        )

        decision = await plugin_national_id.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_uk_ni_no_spaces(self, plugin_national_id):
        """Test UK National Insurance number without spaces.

        Tests: AB123456C (compact format)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-5",
            params={"name": "test_tool", "arguments": {"data": "NI Number: AB123456C"}},
        )

        decision = await plugin_national_id.process_request(request, "test-server")
        assert decision.allowed is False
        assert decision.metadata["pii_detected"] is True
        assert any(d["type"] == "NATIONAL_ID" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_us_ssn_in_json_format_no_longer_detected(self, plugin_national_id):
        """Test US SSN in JSON format is no longer detected (Requirement 8).

        Unformatted 9-digit SSNs cause too many false positives and are
        no longer detected, even in JSON format. Only formatted SSNs are detected.

        Tests: {"ssn":123456789} (should NOT be detected)
        """
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-6",
            params={"name": "test_tool", "arguments": {"data": '{"ssn":123456789}'}},
        )

        decision = await plugin_national_id.process_request(request, "test-server")
        # Should be allowed - unformatted SSNs no longer detected
        assert decision.allowed is True
        assert decision.metadata["pii_detected"] is False


# Note: TestPIIDetectionCustomPatterns class removed - custom_patterns feature removed
# See tests/unit/test_schema_validation_coverage.py


class TestModeBlockBehavior:
    """Test block mode behavior."""

    @pytest.fixture
    def plugin(self):
        """Create plugin in block mode."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_block_mode_prevents_transmission(self, plugin):
        """Test block mode returns PluginResult(allowed=False) when PII detected."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Contact user@example.com"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is False
        assert "PII detected" in decision.reason
        assert decision.modified_content is None

    @pytest.mark.asyncio
    async def test_block_mode_allows_clean_content(self, plugin):
        """Test block mode allows content without PII."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={
                "name": "test_tool",
                "arguments": {"data": "This is clean content"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is True
        assert decision.metadata["pii_detected"] is False


class TestModeRedactBehavior:
    """Test redact mode behavior."""

    @pytest.fixture
    def plugin(self):
        """Create plugin in redact mode."""
        config = {"action": "redact", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_redact_mode_replaces_pii(self, plugin):
        """Test redact mode returns PluginResult with modified_response."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Contact user@example.com for help"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is True
        assert decision.modified_content is not None

        # Check that PII was redacted
        modified_data = decision.modified_content.params["arguments"]["data"]
        assert "user@example.com" not in modified_data
        assert "[EMAIL REDACTED by Gatekit]" in modified_data

    @pytest.mark.asyncio
    async def test_redact_mode_preserves_clean_content(self, plugin):
        """Test redact mode allows clean content unchanged."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={
                "name": "test_tool",
                "arguments": {"data": "This is clean content"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is True
        assert decision.modified_content is None


class TestModeAuditBehavior:
    """Test audit_only mode behavior."""

    @pytest.fixture
    def plugin(self):
        """Create plugin in audit_only mode."""
        config = {"action": "audit_only", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_audit_mode_logs_detections(self, plugin):
        """Test audit_only mode returns PluginResult(allowed=True) with metadata."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Contact user@example.com"},
            },
        )

        decision = await plugin.process_request(request, "test-server")
        assert decision.allowed is True
        assert decision.metadata["pii_detected"] is True
        assert decision.metadata["detection_action"] == "audit_only"
        assert decision.modified_content is None


class TestResponseProcessing:
    """Test response processing functionality."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for response testing."""
        config = {"action": "redact", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_response_pii_redaction(self, plugin):
        """Test response with PII is redacted."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={"name": "test_tool", "arguments": {}},
        )

        response = MCPResponse(
            jsonrpc="2.0",
            id="test-1",
            result={"data": "Contact user@example.com for support"},
        )

        decision = await plugin.process_response(request, response, "test-server")
        assert decision.allowed is True
        assert decision.modified_content is not None

        modified_data = decision.modified_content.result["data"]
        assert "user@example.com" not in modified_data
        assert "[EMAIL REDACTED by Gatekit]" in modified_data


class TestNotificationProcessing:
    """Test notification processing functionality."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for notification testing."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_notification_pii_detection(self, plugin):
        """Test notification with PII is blocked."""
        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/message",
            params={"message": "Contact user@example.com"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is False
        assert "PII detected" in decision.reason

    @pytest.mark.asyncio
    async def test_notification_redact_mode_redacts(self):
        """Test that redact mode properly redacts PII from notifications."""
        config = {"action": "redact", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0",
            method="status",
            params={"message": "User john@example.com logged in"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert "PII detected and redacted from notification" in decision.reason
        assert decision.modified_content is not None

        # Check that PII was redacted
        modified_message = decision.modified_content.params["message"]
        assert "john@example.com" not in modified_message
        assert "[EMAIL REDACTED by Gatekit]" in modified_message

    @pytest.mark.asyncio
    async def test_notification_redact_mode_no_pii(self):
        """Test that redact mode allows clean notifications without modification."""
        config = {"action": "redact", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0",
            method="status",
            params={"message": "User logged in successfully"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert decision.modified_content is None
        assert decision.metadata["pii_detected"] is False

    @pytest.mark.asyncio
    async def test_notification_audit_only_allows(self):
        """Test that audit_only mode allows notifications with PII."""
        config = {
            "action": "audit_only",
            "pii_types": {"phone": {"enabled": True}},
        }
        plugin = BasicPIIFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0", method="alert", params={"contact": "Call me at 555-123-4567"}
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert "audit only" in decision.reason
        assert decision.metadata["pii_detected"] is True


class TestPluginResultMetadataStructure:
    """Test PluginResult metadata structure validation."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for metadata testing."""
        config = {
            "action": "audit_only",
            "pii_types": {"email": {"enabled": True}, "credit_card": {"enabled": True}},
        }
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_metadata_structure_single_detection(self, plugin):
        """Test metadata structure for single PII detection."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {"data": "Email: user@example.com"},
            },
        )

        decision = await plugin.process_request(request, "test-server")

        # Validate metadata structure
        assert "pii_detected" in decision.metadata
        assert "detection_action" in decision.metadata
        assert "detections" in decision.metadata

        assert decision.metadata["pii_detected"] is True
        assert decision.metadata["detection_action"] == "audit_only"
        assert isinstance(decision.metadata["detections"], list)
        assert len(decision.metadata["detections"]) == 1

        detection = decision.metadata["detections"][0]
        assert "type" in detection
        assert "pattern" in detection
        assert "position" in detection
        assert "action" in detection

        assert detection["type"] == "EMAIL"
        assert isinstance(detection["position"], list)
        assert len(detection["position"]) == 2  # start, end positions

    @pytest.mark.asyncio
    async def test_metadata_structure_multiple_detections(self, plugin):
        """Test metadata structure for multiple PII detections."""
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-2",
            params={
                "name": "test_tool",
                "arguments": {"data": "Email user@example.com, card 4532015112830366"},
            },
        )

        decision = await plugin.process_request(request, "test-server")

        assert len(decision.metadata["detections"]) == 2
        types = [d["type"] for d in decision.metadata["detections"]]
        assert "EMAIL" in types
        assert "CREDIT_CARD" in types


class TestPerformanceRequirements:
    """Test performance requirements (<25ms per message, typically <10ms in isolation)."""

    @pytest.fixture
    def plugin(self):
        """Create plugin for performance testing."""
        config = {
            "action": "redact",
            "pii_types": {
                "email": {"enabled": True},
                "credit_card": {"enabled": True},
                "phone": {"enabled": True},
                "national_id": {"enabled": True},
            },
        }
        return BasicPIIFilterPlugin(config)

    @pytest.mark.asyncio
    async def test_performance_under_25ms(self, plugin):
        """Test processing time is under 25ms for typical message.

        Note: Threshold is 25ms to accommodate Windows overhead during parallel test execution.
        Actual processing is typically <10ms in isolation.
        """
        import time

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-1",
            params={
                "name": "test_tool",
                "arguments": {
                    "data": "Large message with various content but no PII to test performance"
                    * 100
                },
            },
        )

        start_time = time.perf_counter()
        decision = await plugin.process_request(request, "test-server")
        end_time = time.perf_counter()

        processing_time_ms = (end_time - start_time) * 1000
        assert (
            processing_time_ms < 25.0
        ), f"Processing took {processing_time_ms:.2f}ms, expected <25ms"
        assert decision.allowed is True


class TestContentProcessingConfiguration:
    """Test content processing configuration and chunking functionality."""

    def test_content_processing_constants(self):
        """Test that content processing uses proper constants."""

        BasicPIIFilterPlugin({"action": "block"})

    @pytest.mark.asyncio
    async def test_large_content_chunking(self):
        """Test that large content is processed in chunks."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Create content larger than chunk size (64KB) with PII at the end
        large_content = "a" * 70000 + " Contact us at test@example.com"

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"text": large_content}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata["pii_detected"] is True
        assert len(result.metadata["detections"]) > 0
        assert result.metadata["detections"][0]["type"] == "EMAIL"

    @pytest.mark.asyncio
    async def test_pii_across_chunk_boundary(self):
        """Test detection of PII that spans chunk boundaries."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Create content where email would be near chunk boundary
        # With 64KB chunks, we need a lot of content
        content = "x" * 65530 + "contact@example.com" + "x" * 40

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"text": content}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_very_large_content_processing(self):
        """Test that very large content is processed without limits."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Create very large content with PII at the end
        large_content = "a" * 10000 + " Contact: test@example.com"

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"text": large_content}},
        )

        # Should detect PII even in very large content
        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata["pii_detected"] is True

    @pytest.mark.asyncio
    async def test_no_duplicate_detections_in_overlap(self):
        """Test that overlapping chunks don't create duplicate detections."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Create content with email that will be in overlap region
        content = "x" * 80 + "test@example.com" + "x" * 80

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"text": content}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False

        # Check that we don't have duplicate detections
        detections = result.metadata["detections"]
        positions = [(d["position"][0], d["position"][1]) for d in detections]
        assert len(positions) == len(set(positions))  # No duplicates


class TestPIIContentSizeLimits:
    """Test MAX_CONTENT_SIZE enforcement in PII filter plugin."""

    @pytest.mark.asyncio
    async def test_oversized_content_blocked_early(self):
        """Test that PII filter blocks oversized content early."""
        config = {"action": "block", "pii_types": {"email": {"enabled": True}}}
        plugin = BasicPIIFilterPlugin(config)

        # Create content larger than MAX_CONTENT_SIZE (1MB)
        from gatekit.plugins.security import MAX_CONTENT_SIZE

        oversized_content = "C" * (MAX_CONTENT_SIZE + 1000)

        request = MCPRequest(
            jsonrpc="2.0",
            method="test_method",
            params={"large_content": oversized_content},
            id="test-1",
        )

        # Should block due to size limit
        decision = await plugin.process_request(request, "test-server")

        assert not decision.allowed, "Should block oversized content"
        assert (
            "exceeds maximum size limit" in decision.reason
        ), "Should mention size limit"
        assert (
            decision.metadata["reason_code"] == "content_size_exceeded"
        ), "Should have correct reason code"
        assert (
            decision.metadata["content_size_bytes"] > MAX_CONTENT_SIZE
        ), "Should report actual size"
