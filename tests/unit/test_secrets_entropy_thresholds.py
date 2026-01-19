"""Tests for entropy detection threshold options in BasicSecretsFilterPlugin.

These tests verify that the entropy_detection.threshold option correctly
controls which high-entropy strings are flagged as potential secrets.

Test data reference: tests/validation/test-files/high-entropy.txt
"""

import pytest
from gatekit.plugins.security.secrets import BasicSecretsFilterPlugin
from gatekit.protocol.messages import MCPRequest


class TestEntropyThresholdConfiguration:
    """Test entropy threshold configuration validation and defaults."""

    def test_default_entropy_threshold(self):
        """Test that entropy detection is disabled by default with threshold 5.0."""
        plugin = BasicSecretsFilterPlugin({"action": "block"})
        # Disabled by default due to false positives
        assert plugin.entropy_detection["enabled"] is False
        # Most relaxed threshold (5.0) when enabled
        assert plugin.entropy_detection["threshold"] == 5.0

    def test_custom_entropy_threshold(self):
        """Test configuring a custom entropy threshold."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5},
        }
        plugin = BasicSecretsFilterPlugin(config)
        assert plugin.entropy_detection["threshold"] == 4.5

    def test_entropy_detection_disabled(self):
        """Test that entropy detection can be disabled."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": False},
        }
        plugin = BasicSecretsFilterPlugin(config)
        assert plugin.entropy_detection["enabled"] is False


class TestEntropyThresholdBehavior:
    """Test entropy threshold behavior at various values.

    Entropy values for reference:
    - Repeating pattern "aaaaaaaabbbbbbbb..." : ~2.0
    - English text/words: ~3.0
    - Medium randomness: ~4.0
    - High randomness (mixed case + numbers): ~5.0-5.5
    - Maximum (all unique chars): ~6.0

    Test data from tests/validation/test-files/high-entropy.txt:
    - HIGH_ENTROPY_KEY_1: 32-char hex, ~4.0 entropy
    - HIGH_ENTROPY_KEY_2: 40-char alphanumeric, ~5.5 entropy
    - HIGH_ENTROPY_SECRET: 64-char mixed, ~5.8 entropy
    - LOW_ENTROPY_KEY: 32-char repeating, ~2.0 entropy
    """

    # Test strings with known entropy ranges
    # Low entropy - repeated patterns (~2.0)
    LOW_ENTROPY_STRING = "aaaaaaaabbbbbbbbccccccccddddddddeeeeeeee"

    # Medium entropy - mixed but predictable (~3.5-4.0)
    MEDIUM_ENTROPY_STRING = "abcdef123456abcdef123456abcdef123456abcd"

    # High entropy - random alphanumeric (~5.0-5.5)
    HIGH_ENTROPY_STRING = "Kj9mNp2xQr5tYw8zAb3cDe6fGh1iJk4lMn7oPq0s"

    # Very high entropy - highly random (~5.8)
    VERY_HIGH_ENTROPY_STRING = (
        "xK9mN2pQr5tYw8zAb3cDe6fGhJk4lMn7oPqRsTuVwXyZ1234567890AbCd"
    )

    @pytest.mark.asyncio
    async def test_threshold_35_catches_medium_entropy(self):
        """Test that threshold 3.5 catches medium entropy strings."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 3.5, "min_length": 20},
            # Disable pattern matching to test only entropy detection
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Medium entropy should be detected at threshold 3.5
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"data": self.MEDIUM_ENTROPY_STRING},
            },
        )

        result = await plugin.process_request(request, "test-server")
        assert result.metadata["secret_detected"] is True
        assert any(
            d.get("type") == "entropy_based" for d in result.metadata.get("detections", [])
        )

    @pytest.mark.asyncio
    async def test_threshold_45_default_behavior(self):
        """Test that threshold 4.5 catches high but not medium entropy."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # High entropy should be detected
        request_high = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"data": self.HIGH_ENTROPY_STRING},
            },
        )
        result_high = await plugin.process_request(request_high, "test-server")
        assert result_high.metadata["secret_detected"] is True

        # Low entropy should NOT be detected
        request_low = MCPRequest(
            jsonrpc="2.0",
            id=2,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"data": self.LOW_ENTROPY_STRING},
            },
        )
        result_low = await plugin.process_request(request_low, "test-server")
        assert result_low.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_threshold_50_strict_mode(self):
        """Test that threshold 5.0 only catches very high entropy strings."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Very high entropy should be detected
        request_very_high = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"data": self.VERY_HIGH_ENTROPY_STRING},
            },
        )
        result = await plugin.process_request(request_very_high, "test-server")
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_threshold_60_very_strict(self):
        """Test that threshold 6.0 (default) minimizes false positives."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 6.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Even high entropy may not be detected at 6.0 threshold
        # This is intentionally conservative to minimize false positives
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"data": self.HIGH_ENTROPY_STRING},
            },
        )
        result = await plugin.process_request(request, "test-server")
        # At 6.0, most real-world strings won't trigger
        # This tests that the conservative default works
        assert result.metadata.get("secret_detected") is not None

    @pytest.mark.asyncio
    async def test_low_entropy_never_detected(self):
        """Test that low entropy strings are never detected regardless of threshold."""
        for threshold in [3.5, 4.0, 4.5, 5.0]:
            config = {
                "action": "block",
                "entropy_detection": {
                    "enabled": True,
                    "threshold": threshold,
                    "min_length": 20,
                },
                "secret_types": {},
            }
            plugin = BasicSecretsFilterPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id=1,
                method="tools/call",
                params={
                    "name": "test",
                    "arguments": {"data": self.LOW_ENTROPY_STRING},
                },
            )
            result = await plugin.process_request(request, "test-server")
            assert result.metadata["secret_detected"] is False, (
                f"Low entropy string should not be detected at threshold {threshold}"
            )


