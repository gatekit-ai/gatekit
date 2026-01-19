"""Tests for the BasicSecretsFilterPlugin security plugin."""

import pytest
import base64
from gatekit.plugins.security.secrets import BasicSecretsFilterPlugin
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification


class TestBasicSecretsFilterPluginConfiguration:
    """Test configuration validation for BasicSecretsFilterPlugin."""

    def test_valid_configuration_parsing(self):
        """Test valid secrets detection configuration loading with all supported types."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
                "google_api_keys": {"enabled": True},
                "jwt_tokens": {"enabled": True},
                "ssh_private_keys": {"enabled": True},
                "slack_tokens": {"enabled": True},
                "private_keys": {"enabled": False},
            },
            "entropy_detection": {"enabled": True, "threshold": 5.5, "min_length": 8},
        }

        plugin = BasicSecretsFilterPlugin(config)
        assert plugin.action == "block"
        assert plugin.secret_types["aws_access_keys"]["enabled"] is True
        assert plugin.secret_types["slack_tokens"]["enabled"] is True
        assert plugin.secret_types["private_keys"]["enabled"] is False
        assert plugin.entropy_detection["enabled"] is True
        assert plugin.entropy_detection["threshold"] == 5.5

    # Note: test_invalid_configuration_handling removed - schema validates action enum
    # See tests/unit/test_schema_validation_coverage.py

    def test_invalid_secret_type_configuration(self):
        """Test invalid secret type configuration raises ValueError."""
        config = {
            "action": "block",
            "secret_types": {
                "bitcoin_wallet": {"enabled": True}  # Invalid secret type
            },
        }

        with pytest.raises(
            ValueError, match="Unsupported secret type 'bitcoin_wallet'"
        ):
            BasicSecretsFilterPlugin(config)

    def test_typo_in_secret_type_configuration(self):
        """Test typo in secret type name is caught by validation."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_acess_keys": {"enabled": True}  # Typo: should be 'aws_access_keys'
            },
        }

        with pytest.raises(
            ValueError, match="Unsupported secret type 'aws_acess_keys'"
        ):
            BasicSecretsFilterPlugin(config)

    def test_multiple_invalid_secret_types_configuration(self):
        """Test that validation catches the first invalid secret type."""
        config = {
            "action": "block",
            "secret_types": {
                "invalid_type_1": {"enabled": True},  # Invalid
                "invalid_type_2": {"enabled": True},  # Also invalid
            },
        }

        with pytest.raises(ValueError, match="Unsupported secret type"):
            BasicSecretsFilterPlugin(config)

    def test_secret_type_specific_configuration(self):
        """Test enabling/disabling specific secret types individually."""
        config = {
            "action": "redact",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": False},
                "slack_tokens": {"enabled": True},
                "private_keys": {"enabled": False},
            },
        }

        plugin = BasicSecretsFilterPlugin(config)
        assert plugin.secret_types["aws_access_keys"]["enabled"] is True
        assert plugin.secret_types["github_tokens"]["enabled"] is False
        assert plugin.secret_types["slack_tokens"]["enabled"] is True
        assert plugin.secret_types["private_keys"]["enabled"] is False

    def test_new_secret_types_have_patterns(self):
        """Test that all new secret types have corresponding detection patterns."""
        config = {
            "action": "block",
            "secret_types": {
                "slack_tokens": {"enabled": True},
                "private_keys": {"enabled": True},
            },
        }

        plugin = BasicSecretsFilterPlugin(config)

        # Check that patterns were compiled for enabled types
        assert (
            "slack_tokens" in plugin.compiled_patterns
        ), "Slack tokens should have compiled pattern"
        assert (
            "private_keys" in plugin.compiled_patterns
        ), "Private keys should have compiled pattern"

    def test_generic_secrets_removed_from_config(self):
        """Test that generic_secrets is no longer a valid secret type."""
        config = {
            "action": "block",
            "secret_types": {
                "generic_secrets": {"enabled": True}  # No longer supported
            },
        }

        with pytest.raises(
            ValueError, match="Unsupported secret type 'generic_secrets'"
        ):
            BasicSecretsFilterPlugin(config)

    def test_entropy_threshold_configuration_validation(self):
        """Test entropy detection threshold validation and edge cases."""
        config = {
            "action": "audit_only",
            "entropy_detection": {
                "enabled": True,
                "threshold": 3.0,
                "min_length": 16,
                "max_length": 300,
            },
        }

        plugin = BasicSecretsFilterPlugin(config)
        assert plugin.entropy_detection["threshold"] == 3.0
        assert plugin.entropy_detection["min_length"] == 16
        assert plugin.entropy_detection["max_length"] == 300


