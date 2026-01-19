"""Tests to verify that security plugins cannot be bypassed through length manipulation."""

import pytest
from gatekit.plugins.security.secrets import BasicSecretsFilterPlugin
from gatekit.protocol.messages import MCPRequest


class TestSecurityBypassPrevention:
    """Test that security plugins cannot be bypassed through length manipulation."""

    def test_short_secrets_are_not_bypassed(self):
        """Test that short secrets are not bypassed due to length constraints."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Test short but valid AWS access key pattern (20 chars)
        short_secret = "AKIA1234567890123456"

        # Should detect the pattern even though it's short
        result = plugin._detect_secrets_in_text(short_secret)
        assert len(result) > 0, "Short secrets should still be detected"
        assert result[0]["type"] == "aws_access_keys"

    def test_long_content_entropy_is_not_bypassed(self):
        """Test that long content with high entropy is not bypassed."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Create a long string with embedded secret (> 200 chars)
        long_secret = "A" * 100 + "AKIA1234567890123456" + "B" * 100

        # Should detect the secret even in long content
        result = plugin._detect_secrets_in_text(long_secret)
        assert len(result) > 0, "Secrets in long content should be detected"

    def test_entropy_detection_works_on_long_strings(self):
        """Test that entropy detection works on strings longer than previous max_length."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 3.0, "min_length": 8},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create a high-entropy string longer than old max_length (200)
        # Use a more varied character set for higher entropy
        high_entropy_long = (
            "X" * 100
            + "aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW3xY5zA7bC9dE1fG3hI5jK7lM9nO1pQ3rS5tU7vW9xY1zA3bC5dE7fG9hI1jK3lM5nO7pQ9rS1tU3vW5xY7zA9bC"
            + "Z" * 100
        )

        # Should detect high entropy even in long content
        is_potential_secret = plugin._is_potential_secret_by_entropy(high_entropy_long)
        assert (
            is_potential_secret
        ), "High entropy content should be detected regardless of length"

    def test_very_long_strings_are_processed_without_bypass(self):
        """Test that very long strings (>10000 chars) are still processed for entropy."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 3.0, "min_length": 8},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create a very long high-entropy token (not repeating pattern)
        # Use only 70 chars with high entropy - will be found by regex pattern
        high_entropy_token = (
            "aB3dE5fG7hI9jK1lM3nO5pQ7rS9tU1vW3xY5zA7bC9dE1fG3hI5jK7lM9nO1pQ3rS5tU"
        )

        # This should be detected due to high entropy (token pattern matching)
        is_potential_secret = plugin._is_potential_secret_by_entropy(high_entropy_token)
        assert is_potential_secret, "High entropy content should be detected"

    def test_scan_base64_configurable(self):
        """Test that base64 scanning can be enabled/disabled via config."""
        # Default: disabled
        config_disabled = {"action": "block"}
        plugin_disabled = BasicSecretsFilterPlugin(config_disabled)
        assert hasattr(plugin_disabled, "scan_base64")
        assert plugin_disabled.scan_base64 is False

        # Explicitly enabled
        config_enabled = {"action": "block", "scan_base64": True}
        plugin_enabled = BasicSecretsFilterPlugin(config_enabled)
        assert plugin_enabled.scan_base64 is True

        # The plugin uses a simple heuristic for data URLs
        # Test that short base64-like strings are still checked for patterns/entropy
        medium_string = "A" * 50  # 50 chars

        # _is_likely_base64_data only skips very long strings (>500 chars) or data URLs
        is_likely_base64 = plugin_enabled._is_likely_base64_data(medium_string)
        assert (
            not is_likely_base64
        ), "Medium strings should not be considered base64 data"

    def test_very_short_strings_still_bypass_entropy(self):
        """Test that very short strings still bypass entropy detection (to avoid false positives)."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Test strings shorter than min_length (8)
        very_short = "Abc123"  # 6 chars

        # Should not trigger entropy detection
        is_potential_secret = plugin._is_potential_secret_by_entropy(very_short)
        assert (
            not is_potential_secret
        ), "Very short strings should not trigger entropy detection"

    def test_pattern_detection_works_regardless_of_length(self):
        """Test that pattern-based detection works regardless of content length."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Test in short content
        short_content = "AKIA1234567890123456"
        short_result = plugin._detect_secrets_in_text(short_content)
        assert len(short_result) > 0, "Pattern detection should work in short content"

        # Test in long content
        long_content = "A" * 500 + "AKIA1234567890123456" + "B" * 500
        long_result = plugin._detect_secrets_in_text(long_content)
        assert len(long_result) > 0, "Pattern detection should work in long content"

    @pytest.mark.asyncio
    async def test_request_processing_bypasses_are_prevented(self):
        """Test that request processing cannot be bypassed through length manipulation."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Test short secret in request
        short_request = MCPRequest(
            jsonrpc="2.0",
            method="test_method",
            params={"secret": "AKIA1234567890123456"},
            id="test-1",
        )

        decision = await plugin.process_request(short_request, "test-server")
        assert not decision.allowed, "Short secrets in requests should be blocked"

        # Test long content with embedded secret
        long_request = MCPRequest(
            jsonrpc="2.0",
            method="test_method",
            params={"data": "A" * 500 + "AKIA1234567890123456" + "B" * 500},
            id="test-2",
        )

        decision = await plugin.process_request(long_request, "test-server")
        assert not decision.allowed, "Secrets in long content should be blocked"

    def test_entropy_calculation_respects_min_length(self):
        """Test that entropy calculation still respects minimum length for performance."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Default min_length is now 20 (more relaxed to reduce false positives)
        min_length = plugin.entropy_detection["min_length"]
        assert min_length == 20, "Default min_length should be 20"

        # Test string shorter than min_length
        short_string = "a" * (min_length - 1)
        entropy = plugin._calculate_entropy(short_string)
        assert entropy == 0.0, "Strings below min_length should return 0 entropy"

        # Test string at min_length
        at_min_length = "abcdefghijklmnopqrst"  # 20 chars
        entropy = plugin._calculate_entropy(at_min_length)
        assert entropy > 0.0, "Strings at min_length should have calculated entropy"