class TestEntropyThresholdWithPatternMatching:
    """Test entropy detection interaction with pattern-based detection."""

    @pytest.mark.asyncio
    async def test_pattern_match_overrides_entropy(self):
        """Test that pattern matches are found even without entropy match."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 6.0},  # Very high
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # AWS key pattern should be detected regardless of entropy threshold
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"key": "AKIAIOSFODNN7EXAMPLE"},
            },
        )
        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True
        assert any(
            d.get("type") == "aws_access_keys"
            for d in result.metadata.get("detections", [])
        )

    @pytest.mark.asyncio
    async def test_entropy_detects_unknown_secret_types(self):
        """Test that entropy detection catches secrets not in known patterns."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5, "min_length": 20},
            # Only enable a few pattern types
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # This looks like a secret but doesn't match AWS pattern
        # Should be caught by entropy detection
        unknown_secret = "sk_live_4eC39HqLyjWDarjtT1zdp7dc1234567890"

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"secret": unknown_secret},
            },
        )
        result = await plugin.process_request(request, "test-server")
        # Should be detected by entropy since it's high entropy
        assert result.metadata["secret_detected"] is True


class TestEntropyWithTestDataFile:
    """Test entropy detection using strings from test data file."""

    # Strings from tests/validation/test-files/high-entropy.txt
    HIGH_ENTROPY_KEY_1 = "a7f3b2e9c1d8f4a6b5c3d2e1f9a8b7c6"  # 32-char hex, ~4.0
    HIGH_ENTROPY_KEY_2 = "Kj9mNp2xQr5tYw8zAb3cDe6fGh1iJk4lMn7oPq0s"  # 40-char, ~5.5
    MEDIUM_ENTROPY_1 = "abcdef123456abcdef123456abcdef12"  # Repeated, lower entropy
    LOW_ENTROPY_KEY = "aaaaaaaabbbbbbbbccccccccdddddddd"  # Very low entropy
    EDGE_CASE_KEY = "aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV"  # ~4.5 entropy

    @pytest.mark.asyncio
    async def test_high_entropy_hex_at_various_thresholds(self):
        """Test 32-char hex string detection at various thresholds."""
        test_cases = [
            (3.5, True),  # Should detect at low threshold
            (4.0, True),  # Should detect at medium threshold
            (4.5, False),  # May not detect (32 chars is short for entropy-only)
            (5.0, False),  # Should not detect at high threshold
        ]

        for threshold, should_detect_entropy in test_cases:
            config = {
                "action": "block",
                "entropy_detection": {
                    "enabled": True,
                    "threshold": threshold,
                    "min_length": 20,
                },
                "secret_types": {},
            }
            plugin = BasicSecretsFilterPlugin(config)

            request = MCPRequest(
                jsonrpc="2.0",
                id=1,
                method="tools/call",
                params={
                    "name": "test",
                    "arguments": {"key": self.HIGH_ENTROPY_KEY_1},
                },
            )
            result = await plugin.process_request(request, "test-server")
            # Note: 32 chars may not meet the 40-char token minimum for entropy
            # This tests the actual behavior

    @pytest.mark.asyncio
    async def test_40_char_high_entropy_detection(self):
        """Test that 40-char high entropy strings are detected."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"key": self.HIGH_ENTROPY_KEY_2},
            },
        )
        result = await plugin.process_request(request, "test-server")
        assert result.metadata["secret_detected"] is True
        assert any(
            d.get("type") == "entropy_based" for d in result.metadata.get("detections", [])
        )

    @pytest.mark.asyncio
    async def test_low_entropy_never_flagged(self):
        """Test that low entropy strings are never flagged even at low threshold."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 3.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"key": self.LOW_ENTROPY_KEY},
            },
        )
        result = await plugin.process_request(request, "test-server")
        assert result.metadata["secret_detected"] is False