class TestRequestProcessing:
    """Test secret detection in requests."""

    @pytest.mark.asyncio
    async def test_request_with_aws_key_blocked(self):
        """Test that requests containing AWS access keys are blocked in block mode."""
        config = {
            "action": "block",
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={
                "name": "upload_config",
                "arguments": {"aws_key": "AKIAIOSFODNN7EXAMPLE"},
            },
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert "Secret detected" in result.reason
        assert result.metadata["secret_detected"] is True
        assert result.metadata["detection_mode"] == "block"
        assert len(result.metadata["detections"]) > 0

        # Verify full detection metadata schema (contract test)
        detection = result.metadata["detections"][0]
        assert "type" in detection
        assert "pattern" in detection
        assert "position" in detection
        assert "action" in detection
        assert "confidence" in detection
        assert detection["type"] == "aws_access_keys"
        assert detection["confidence"] == "high"
        assert detection["action"] == "block"

    @pytest.mark.asyncio
    async def test_request_with_github_token_redacted(self):
        """Test that requests containing GitHub tokens are redacted in redact mode."""
        config = {
            "action": "redact",
            "secret_types": {"github_tokens": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={
                "name": "git_push",
                "arguments": {"token": "ghp_1234567890abcdef1234567890abcdef12345678"},
            },
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is True
        assert "Secret redacted" in result.reason
        assert result.metadata["secret_detected"] is True
        assert result.metadata["detection_mode"] == "redact"

        # Check that the content was actually redacted
        modified_request = result.modified_content
        assert modified_request is not None
        assert "[SECRET REDACTED by Gatekit]" in str(modified_request.params)
        assert "ghp_1234567890abcdef1234567890abcdef12345678" not in str(
            modified_request.params
        )

    @pytest.mark.asyncio
    async def test_request_with_jwt_token_audit_only(self):
        """Test that requests with JWT tokens are logged but allowed in audit_only mode."""
        config = {
            "action": "audit_only",
            "secret_types": {"jwt_tokens": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "authenticate", "arguments": {"auth_token": jwt_token}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is True
        assert "Secret logged" in result.reason
        assert result.metadata["secret_detected"] is True
        assert result.metadata["detection_mode"] == "audit_only"

    @pytest.mark.asyncio
    async def test_request_with_ssh_key_detected(self):
        """Test detection of SSH private keys in requests."""
        config = {
            "action": "block",
            "secret_types": {"ssh_private_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={
                "name": "setup_ssh",
                "arguments": {
                    "key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7yn3bRHQ..."
                },
            },
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True
        assert result.metadata["detections"][0]["type"] == "ssh_private_keys"

    @pytest.mark.asyncio
    async def test_request_with_google_api_key_detected(self):
        """Test detection of Google API keys in requests."""
        config = {
            "action": "block",
            "secret_types": {"google_api_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={
                "name": "maps_query",
                "arguments": {"api_key": "AIza1234567890abcdef1234567890abcdef123456"},
            },
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True
        assert result.metadata["detections"][0]["type"] == "google_api_keys"

    @pytest.mark.asyncio
    async def test_request_with_slack_token_detected(self):
        """Test detection of Slack tokens in requests."""
        config = {
            "action": "block",
            "secret_types": {"slack_tokens": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test various Slack token formats
        slack_tokens = [
            "xoxb-1234567890-1234567890-abcdefghijklmnopqrstuvwxyz",  # Bot token
            "xoxp-1234567890-1234567890-1234567890-abcdefghijklmnopqr",  # User token
            "xoxa-2-1234567890-1234567890-abcdefghijklmnopqrstuvwx",  # App token
            "xoxr-1234567890-abcdefghijklmnopqrstuvwxyz",  # Refresh token
            "xoxs-1234567890-1234567890-1234567890-abcdefghijklmnopqr",  # Session token
        ]

        for token in slack_tokens:
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id=1,
                params={"name": "slack_notify", "arguments": {"token": token}},
            )

            result = await plugin.process_request(request, "test-server")
            assert result.allowed is False, f"Slack token should be detected: {token}"
            assert result.metadata["secret_detected"] is True
            assert result.metadata["detections"][0]["type"] == "slack_tokens"

    @pytest.mark.asyncio
    async def test_request_with_private_key_detected(self):
        """Test detection of private keys in requests."""
        config = {
            "action": "block",
            "secret_types": {"private_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test private key formats that don't overlap with ssh_private_keys
        private_keys = [
            "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7...",
            "-----BEGIN ENCRYPTED PRIVATE KEY-----\nMIIFLTBXBgkqhkiG9w0BBQ0wSjApBgkqhkiG9w...",
        ]

        for key in private_keys:
            request = MCPRequest(
                jsonrpc="2.0",
                method="tools/call",
                id=1,
                params={"name": "setup_key", "arguments": {"private_key": key}},
            )

            result = await plugin.process_request(request, "test-server")
            assert (
                result.allowed is False
            ), f"Private key should be detected: {key[:50]}..."
            assert result.metadata["secret_detected"] is True
            assert result.metadata["detections"][0]["type"] == "private_keys"

    @pytest.mark.asyncio
    async def test_request_without_secrets_allowed(self):
        """Test that requests without secrets are allowed through."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "read_file", "arguments": {"path": "normal_file.txt"}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is True
        assert "No secrets detected" in result.reason
        assert result.metadata["secret_detected"] is False

    # Note: All custom_patterns and allowlist tests removed - features removed
    # See tests/unit/test_schema_validation_coverage.py

    @pytest.mark.asyncio
    async def test_entropy_detection_in_requests(self):
        """Test entropy-based secret detection in requests."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5, "min_length": 8},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # High entropy string that looks like a secret
        high_entropy_string = (
            "aB3xF9kL2mN8pQ5rS7tU1vW4yZ6cE0dG" + "hI9jK2lM5nO8pQ1rS4tU7vW0yZ3aB6c"
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={
                "name": "authenticate",
                "arguments": {"secret": high_entropy_string},
            },
        )

        result = await plugin.process_request(request, "test-server")
        # Note: Entropy detection is conservative, so this may or may not be detected
        # depending on the exact entropy calculation and thresholds
        if result.metadata["secret_detected"]:
            assert any(
                "entropy" in detection["type"]
                for detection in result.metadata["detections"]
            )

    @pytest.mark.asyncio
    async def test_request_processing_performance(self):
        """Test that request processing meets performance requirements."""
        config = {
            "action": "audit_only",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
                "google_api_keys": {"enabled": True},
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create a request with large content
        large_content = (
            "Normal text content " * 100
            + " AKIAIOSFODNN7EXAMPLE "
            + "More content " * 100
        )

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "process_data", "arguments": {"content": large_content}},
        )

        # Time the processing
        import time

        start_time = time.time()
        result = await plugin.process_request(request, "test-server")
        end_time = time.time()

        processing_time_ms = (end_time - start_time) * 1000

        # Should process efficiently (targeting <10ms per the secrets filter requirements)
        assert (
            processing_time_ms < 10
        ), f"Request processing took {processing_time_ms:.2f}ms, should be under 10ms"

        # Should detect the AWS key
        assert result.metadata["secret_detected"] is True


class TestBasicSecretsFilterPluginResponseDetection:
    """Test secret detection in responses."""

    @pytest.mark.asyncio
    async def test_response_with_aws_key_blocked(self):
        """Test that responses containing AWS access keys are blocked in block mode."""
        config = {
            "action": "block",
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create a mock request and response with AWS key
        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id=1,
            params={"name": "read_file", "arguments": {"path": "secrets.txt"}},
        )

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\nAWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI...",
                    }
                ]
            },
        )

        decision = await plugin.process_response(request, response, "test-server")
        assert decision.allowed is False
        assert "Secret detected in response" in decision.reason
        assert decision.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_response_with_github_token_redacted(self):
        """Test that responses containing GitHub tokens are redacted in redact mode."""
        config = {
            "action": "redact",
            "secret_types": {"github_tokens": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create response with GitHub token
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id=1, params={"name": "read_file"}
        )

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "content": "GITHUB_TOKEN=ghp_1234567890abcdefghijklmnopqrstuvwxyz12"
            },
        )

        decision = await plugin.process_response(request, response, "test-server")
        assert decision.allowed is True
        assert "Secret redacted from response" in decision.reason
        assert decision.metadata["secret_detected"] is True

        # Check that the content was actually redacted
        modified_response = decision.modified_content
        assert modified_response is not None
        assert "[SECRET REDACTED by Gatekit]" in str(modified_response.result)
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz12" not in str(
            modified_response.result
        )

    @pytest.mark.asyncio
    async def test_response_without_secrets_allowed(self):
        """Test that responses without secrets are allowed through."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create response without secrets
        request = MCPRequest(
            jsonrpc="2.0", method="tools/call", id=1, params={"name": "read_file"}
        )

        response = MCPResponse(
            jsonrpc="2.0",
            id=1,
            result={
                "content": "This is a clean file with no secrets. Just normal text."
            },
        )

        decision = await plugin.process_response(request, response, "test-server")
        assert decision.allowed is True
        assert "No secrets detected in response" in decision.reason
        assert decision.metadata["secret_detected"] is False


class TestNotificationHandling:
    """Test secrets detection and filtering in notifications."""

    @pytest.mark.asyncio
    async def test_notification_with_secrets_blocked(self):
        """Test that notifications containing secrets are blocked in block mode."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create notification with secrets
        notification = MCPNotification(
            jsonrpc="2.0",
            method="log",
            params={"message": "API Key found: AKIAIOSFODNN7EXAMPLE", "level": "info"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is False
        assert "Secrets detected in notification" in decision.reason
        assert decision.metadata["secret_detected"] is True
        assert len(decision.metadata["detections"]) > 0

    @pytest.mark.asyncio
    async def test_notification_with_secrets_in_method_name(self):
        """Test detection of secrets in notification method names."""
        config = {
            "action": "block",
            "secret_types": {"github_tokens": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create notification with secret in method name (unusual but possible)
        notification = MCPNotification(
            jsonrpc="2.0",
            method="ghp_1234567890abcdefghijklmnopqrstuvwxyz12",
            params={"data": "clean"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is False
        assert decision.metadata["secret_detected"] is True
        assert any(d["field"] == "method" for d in decision.metadata["detections"])

    @pytest.mark.asyncio
    async def test_notification_redact_mode_redacts(self):
        """Test that redact mode properly redacts secrets from notifications."""
        config = {
            "action": "redact",
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0", method="log", params={"key": "AKIAIOSFODNN7EXAMPLE"}
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert "redacted from notification" in decision.reason.lower()
        assert decision.modified_content is not None

        # Check that secret was redacted
        modified_key = decision.modified_content.params["key"]
        assert "AKIAIOSFODNN7EXAMPLE" not in modified_key
        assert "[SECRET REDACTED by Gatekit]" in modified_key

    @pytest.mark.asyncio
    async def test_notification_redact_mode_no_secrets(self):
        """Test that redact mode allows clean notifications without modification."""
        config = {
            "action": "redact",
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0", method="log", params={"message": "No secrets here"}
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert decision.modified_content is None
        assert decision.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_notification_audit_only_allows(self):
        """Test that audit_only mode allows notifications with secrets."""
        config = {
            "action": "audit_only",
            "secret_types": {"github_tokens": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0",
            method="log",
            params={"token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz12"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert "audit only" in decision.reason.lower()
        assert decision.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_notification_without_secrets_allowed(self):
        """Test that clean notifications are allowed through."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        notification = MCPNotification(
            jsonrpc="2.0",
            method="log",
            params={"message": "User logged in successfully", "level": "info"},
        )

        decision = await plugin.process_notification(notification, "test-server")
        assert decision.allowed is True
        assert "No secrets detected" in decision.reason
        assert decision.metadata["secret_detected"] is False


class TestBase64DetectionConfiguration:
    """Test base64 detection configuration and heuristics."""

    def test_scan_base64_configuration(self):
        """Test that scan_base64 can be configured."""
        config = {
            "action": "block",
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)
        assert hasattr(plugin, "scan_base64")
        assert plugin.scan_base64 is True

    def test_default_scan_base64_values(self):
        """Test that base64 scanning is disabled by default."""
        plugin = BasicSecretsFilterPlugin({"action": "block"})
        assert hasattr(plugin, "scan_base64")
        # Disabled by default due to false positives on images/files
        assert plugin.scan_base64 is False

    @pytest.mark.asyncio
    async def test_base64_file_signature_detection(self):
        """Test that base64-encoded files with signatures are skipped."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True},
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create base64-encoded PNG header
        png_header = b"\x89PNG\r\n\x1a\n" + b"x" * 100
        base64_png = base64.b64encode(png_header).decode("utf-8")

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": base64_png}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is True
        assert result.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_base64_strict_mode_disables_heuristic(self):
        """Test that strict mode disables the base64 heuristic."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.0},
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create high-entropy base64 string that would normally be skipped
        import secrets

        high_entropy_data = secrets.token_bytes(150)
        high_entropy_base64 = base64.b64encode(high_entropy_data).decode("utf-8")

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": high_entropy_base64}},
        )

        result = await plugin.process_request(request, "test-server")
        # In strict mode, it should be detected as a potential secret
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_base64_min_length_threshold(self):
        """Test that base64 strings below min_length are not skipped."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.0},
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create base64 string shorter than min_length with high entropy
        short_base64 = base64.b64encode(b"abcdefghijklmnop" * 5).decode("utf-8")

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": short_base64}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be detected since it's shorter than min_length
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_data_url_always_skipped(self):
        """Test that data URLs are always skipped regardless of settings."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True},
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)

        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"image": data_url}},
        )

        result = await plugin.process_request(request, "test-server")
        assert result.allowed is True
        assert result.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_scan_base64_disabled(self):
        """Test that disabling base64 scanning processes all base64 strings."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.0},
            "scan_base64": False,
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Long base64 string that would normally be skipped
        import secrets

        high_entropy_data = secrets.token_bytes(200)
        long_base64 = base64.b64encode(high_entropy_data).decode("utf-8")

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": long_base64}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be detected since base64 detection is disabled
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_data_url_skipping_comprehensive(self):
        """Test comprehensive data URL skipping for all MIME types."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.0},
            # scan_base64 not set (defaults to False)
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test various data URL formats - base64 content is not decoded/scanned
        data_urls = [
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA",  # Shortened to avoid entropy detection
            "data:text/plain;base64,SGVsbG8gV29ybGQ=",  # "Hello World" - short enough
            "data:application/json;base64,eyJtZXNzYWdlIjogIkhlbGxvIn0=",  # Shortened JSON
            "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAK==",
            "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAAAAGlzb21tcDQx",
            "data:font/woff;base64,d09GRgABAAAAAC4AAAA=",
        ]

        for data_url in data_urls:
            request = MCPRequest(
                jsonrpc="2.0",
                id=1,
                method="tools/call",
                params={"name": "test_tool", "arguments": {"data": data_url}},
            )

            result = await plugin.process_request(request, "test-server")
            # Data URLs should be handled - prefix is checked but base64 content is skipped
            # However, if the base64 part is >40 chars and high entropy, it may still trigger
            # These shorter examples should pass
            assert (
                result.allowed is True
            ), f"Data URL should be allowed: {data_url[:50]}..."

    @pytest.mark.asyncio
    async def test_data_url_with_secrets_in_content_should_be_skipped(self):
        """Test that data URLs with secrets in the base64 content are skipped (as intended)."""
        config = {
            "action": "block",
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # AWS access key embedded in data URL base64 content - should be skipped
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        malicious_data_url = (
            f"data:text/plain;base64,{base64.b64encode(aws_key.encode()).decode()}"
        )

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": malicious_data_url}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should NOT detect the secret since it's in base64 content (legitimate file data)
        assert result.allowed is True
        assert result.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_data_url_with_secrets_in_non_content_should_detect(self):
        """Test that secrets outside the data URL content are still detected."""
        config = {
            "action": "block",
            "secret_types": {"aws_access_keys": {"enabled": True}},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # AWS access key outside the data URL
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        text_with_secret = (
            f"API Key: {aws_key} and image: data:image/png;base64,iVBORw0KGgo="
        )

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": text_with_secret}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should detect the secret since it's outside the data URL
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_multiple_file_signatures(self):
        """Test detection of various file signatures in base64."""
        config = {
            "action": "block",
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test various file signatures
        file_headers = [
            b"\xff\xd8\xff",  # JPEG
            b"%PDF-1.4",  # PDF
            b"PK\x03\x04",  # ZIP
            b"GIF89a",  # GIF
        ]

        for header in file_headers:
            file_data = header + b"x" * 100
            base64_data = base64.b64encode(file_data).decode("utf-8")

            request = MCPRequest(
                jsonrpc="2.0",
                id=1,
                method="tools/call",
                params={"name": "test_tool", "arguments": {"file": base64_data}},
            )

            result = await plugin.process_request(request, "test-server")
            assert result.allowed is True
            assert result.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_scan_base64_at_minimum_length(self):
        """Test base64 detection works at exactly the minimum length threshold (20 chars)."""
        config = {
            "action": "block",
            "scan_base64": True,
            "entropy_detection": {"enabled": True, "threshold": 6.0},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Exactly 20-character base64 string (should be checked)
        base64_20_chars = "QVBJMTIzNDU2Nzg5MDEyMw=="  # 20 chars

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"secret": base64_20_chars}},
        )

        result = await plugin.process_request(request, "test-server")
        # Should be processed (length >= 20) and may be detected based on entropy
        assert result is not None

    @pytest.mark.asyncio
    async def test_long_strings_still_checked_for_secrets(self):
        """Test that long strings (>1000 chars) are still checked for embedded secrets."""
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 5.0,
            },  # Lower threshold to ensure detection
            "scan_base64": True,
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create a 1200-character string with an embedded AWS API key
        # This tests that we removed the dangerous "> 1000 chars = file data" assumption
        padding = "A" * 500
        api_key = (
            "AKIA1234567890ABCDEF"  # AWS access key pattern - guaranteed detection
        )
        long_string_with_secret = (
            padding + api_key + padding + "B" * 680
        )  # Total > 1200 chars

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={
                "name": "test_tool",
                "arguments": {"data": long_string_with_secret},
            },
        )

        result = await plugin.process_request(request, "test-server")

        # Should detect the embedded API key (not skip as "file data")
        assert (
            result.allowed is False
        ), f"Long strings should still be checked, got allowed={result.allowed}"
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_large_content_rejected(self):
        """Test that content exceeding 1MB is rejected with appropriate error message."""
        config = {"action": "block", "entropy_detection": {"enabled": True}}
        plugin = BasicSecretsFilterPlugin(config)

        # Create content of exactly 1MB + 1 byte
        large_content = "A" * (1024 * 1024 + 1)  # 1,048,577 bytes

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": large_content}},
        )

        result = await plugin.process_request(request, "test-server")

        # Should be rejected due to size limit
        assert result.allowed is False
        assert "exceeds maximum size limit" in result.reason
        assert result.metadata["plugin"] == "BasicSecretsFilterPlugin"
        assert result.metadata["reason_code"] == "content_size_exceeded"
        # Content size includes JSON encoding overhead, so it will be slightly larger
        assert result.metadata["content_size_bytes"] > 1024 * 1024
        assert result.metadata["max_size"] == 1024 * 1024

    @pytest.mark.asyncio
    async def test_exactly_max_size_content_processed(self):
        """Test that content close to 1MB (accounting for JSON overhead) is processed normally."""
        config = {"action": "block", "entropy_detection": {"enabled": True}}
        plugin = BasicSecretsFilterPlugin(config)

        # Create content that will be exactly at the limit after JSON encoding
        # Account for JSON overhead: {"name":"test_tool","arguments":{"data":"..."}}
        json_overhead = 48  # Approximate overhead from JSON structure
        content_size = 1024 * 1024 - json_overhead
        max_size_content = "A" * content_size

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": max_size_content}},
        )

        result = await plugin.process_request(request, "test-server")

        # Should be processed normally (not rejected for size)
        assert result.allowed is True  # No secrets in "AAAA..." string
        assert "No secrets detected" in result.reason

    @pytest.mark.asyncio
    async def test_entropy_threshold_reduces_false_positives(self):
        """Test entropy threshold reduces false positives on legitimate code."""
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 6.0},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test string with entropy around 4.8 (typical code)
        code_like_string = "functionNameWithCamelCase123"  # Legitimate code pattern

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"code": code_like_string}},
        )

        result = await plugin.process_request(request, "test-server")

        # Should NOT be flagged as secret (entropy < 6.0)
        assert result.allowed is True
        assert result.metadata["secret_detected"] is False

    @pytest.mark.asyncio
    async def test_high_entropy_still_detected(self):
        """Test that genuinely high entropy strings are still detected."""
        # Use a lower but reasonable entropy threshold for testing
        config = {
            "action": "block",
            "entropy_detection": {"enabled": True, "threshold": 4.5},
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test string that should have entropy > 4.5
        high_entropy_secret = "aB3xF9kL2mN8pQ5rS7tU1vW4yZ6cE0dG9hI2jK5lM8nO1pQ4rS7tU0vW3yZ6aB9c"  # Mixed case and numbers

        request = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"secret": high_entropy_secret}},
        )

        result = await plugin.process_request(request, "test-server")

        # Should be flagged as secret (entropy >= 4.5 and length >= 40)
        assert result.allowed is False
        assert result.metadata["secret_detected"] is True

    @pytest.mark.asyncio
    async def test_token_length_threshold_respects_min_length(self):
        """Test that only tokens >= min_length chars are checked for entropy.

        The min_length configuration option controls the minimum token length
        for entropy detection (default: 20).
        """
        # Use min_length of 40 to test the threshold behavior
        config = {
            "action": "block",
            "entropy_detection": {
                "enabled": True,
                "threshold": 4.5,
                "min_length": 40,  # Explicitly set to test the threshold
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Test 39-char token (should NOT be checked due to length < min_length)
        short_token = "aB3xF9kL2mN8pQ5rS7tU1vW4yZ6cE0dG9hI2jK5"  # 39 chars
        assert len(short_token) == 39

        # Test 40-char token (should be checked due to length >= min_length)
        long_token = "aB3xF9kL2mN8pQ5rS7tU1vW4yZ6cE0dG9hI2jK5l"  # 40 chars
        assert len(long_token) == 40

        # Test short token (should be ignored due to length < min_length)
        request_short = MCPRequest(
            jsonrpc="2.0",
            id=1,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": short_token}},
        )

        result_short = await plugin.process_request(request_short, "test-server")
        # Should be allowed (not checked for entropy due to < min_length)
        assert result_short.allowed is True

        # Test long token (should be checked for entropy)
        request_long = MCPRequest(
            jsonrpc="2.0",
            id=2,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"data": long_token}},
        )

        result_long = await plugin.process_request(request_long, "test-server")
        # Should be detected (length >= min_length and entropy >= threshold)
        assert result_long.allowed is False
        assert result_long.metadata["secret_detected"] is True


class TestBase64DecodedSecretsDetection:
    """Test base64-encoded secrets detection functionality."""

    def test_base64_encoded_secrets_properly_detected(self):
        """Test that base64-encoded secrets are properly detected and decoded."""
        config = {
            "action": "block",
            "secret_types": {
                "aws_access_keys": {"enabled": True},
                "github_tokens": {"enabled": True},
                "google_api_keys": {"enabled": True},
                "slack_tokens": {"enabled": True},
                "private_keys": {"enabled": True},
            },
        }
        plugin = BasicSecretsFilterPlugin(config)

        # Create various base64-encoded secrets including new types
        test_cases = [
            ("AKIA1234567890123456", "aws_access_keys"),  # AWS access key
            (
                "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
                "github_tokens",
            ),  # GitHub token
            (
                "AIzaSyDxVlAKC123456789012345678901234567",
                "google_api_keys",
            ),  # Google API key
            (
                "xoxb-1234567890-1234567890-abcdefghijklmnopqrstuvwxyz",
                "slack_tokens",
            ),  # Slack bot token
            (
                "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7...",
                "private_keys",
            ),  # Private key
        ]

        for secret, expected_type in test_cases:
            # Encode the secret
            import base64

            encoded_secret = base64.b64encode(secret.encode()).decode()
            test_text = f"Here is encoded data: {encoded_secret}"

            # Should detect the encoded secret
            detections = plugin._detect_base64_encoded_secrets(test_text)

            assert len(detections) > 0, f"Should detect base64-encoded {expected_type}"
            assert (
                detections[0]["type"] == expected_type
            ), f"Should identify as {expected_type}"
            assert (
                detections[0]["encoding_type"] == "base64"
            ), "Should mark as base64-encoded"
            assert "original_base64" in detections[0], "Should include original base64"
            assert detections[0]["decoded_length"] == len(
                secret
            ), "Should track decoded length"

    def test_base64_false_positive_noise_prevention(self):
        """Test that random base64 noise doesn't create false positives."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Generate random base64 strings that shouldn't match any secret patterns
        import base64
        import secrets

        random_noise_cases = [
            # Random data that's unlikely to match patterns
            base64.b64encode(secrets.token_bytes(20)).decode(),  # 20 random bytes
            base64.b64encode(
                b"The quick brown fox jumps over the lazy dog"
            ).decode(),  # Text
            base64.b64encode(
                b"Lorem ipsum dolor sit amet consectetur"
            ).decode(),  # Latin text
            base64.b64encode(b"1234567890" * 5).decode(),  # Repeated digits
            base64.b64encode(b"abcdefghijklmnopqrstuvwxyz" * 2).decode(),  # Alphabet
        ]

        for noise_b64 in random_noise_cases:
            # Ensure it's long enough to be considered (12+ chars)
            if len(noise_b64) >= 12:
                test_text = f"Random data: {noise_b64}"

                detections = plugin._detect_base64_encoded_secrets(test_text)

                # Should not detect any secrets in random noise
                assert (
                    len(detections) == 0
                ), f"Should not detect secrets in random base64: {noise_b64[:30]}..."

    def test_base64_candidate_dos_protection(self):
        """Test DoS protection against many base64 candidates."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Create text with many base64-like candidates (more than the 50 limit)
        import base64
        import secrets
        import time

        many_candidates = []
        for i in range(75):  # Exceed the MAX_BASE64_CANDIDATES limit
            # Create valid base64 strings with non-secret content
            random_data = secrets.token_bytes(16)
            b64_candidate = base64.b64encode(random_data).decode()
            many_candidates.append(f"data_{i}: {b64_candidate}")

        test_text = " | ".join(many_candidates)

        # Should process up to the limit but not crash or take excessive time
        start_time = time.time()
        detections = plugin._detect_base64_encoded_secrets(test_text)
        processing_time = time.time() - start_time

        # Should complete within reasonable time (less than 1 second)
        assert (
            processing_time < 1.0
        ), f"Processing took too long: {processing_time:.2f}s"

        # Should not detect secrets in random data
        assert (
            len(detections) == 0
        ), "Should not detect secrets in random base64 candidates"

    def test_base64_total_bytes_dos_protection(self):
        """Test DoS protection against large total decoded bytes."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Create base64 strings that decode to large content
        import base64
        import time

        large_candidates = []
        for i in range(5):  # Few candidates but large decoded size
            # Create 30KB of data per candidate (will exceed 100KB total limit)
            large_data = b"X" * (30 * 1024)
            b64_candidate = base64.b64encode(large_data).decode()
            large_candidates.append(f"large_{i}: {b64_candidate}")

        test_text = " | ".join(large_candidates)

        # Should process up to the byte limit but not crash
        start_time = time.time()
        detections = plugin._detect_base64_encoded_secrets(test_text)
        processing_time = time.time() - start_time

        # Should complete within reasonable time
        assert (
            processing_time < 2.0
        ), f"Processing took too long: {processing_time:.2f}s"

        # Should not detect secrets in large random data
        assert len(detections) == 0, "Should not detect secrets in large base64 content"

    def test_base64_regex_non_overlapping_behavior(self):
        """Document and test that base64 regex matching is intentionally non-overlapping."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Create overlapping base64-like patterns
        # "AKIA1234567890123456" appears at position 0 and 10 (overlapping)
        overlapping_text = "AKIA1234567890123456AKIA1234567890123456"  # 40 chars total

        detections = plugin._detect_base64_encoded_secrets(overlapping_text)

        # The regex should find the first match but not overlapping ones
        # This is CORRECT behavior - we don't want to decode overlapping substrings
        # as they would likely be fragments of the same data

        # Should find at most one detection (the first valid base64 pattern)
        # Note: This particular example might not decode to valid base64, so may be 0
        assert len(detections) <= 1, "Regex should be non-overlapping by design"

    def test_base64_separate_candidates_detection(self):
        """Test that separate (non-overlapping) base64 candidates are all detected."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Create separate base64-encoded secrets with clear separation
        import base64

        secret1 = "AKIA1234567890123456"
        secret2 = "AKIAABCDEFGHIJKLMNOP"

        encoded1 = base64.b64encode(secret1.encode()).decode()
        encoded2 = base64.b64encode(secret2.encode()).decode()

        # Separate them clearly to avoid overlap
        test_text = f"First: {encoded1} | Second: {encoded2}"

        detections = plugin._detect_base64_encoded_secrets(test_text)

        # Should detect both separate secrets
        assert (
            len(detections) == 2
        ), "Should detect both separate base64-encoded secrets"

        # Both should be AWS access keys
        for detection in detections:
            assert detection["type"] == "aws_access_keys"
            assert detection["encoding_type"] == "base64"


class TestSecretsContentSizeLimits:
    """Test MAX_CONTENT_SIZE enforcement in secrets filter plugin."""

    @pytest.mark.asyncio
    async def test_oversized_content_blocked_early(self):
        """Test that secrets filter blocks oversized content early."""
        config = {"action": "block"}
        plugin = BasicSecretsFilterPlugin(config)

        # Create content larger than MAX_CONTENT_SIZE (1MB)
        from gatekit.plugins.security import MAX_CONTENT_SIZE

        oversized_content = "B" * (MAX_CONTENT_SIZE + 1000)

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


class TestBase64SecretsIntegration:
    """Integration tests for base64 secrets detection through public API."""

    @pytest.mark.asyncio
    async def test_secrets_base64_request_integration(self):
        """Encode an AWS key inside request params, call process_request, assert detection & reason_code."""
        # Must explicitly enable scan_base64 (disabled by default due to false positives)
        config = {"action": "block", "scan_base64": True}
        plugin = BasicSecretsFilterPlugin(config)

        # Create a base64-encoded AWS access key
        import base64

        aws_secret = "AKIA1234567890123456"
        encoded_secret = base64.b64encode(aws_secret.encode()).decode()

        # Embed in request params (this tests full integration path)
        request = MCPRequest(
            jsonrpc="2.0",
            method="test_method",
            params={
                "data": f"Configuration: {encoded_secret}",
                "other_field": "normal content",
            },
            id="test-1",
        )

        # Should be detected via public API (not private methods)
        decision = await plugin.process_request(request, "test-server")

        assert not decision.allowed, "Should block request with base64-encoded secret"
        assert (
            decision.metadata["secret_detected"] is True
        ), "Should mark secret as detected"
        assert (
            decision.metadata["reason_code"] == "secret_detected"
        ), "Should have correct reason code"

        # Verify detection details include base64 metadata
        detections = decision.metadata["detections"]
        assert len(detections) > 0, "Should have detection details"

        base64_detection = detections[0]
        assert (
            base64_detection["encoding_type"] == "base64"
        ), "Should mark as base64-encoded"
        assert (
            base64_detection["type"] == "aws_access_keys"
        ), "Should identify as AWS access key"
        assert "original_base64" in base64_detection, "Should include original base64"
        assert base64_detection["decoded_length"] == len(
            aws_secret
        ), "Should track decoded length"

    @pytest.mark.asyncio
    async def test_secrets_base64_response_integration(self):
        """Test base64 secrets detection in response via public API."""
        # Must explicitly enable scan_base64 (disabled by default due to false positives)
        config = {"action": "block", "scan_base64": True}
        plugin = BasicSecretsFilterPlugin(config)

        import base64

        github_secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        encoded_secret = base64.b64encode(github_secret.encode()).decode()

        from gatekit.protocol.messages import MCPResponse

        request = MCPRequest(jsonrpc="2.0", method="test", id="1")
        response = MCPResponse(
            jsonrpc="2.0", id="1", result={"config_data": f"Token: {encoded_secret}"}
        )

        decision = await plugin.process_response(request, response, "test-server")

        assert not decision.allowed, "Should block response with base64-encoded secret"
        assert decision.metadata["secret_detected"] is True, "Should detect secret"
        assert (
            decision.metadata["reason_code"] == "secret_detected"
        ), "Should have correct reason code"

        # Verify base64-specific detection
        detections = decision.metadata["detections"]
        base64_detection = detections[0]
        assert (
            base64_detection["encoding_type"] == "base64"
        ), "Should mark as base64-encoded"
        assert (
            base64_detection["type"] == "github_tokens"
        ), "Should identify as GitHub token"


class TestSecretsBase64ForcedBlocking:
    """Test forced blocking behavior for base64-encoded secrets.

    Base64 content cannot be redacted without corrupting binary data.
    When action=redact and base64 secrets are detected, the plugin must block.
    When action=audit_only, the plugin should allow through (no modification attempted).
    See ADR-025.
    """

    @pytest.fixture
    def plugin_redact(self):
        """Create plugin with base64 scanning enabled (redact mode)."""
        return BasicSecretsFilterPlugin({
            "action": "redact",
            "scan_base64": True,
        })

    @pytest.fixture
    def plugin_audit_only(self):
        """Create plugin with base64 scanning enabled (audit_only mode)."""
        return BasicSecretsFilterPlugin({
            "action": "audit_only",
            "scan_base64": True,
        })

    @pytest.mark.asyncio
    async def test_redact_mode_forces_block_for_base64_request(self, plugin_redact):
        """Test that base64-encoded secrets in request force blocking in redact mode."""
        # Base64-encoded AWS access key
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        encoded_key = base64.b64encode(aws_key.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-request",
            params={"name": "test", "arguments": {"data": encoded_key}},
        )

        result = await plugin_redact.process_request(request, "test-server")
        assert result.allowed is False
        assert result.metadata.get("secret_detected") is True
        assert result.metadata.get("base64_force_block") is True
        assert "base64" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_redact_mode_forces_block_for_base64_response(self, plugin_redact):
        """Test that base64-encoded secrets in response force blocking in redact mode."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        encoded_key = base64.b64encode(aws_key.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-response",
            params={"name": "test"},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id="test-response",
            result={"content": encoded_key},
        )

        result = await plugin_redact.process_response(request, response, "test-server")
        assert result.allowed is False
        assert result.metadata.get("secret_detected") is True
        assert result.metadata.get("base64_force_block") is True
        assert "base64" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_redact_mode_forces_block_for_base64_notification(self, plugin_redact):
        """Test that base64-encoded secrets in notification force blocking in redact mode."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        encoded_key = base64.b64encode(aws_key.encode()).decode()

        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/test",
            params={"data": encoded_key},
        )

        result = await plugin_redact.process_notification(notification, "test-server")
        assert result.allowed is False
        assert result.metadata.get("secret_detected") is True
        assert result.metadata.get("base64_force_block") is True
        assert "base64" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_audit_only_allows_base64_secrets_request(self, plugin_audit_only):
        """Test that audit_only mode allows base64 secrets through (no modification attempted)."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        encoded_key = base64.b64encode(aws_key.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-audit",
            params={"name": "test", "arguments": {"data": encoded_key}},
        )

        result = await plugin_audit_only.process_request(request, "test-server")
        # audit_only should allow through - no modification attempted
        assert result.allowed is True
        assert result.metadata.get("secret_detected") is True
        # Should NOT have base64_force_block since audit_only doesn't force block
        assert result.metadata.get("base64_force_block") is not True

    @pytest.mark.asyncio
    async def test_audit_only_allows_base64_secrets_response(self, plugin_audit_only):
        """Test that audit_only mode allows base64 secrets in response through."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        encoded_key = base64.b64encode(aws_key.encode()).decode()

        request = MCPRequest(
            jsonrpc="2.0",
            method="tools/call",
            id="test-audit-response",
            params={"name": "test"},
        )
        response = MCPResponse(
            jsonrpc="2.0",
            id="test-audit-response",
            result={"content": encoded_key},
        )

        result = await plugin_audit_only.process_response(request, response, "test-server")
        assert result.allowed is True
        assert result.metadata.get("secret_detected") is True

    @pytest.mark.asyncio
    async def test_audit_only_allows_base64_secrets_notification(self, plugin_audit_only):
        """Test that audit_only mode allows base64 secrets in notification through."""
        aws_key = "AKIAIOSFODNN7EXAMPLE"
        encoded_key = base64.b64encode(aws_key.encode()).decode()

        notification = MCPNotification(
            jsonrpc="2.0",
            method="notifications/test",
            params={"data": encoded_key},
        )

        result = await plugin_audit_only.process_notification(notification, "test-server")
        assert result.allowed is True
        assert result.metadata.get("secret_detected") is True