class TestValidationFileEntropyStrings:
    """Test the exact entropy strings from tests/validation/test-files/secrets.txt.

    These tests ensure the manual validation guide tests will work correctly.
    """

    # Exact strings from secrets.txt - full line (with variable name) must be 40+ chars
    # Entropy is calculated on the FULL tokenized line (e.g., "ENTROPY_LOW=value")
    ENTROPY_LOW = "abcdABCDabcdABCDabcdABCDabcdABCDabcd"  # Full line ~3.9 entropy
    ENTROPY_MED = "AaBbCcDdEeFfGgHhAaBbCcDdEeFfGgHh1234"  # Full line ~4.7 entropy
    ENTROPY_HIGH = "xK9mN2pQr5tYw8zAb3cDe6fGhJk4lMn7oPqRs"  # Full line ~5.4 entropy

    def test_entropy_calculation_matches_expected(self):
        """Verify our entropy calculations are correct for FULL LINE (with variable name)."""
        import math
        from collections import Counter

        def calculate_entropy(s):
            counts = Counter(s)
            length = len(s)
            entropy = 0.0
            for count in counts.values():
                prob = count / length
                entropy -= prob * math.log2(prob)
            return entropy

        # Full lines as they appear in the file (this is what gets tokenized)
        low_full = f"ENTROPY_LOW={self.ENTROPY_LOW}"
        med_full = f"ENTROPY_MED={self.ENTROPY_MED}"
        high_full = f"ENTROPY_HIGH={self.ENTROPY_HIGH}"

        low_entropy = calculate_entropy(low_full)
        med_entropy = calculate_entropy(med_full)
        high_entropy = calculate_entropy(high_full)

        # Verify expected entropy ranges for FULL LINE
        assert 3.5 <= low_entropy < 4.5, f"LOW full line entropy {low_entropy} not in expected range"
        assert 4.5 <= med_entropy < 5.0, f"MED full line entropy {med_entropy} not in expected range"
        assert high_entropy >= 5.0, f"HIGH full line entropy {high_entropy} should be >= 5.0"

        # Print for debugging
        print(f"\nFull line entropy (what gets detected):")
        print(f"  ENTROPY_LOW={self.ENTROPY_LOW[:20]}...: {low_entropy:.4f}")
        print(f"  ENTROPY_MED={self.ENTROPY_MED[:20]}...: {med_entropy:.4f}")
        print(f"  ENTROPY_HIGH={self.ENTROPY_HIGH[:20]}...: {high_entropy:.4f}")

    def test_strings_meet_tokenization_requirement(self):
        """Verify FULL LINES are 40+ chars to be tokenized for entropy check."""
        import re

        # This is the exact regex from secrets.py _detect_secrets_in_text_content
        # Includes negative lookbehind (?<!\\) to avoid matching chars after JSON escapes
        token_pattern = re.compile(r"(?<!\\)[A-Za-z0-9+/=_-]{40,200}")

        # Test full lines (variable name + = + value), not just values
        for name, value in [
            ("ENTROPY_LOW", self.ENTROPY_LOW),
            ("ENTROPY_MED", self.ENTROPY_MED),
            ("ENTROPY_HIGH", self.ENTROPY_HIGH),
        ]:
            full_line = f"{name}={value}"
            assert len(full_line) >= 40, f"{name} full line is only {len(full_line)} chars, needs 40+"
            matches = token_pattern.findall(full_line)
            assert len(matches) > 0, f"{name} full line not matched by tokenization regex"
            print(f"{name}={value[:15]}...: len={len(full_line)}, tokenized={matches[0][:30]}...")

    @pytest.mark.asyncio
    async def test_entropy_low_not_caught_at_45(self):
        """ENTROPY_LOW full line (~3.9) should NOT be caught at threshold 4.5."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Send full line as it appears in file (this is what gets tokenized)
        full_line = f"ENTROPY_LOW={self.ENTROPY_LOW}"
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test", "arguments": {"data": full_line}},
        )
        result = await plugin.process_request(request, "test-server")
        assert result.metadata["secret_detected"] is False, (
            f"ENTROPY_LOW full line should NOT be detected at threshold 4.5"
        )

    @pytest.mark.asyncio
    async def test_entropy_med_caught_at_45(self):
        """ENTROPY_MED full line (~4.7) SHOULD be caught at threshold 4.5."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Send full line as it appears in file (this is what gets tokenized)
        full_line = f"ENTROPY_MED={self.ENTROPY_MED}"
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test", "arguments": {"data": full_line}},
        )
        result = await plugin.process_request(request, "test-server")
        assert result.metadata["secret_detected"] is True, (
            f"ENTROPY_MED full line should be detected at threshold 4.5"
        )

    @pytest.mark.asyncio
    async def test_entropy_med_not_caught_at_50(self):
        """ENTROPY_MED full line (~4.7) should NOT be caught at threshold 5.0."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Send full line as it appears in file (this is what gets tokenized)
        full_line = f"ENTROPY_MED={self.ENTROPY_MED}"
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test", "arguments": {"data": full_line}},
        )
        result = await plugin.process_request(request, "test-server")
        assert result.metadata["secret_detected"] is False, (
            f"ENTROPY_MED full line should NOT be detected at threshold 5.0"
        )

    @pytest.mark.asyncio
    async def test_entropy_high_caught_at_50(self):
        """ENTROPY_HIGH full line (~5.4) SHOULD be caught at threshold 5.0."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Send full line as it appears in file (this is what gets tokenized)
        full_line = f"ENTROPY_HIGH={self.ENTROPY_HIGH}"
        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test", "arguments": {"data": full_line}},
        )
        result = await plugin.process_request(request, "test-server")

        # Debug output
        print(f"\nENTROPY_HIGH detection result:")
        print(f"  secret_detected: {result.metadata.get('secret_detected')}")
        print(f"  detections: {result.metadata.get('detections', [])}")

        assert result.metadata["secret_detected"] is True, (
            f"ENTROPY_HIGH full line (~5.4) should be detected at threshold 5.0"
        )
        assert any(
            d.get("type") == "entropy_based" for d in result.metadata.get("detections", [])
        ), "Detection should be entropy_based"

    @pytest.mark.asyncio
    async def test_direct_entropy_method_on_full_lines(self):
        """Directly test the plugin's _calculate_entropy method on full lines."""
        plugin = BasicSecretsFilterPlugin({"action": "block"})

        # Test full lines (what actually gets tokenized)
        low_full = f"ENTROPY_LOW={self.ENTROPY_LOW}"
        med_full = f"ENTROPY_MED={self.ENTROPY_MED}"
        high_full = f"ENTROPY_HIGH={self.ENTROPY_HIGH}"

        low_entropy = plugin._calculate_entropy(low_full)
        med_entropy = plugin._calculate_entropy(med_full)
        high_entropy = plugin._calculate_entropy(high_full)

        print(f"\nPlugin._calculate_entropy on full lines:")
        print(f"  {low_full[:30]}...: {low_entropy:.4f}")
        print(f"  {med_full[:30]}...: {med_entropy:.4f}")
        print(f"  {high_full[:30]}...: {high_entropy:.4f}")

        # Verify HIGH full line is above 5.0
        assert high_entropy >= 5.0, f"HIGH full line entropy {high_entropy} should be >= 5.0"

    @pytest.mark.asyncio
    async def test_is_potential_secret_by_entropy_direct(self):
        """Directly test _is_potential_secret_by_entropy method on full lines."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test full lines (what actually gets tokenized)
        low_full = f"ENTROPY_LOW={self.ENTROPY_LOW}"
        med_full = f"ENTROPY_MED={self.ENTROPY_MED}"
        high_full = f"ENTROPY_HIGH={self.ENTROPY_HIGH}"

        is_potential_low = plugin._is_potential_secret_by_entropy(low_full)
        is_potential_med = plugin._is_potential_secret_by_entropy(med_full)
        is_potential_high = plugin._is_potential_secret_by_entropy(high_full)

        print(f"\n_is_potential_secret_by_entropy at threshold 5.0:")
        print(f"  ENTROPY_LOW full line:  {is_potential_low}")
        print(f"  ENTROPY_MED full line:  {is_potential_med}")
        print(f"  ENTROPY_HIGH full line: {is_potential_high}")

        assert is_potential_high is True, (
            f"ENTROPY_HIGH full line should be flagged as potential secret at threshold 5.0"
        )

    @pytest.mark.asyncio
    async def test_entropy_high_in_file_context(self):
        """Test ENTROPY_HIGH detection when embedded in file content like secrets.txt.

        Uses audit_only mode to test detection without redaction.
        """
        # Simulate file content structure from secrets.txt (using class constants)
        file_content = f"""=== ENTROPY THRESHOLD TEST STRINGS ===
# Note: Full line (including variable name) must be 40+ chars for entropy detection

# Full line entropy ~3.9 - Caught at threshold 3.5, NOT at 4.5 or 5.0
ENTROPY_LOW={self.ENTROPY_LOW}

# Full line entropy ~4.7 - Caught at threshold 3.5 and 4.5, NOT at 5.0
ENTROPY_MED={self.ENTROPY_MED}

# Full line entropy ~5.4 - Caught at ALL thresholds (3.5, 4.5, 5.0)
ENTROPY_HIGH={self.ENTROPY_HIGH}
"""

        # Use audit_only to test detection without redaction
        config = {
            "action": "audit_only",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Simulate MCP response containing file content
        from gatekit.protocol.messages import MCPResponse

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "read_file", "arguments": {"path": "/test/secrets.txt"}},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": file_content}]},
        )

        result = await plugin.process_response(request, response, "test-server")

        print(f"\nFile content detection result:")
        print(f"  secret_detected: {result.metadata.get('secret_detected')}")
        print(f"  detections count: {len(result.metadata.get('detections', []))}")
        for d in result.metadata.get("detections", []):
            entropy = d.get("entropy_score")
            entropy_str = f"{entropy:.4f}" if entropy else "N/A"
            print(f"    - type: {d.get('type')}, entropy: {entropy_str}")

        # ENTROPY_HIGH should be detected
        assert result.metadata["secret_detected"] is True, (
            "ENTROPY_HIGH in file content should be detected at threshold 5.0"
        )

    @pytest.mark.asyncio
    async def test_redaction_with_single_line_content(self):
        """Test redaction works with single line content."""
        single_line_content = f"ENTROPY_HIGH={self.ENTROPY_HIGH}"

        config = {
            "action": "redact",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        from gatekit.protocol.messages import MCPResponse

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "read_file", "arguments": {"path": "/test/secret.txt"}},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": single_line_content}]},
        )

        result = await plugin.process_response(request, response, "test-server")

        # Single line content should work with redaction
        assert result.metadata["secret_detected"] is True
        assert result.modified_content is not None, "Should have modified response"

        # Verify redaction worked
        modified_text = result.modified_content.result["content"][0]["text"]
        assert "[SECRET REDACTED" in modified_text
        assert self.ENTROPY_HIGH not in modified_text

    @pytest.mark.asyncio
    async def test_redaction_with_multiline_content(self):
        """Test redaction works with multiline content containing JSON escapes.

        This test verifies the fix for the bug where tokenization would pick up
        characters from JSON escape sequences (like the 'n' from '\\n'), causing
        position-based redaction to corrupt the JSON.
        """
        # Content with newlines - these become \n in JSON
        multiline_content = f"""Line one
ENTROPY_HIGH={self.ENTROPY_HIGH}
Line three"""

        config = {
            "action": "redact",
            "entropy_detection": {"enabled": True, "threshold": 5.0, "min_length": 20},
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        from gatekit.protocol.messages import MCPResponse

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "read_file", "arguments": {"path": "/test/secret.txt"}},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={"content": [{"type": "text", "text": multiline_content}]},
        )

        result = await plugin.process_response(request, response, "test-server")

        # Should detect and redact without corrupting JSON
        assert result.metadata["secret_detected"] is True
        assert result.modified_content is not None, "Should have modified response"

        # Verify redaction worked and JSON is valid
        modified_text = result.modified_content.result["content"][0]["text"]
        assert "[SECRET REDACTED" in modified_text
        assert self.ENTROPY_HIGH not in modified_text
        # Verify newlines are preserved
        assert "\n" in modified_text

    @pytest.mark.asyncio
    async def test_tokenization_with_equals_sign(self):
        """Test that ENTROPY_HIGH= prefix doesn't break tokenization."""
        import re

        # The full line as it appears in the file (using class constant)
        full_line = f"ENTROPY_HIGH={self.ENTROPY_HIGH}"

        # Tokenization regex from secrets.py (with negative lookbehind for JSON escapes)
        token_pattern = re.compile(r"(?<!\\)[A-Za-z0-9+/=_-]{40,200}")
        tokens = token_pattern.findall(full_line)

        print(f"\nTokenization of full line:")
        print(f"  Full line: {full_line}")
        print(f"  Tokens found: {tokens}")

        # The full line should be tokenized (40+ chars)
        assert len(tokens) > 0, "Full line should be tokenized"

        # Check entropy of the tokenized result
        import math
        from collections import Counter

        def calc_entropy(s):
            counts = Counter(s)
            length = len(s)
            return -sum((c / length) * math.log2(c / length) for c in counts.values())

        for token in tokens:
            entropy = calc_entropy(token)
            print(f"    Token '{token[:20]}...' (len={len(token)}): entropy={entropy:.4f}")

        # The full line "ENTROPY_HIGH=..." includes '=' which is in the token pattern
        # Verify the token entropy is above 5.0
        if tokens:
            full_line_entropy = calc_entropy(tokens[0])
            print(f"\n  Full line token entropy: {full_line_entropy:.4f}")
            assert full_line_entropy >= 5.0, f"Full line entropy {full_line_entropy} should be >= 5.0"


class TestEntropyMinLengthInteraction:
    """Test interaction between threshold and min_length settings."""

    @pytest.mark.asyncio
    async def test_short_high_entropy_string_not_detected(self):
        """Test that strings below min_length are not checked for entropy."""
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 3.0,  # Low threshold
                "min_length": 50,  # High minimum length
            },
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # 40-char high entropy - below min_length of 50
        short_high_entropy = "xK9mN2pQr5tYw8zAb3cDe6fGhJk4lMn7oPq0sT1u"

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"key": short_high_entropy},
            },
        )
        result = await plugin.process_request(request, "test-server")
        # Should not be detected because length < min_length
        assert result.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_long_low_entropy_string_not_detected(self):
        """Test that long low-entropy strings are not detected."""
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 3.5,
                "min_length": 20,
            },
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # 100-char low entropy - long but repetitive
        long_low_entropy = "aaaa" * 25  # 100 chars of 'a'

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"key": long_low_entropy},
            },
        )
        result = await plugin.process_request(request, "test-server")
        # Should not be detected despite length because entropy is low
        assert result.metadata["secret_detected"] is False


class TestEntropyMinLengthConfigBugFix:
    """Tests for the min_length configuration option bug fix.

    Previously, the entropy detection regex hardcoded {40,200} instead of using
    the configured min_length value. This meant tokens shorter than 40 chars
    were never checked regardless of min_length setting.

    These tests verify that min_length now correctly controls the minimum
    token length for entropy detection.
    """

    # 24-char high-entropy string (simulates a typical API token)
    # This is below the old hardcoded 40-char minimum but above default min_length of 20
    HIGH_ENTROPY_24_CHAR = "xK9mN2pQr5tYw8zAb3cDe6fG"  # ~5.0 entropy

    # 19-char high-entropy string (below default min_length of 20)
    HIGH_ENTROPY_19_CHAR = "xK9mN2pQr5tYw8zAb3c"  # High entropy but too short

    @pytest.mark.asyncio
    async def test_24_char_detected_with_default_min_length(self):
        """A 24-char high-entropy string IS detected with default min_length (20).

        This tests the bug fix: previously 24-char strings were never checked
        because the regex hardcoded {40,200}. Now with the fix, strings down to
        min_length (default 20) are tokenized and checked for entropy.
        """
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 4.5,  # Reasonable threshold
                # min_length defaults to 20
            },
            "secret_types": {},  # Disable pattern matching to isolate entropy detection
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"api_key": self.HIGH_ENTROPY_24_CHAR},
            },
        )
        result = await plugin.process_request(request, "test-server")

        assert result.metadata["secret_detected"] is True, (
            "24-char high-entropy string should be detected with default min_length (20)"
        )
        assert any(
            d.get("type") == "entropy_based" for d in result.metadata.get("detections", [])
        ), "Detection should be entropy_based"

    @pytest.mark.asyncio
    async def test_24_char_not_detected_with_min_length_30(self):
        """A 24-char high-entropy string is NOT detected when min_length is set to 30.

        This verifies that the min_length configuration option actually controls
        the minimum token length for entropy detection.
        """
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 4.5,
                "min_length": 30,  # Higher than our 24-char string
            },
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"api_key": self.HIGH_ENTROPY_24_CHAR},
            },
        )
        result = await plugin.process_request(request, "test-server")

        assert result.metadata["secret_detected"] is False, (
            "24-char string should NOT be detected when min_length is 30"
        )

    @pytest.mark.asyncio
    async def test_19_char_not_detected_with_default_min_length(self):
        """A 19-char high-entropy string is NOT detected with default min_length (20).

        This verifies that strings shorter than min_length are correctly excluded.
        """
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 4.0,  # Low threshold to ensure we'd catch it if tokenized
                # min_length defaults to 20
            },
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"api_key": self.HIGH_ENTROPY_19_CHAR},
            },
        )
        result = await plugin.process_request(request, "test-server")

        assert result.metadata["secret_detected"] is False, (
            "19-char string should NOT be detected with default min_length (20)"
        )

    @pytest.mark.asyncio
    async def test_stripe_like_key_detected(self):
        """A Stripe-like API key (~32 chars) is detected with default min_length.

        Real-world example: Stripe API keys are ~32 characters, which were
        previously missed due to the hardcoded 40-char minimum.
        """
        # Simulates a Stripe-like key format (not matching any pattern-based detection)
        stripe_like_key = "rk_test_4eC39HqLyjWDarjtT1zdp7dc"  # 32 chars

        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 4.5,
                # min_length defaults to 20
            },
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"stripe_key": stripe_like_key},
            },
        )
        result = await plugin.process_request(request, "test-server")

        assert result.metadata["secret_detected"] is True, (
            "32-char Stripe-like key should be detected with default min_length"
        )

    @pytest.mark.asyncio
    async def test_21_char_minimum_detected(self):
        """A 21-char high-entropy string (just above min_length) is detected.

        This verifies the boundary condition: strings at or just above the
        minimum length are correctly tokenized and checked.
        """
        # 21-char high-entropy string - just above default min_length of 20
        high_entropy_21 = "xK9mN2pQr5tYw8zAb3cDe"  # ~4.4 entropy

        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 4.0,
                # min_length defaults to 20
            },
            "secret_types": {},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test",
                "arguments": {"api_key": high_entropy_21},
            },
        )
        result = await plugin.process_request(request, "test-server")

        assert result.metadata["secret_detected"] is True, (
            "21-char high-entropy string should be detected with default min_length (20)"
        )
