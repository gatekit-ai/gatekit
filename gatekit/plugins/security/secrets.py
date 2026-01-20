"""Basic Secrets Filter security plugin implementation.

⚠️  WARNING: This plugin provides only basic secrets protection and is NOT suitable
for production use. It uses simple regex patterns and entropy analysis which can be
bypassed. For production environments, implement enterprise-grade secret detection solutions.

This module provides a security plugin that detects and filters well-known
secrets, tokens, and credentials across all MCP communications using
high-confidence regex patterns and conservative entropy analysis.

The plugin supports:
- AWS Access Keys (AKIA-prefixed patterns)
- GitHub Tokens (ghp_, gho_, ghu_, ghs_, ghr_ prefixes)
- Google API Keys (AIza-prefixed patterns)
- JWT Tokens (three-part base64url structure)
- OpenAI API Keys (sk-, sk-proj-, sk-admin- prefixes)
- Slack Tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs- prefixes)
- SSH Private Keys (PEM format headers)
- Base64-encoded secrets (12+ characters, with DoS protection)
- Conservative Shannon entropy detection

NOTE: This plugin uses regex patterns, entropy analysis, and base64 decoding for secret detection.
Base64 decoding includes safeguards: candidate limits (50 max), size limits (100KB total decoded),
and skips data URLs to avoid false positives on legitimate file content.

While effective for well-known secret formats, it may not catch:
- Secrets in novel or proprietary formats
- Non-base64 encoded or obfuscated secrets (ROT13, custom encoding, etc.)
- Secrets split across multiple fields
- Context-dependent credentials
- High-entropy strings with special characters (e.g., `aB3$xK9@mN2!`) - special chars
  fragment tokens below the min_length threshold, bypassing entropy detection

The entropy detection is conservative to minimize false positives. Consider
adjusting entropy thresholds based on your security requirements.
"""

import logging
import re
import json
import math
import copy
from typing import Dict, Any, List
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.utils.encoding import is_data_url

logger = logging.getLogger(__name__)


class BasicSecretsFilterPlugin(SecurityPlugin):
    """Security plugin that detects and filters secrets using high-confidence patterns and entropy analysis."""

    # Secret type identifiers and display names
    # NOTE: aws_secret_keys was removed due to high false positive rate on file paths.
    # The pattern [A-Za-z0-9+/]{40} matches too many legitimate strings.
    # Consider re-adding with context-based detection (e.g., require "aws" keyword nearby).
    SECRET_TYPES = {
        "aws_access_keys": "AWS Keys",
        "github_tokens": "GitHub",
        "google_api_keys": "Google API",
        "jwt_tokens": "JWT",
        "openai_api_keys": "OpenAI",
        "slack_tokens": "Slack",
        "ssh_private_keys": "SSH Keys",
        "private_keys": "Private Keys",
    }

    # Note: action enum validation is handled by JSON schema

    # TUI Display Metadata
    DISPLAY_NAME = "Basic Secrets Filter"
    DESCRIPTION = "Basic pattern-based secrets detection. Not suitable for production use - can be bypassed with encoding or obfuscation."
    DISPLAY_SCOPE = "global"

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        """Generate status description from secrets filter configuration."""
        if not config or not config.get("enabled", False):
            return "Disabled"

        action = config.get("action", "redact")
        secret_types = config.get("secret_types", {})

        # Count enabled secret types using constants
        # Per ADR-024: unspecified types default to enabled (except private_keys)
        enabled = []
        for secret_type, display_name in cls.SECRET_TYPES.items():
            # private_keys defaults to False due to high false positive rate
            default_enabled = secret_type != "private_keys"
            if secret_types.get(secret_type, {}).get("enabled", default_enabled):
                enabled.append(display_name)

        entropy_detection = config.get("entropy_detection", {})
        if entropy_detection.get("enabled", False):
            enabled.append("Entropy")

        if config.get("scan_base64", False):
            enabled.append("Base64")

        if not enabled:
            return "No detection types configured"
        else:
            return f"{action.title()}: {', '.join(enabled)}"

    @classmethod
    def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
        """Return actions based on configuration state."""
        if config and config.get("enabled", False):
            return ["Configure", "Test"]
        return ["Setup"]

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for Secrets Filter configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/secrets-filter.json",
            "type": "object",
            "description": "Secrets Filter security plugin configuration",
            "$defs": {
                "secretTypeConfig": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean", "default": True}},
                    "additionalProperties": False,
                }
            },
            "properties": {
                # Note: enabled and priority are injected by framework
                # See gatekit/config/framework_fields.py
                "action": {
                    "type": "string",
                    "title": "Action on Detection",
                    "enum": ["block", "redact", "audit_only"],
                    "x-enum-labels": {
                        "block": "Block",
                        "redact": "Redact",
                        "audit_only": "Audit Only",
                    },
                    "description": (
                        "• Block: Reject request/response (usually appears to the MCP Client as an error)\n"
                        "• Redact: Replace secrets with placeholders\n"
                        "• Audit Only: Log detection but allow through"
                    ),
                    "default": "redact",
                },
                "secret_types": {
                    "type": "object",
                    "title": "Secret Types",
                    "description": "Secret detection types configuration",
                    "properties": {
                        **{
                            secret_type: {
                                "title": display_name,
                                "$ref": "#/$defs/secretTypeConfig",
                            }
                            for secret_type, display_name in cls.SECRET_TYPES.items()
                            if secret_type != "private_keys"
                        },
                        # private_keys defaults to False due to high false positive rate
                        "private_keys": {
                            "title": cls.SECRET_TYPES.get("private_keys", "Private Keys"),
                            "type": "object",
                            "properties": {
                                "enabled": {"type": "boolean", "default": False}
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
                "entropy_detection": {
                    "type": "object",
                    "title": "Entropy Detection",
                    "description": "Detect high-entropy strings that may be secrets.",
                    "properties": {
                        "enabled": {
                            "type": "boolean",
                            "description": "Enable entropy detection",
                            "default": False,
                        },
                        "threshold": {
                            "type": "number",
                            "description": "Minimum entropy to flag. Higher = fewer false positives. Range: 4.0-5.0. Values below 5.0 are likely to produce false positives on typical MCP traffic.",
                            "default": 5.0,
                            "minimum": 4.0,
                            "maximum": 5.0,
                        },
                        "min_length": {
                            "type": "integer",
                            "description": "Minimum string length (only used when enabled)",
                            "default": 20,
                            "minimum": 10,
                        },
                    },
                    "additionalProperties": False,
                },
                "scan_base64": {
                    "type": "boolean",
                    "title": "Decode and scan base64-encoded content (blocks even on action=redact)",
                    "description": "When enabled, base64-encoded strings are decoded and scanned for secret patterns. Note: base64 content cannot be redacted (would corrupt data), so redact mode forces blocking for base64 detections.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        }

    def _validate_configuration(self, config: Dict[str, Any]) -> None:
        """Validate configuration against supported options.

        Note: action enum validation is handled by JSON schema.
        """
        # Validate secret types (business logic - not in schema)
        secret_types = config.get("secret_types", {})
        for secret_type in secret_types.keys():
            if secret_type not in self.SECRET_TYPES:
                raise ValueError(
                    f"Unsupported secret type '{secret_type}'. Must be one of: {', '.join(self.SECRET_TYPES.keys())}"
                )

    def __init__(self, config: Dict[str, Any]):
        """Initialize plugin with configuration."""
        # Validate configuration type first
        if not isinstance(config, dict):
            raise TypeError("Configuration must be a dictionary")

        # Initialize base class to set priority
        super().__init__(config)

        # Validate configuration against supported options
        self._validate_configuration(config)

        self.action = config.get("action", "redact")

        # Initialize secret types with defaults based on constants
        default_secret_types = {}
        for secret_type in self.SECRET_TYPES.keys():
            if secret_type == "private_keys":
                default_secret_types[secret_type] = {
                    "enabled": False
                }  # Higher false positive risk
            else:
                default_secret_types[secret_type] = {"enabled": True}

        # Get secret types from config
        self.secret_types = config.get("secret_types", {})
        # Merge with defaults
        for secret_type, default_config in default_secret_types.items():
            if secret_type not in self.secret_types:
                self.secret_types[secret_type] = default_config

        # Initialize entropy detection - disabled by default due to false positives
        default_entropy = {
            "enabled": False,
            "threshold": 5.0,  # Most relaxed threshold (higher = fewer false positives)
            "min_length": 20,
        }

        self.entropy_detection = config.get("entropy_detection", default_entropy)
        # Merge with defaults
        for key, default_value in default_entropy.items():
            if key not in self.entropy_detection:
                self.entropy_detection[key] = default_value

        # Initialize base64 scanning - disabled by default due to false positives on images/files
        self.scan_base64 = config.get("scan_base64", False)

        # Compile regex patterns for performance
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for performance."""
        self.compiled_patterns = {}

        # High-confidence secret patterns mapped to constants
        # NOTE: aws_secret_keys pattern was removed - too many false positives on file paths
        secret_patterns = {
            "aws_access_keys": r"AKIA[0-9A-Z]{16}",
            "github_tokens": r"gh[pousrp]_[0-9a-zA-Z]{36}",
            "google_api_keys": r"AIza[0-9A-Za-z\-_]{35}",
            "jwt_tokens": r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+",
            "openai_api_keys": r"sk-(?:proj-|admin-)?[a-zA-Z0-9_-]{20,}",  # OpenAI API keys (sk-, sk-proj-, sk-admin-)
            "ssh_private_keys": r"-----BEGIN (?:RSA|DSA|EC|OPENSSH) PRIVATE KEY-----",  # SSH-specific private keys
            "slack_tokens": r"xox[bpars]-[0-9a-zA-Z\-]{10,}",  # Slack tokens (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-)
            "private_keys": r"-----BEGIN (?:ENCRYPTED )?PRIVATE KEY-----",  # General private keys (PKCS#8 format)
        }

        # Only compile patterns for enabled secret types that we have patterns for
        for secret_type in self.SECRET_TYPES.keys():
            if (
                self.secret_types.get(secret_type, {}).get("enabled", False)
                and secret_type in secret_patterns
            ):
                try:
                    self.compiled_patterns[secret_type] = re.compile(
                        secret_patterns[secret_type]
                    )
                except re.error as e:
                    logger.warning(f"Invalid regex pattern for {secret_type}: {e}")

    def _calculate_entropy(self, data: str) -> float:
        """Calculate Shannon entropy for potential secret detection."""
        if len(data) < self.entropy_detection["min_length"]:
            return 0.0

        entropy = 0.0
        data_len = len(data)

        # Count frequency of each character
        char_counts = {}
        for char in data:
            char_counts[char] = char_counts.get(char, 0) + 1

        # Calculate entropy
        for count in char_counts.values():
            probability = count / data_len
            if probability > 0:
                entropy += -probability * math.log2(probability)

        return entropy

    def _is_likely_base64_data(self, text: str) -> bool:
        """Heuristic to identify base64 encoded data that is likely file content, not secrets.

        This method is used to skip entropy detection on legitimate base64 file data
        to reduce false positives. The plugin separately handles base64 secret detection
        via the _detect_base64_encoded_secrets() method.

        Note: This heuristic is for entropy detection only. Base64 secret detection
        is handled separately with proper decoding and pattern matching.
        """
        # Check if it's a data URL (files embedded in responses)
        if is_data_url(text):
            return True

        # Skip short strings - they're more likely to be actual tokens
        if len(text) <= 100:
            return False

        # If it looks like base64 and is very long, it's probably file data
        if (
            re.match(r"^[A-Za-z0-9+/]*={0,2}$", text)
            and len(text) % 4 == 0
            and len(text) > 500
        ):
            return True

        return False

    def _is_potential_secret_by_entropy(self, text: str) -> bool:
        """Determine if text might be a secret based on conservative entropy thresholds."""
        if not self.entropy_detection["enabled"]:
            return False

        min_length = self.entropy_detection["min_length"]
        threshold = self.entropy_detection["threshold"]

        # Check minimum length constraint (keep reasonable minimum to avoid false positives)
        # No maximum length limit - analyze all content regardless of size
        if len(text) < min_length:
            return False

        # Additional heuristics to reduce false positives
        if self._is_likely_base64_data(text):
            return False

        # Calculate entropy
        entropy = self._calculate_entropy(text)
        return entropy >= threshold

    def _detect_secrets_in_text(self, text: str) -> List[Dict[str, Any]]:
        """Detect secrets in a text string."""
        detections = []

        # Handle data URLs specially: check the URL itself but skip encoded content
        if is_data_url(text):
            # Extract the data URL prefix (before the base64 content) for pattern matching
            parts = text.split(",", 1)
            if len(parts) >= 1:
                # Check the data URL schema/MIME type part for patterns
                url_prefix = parts[0]
                prefix_detections = self._detect_secrets_in_text_content(url_prefix)
                detections.extend(prefix_detections)

            # Skip the base64 content portion - it's likely legitimate file data
            return detections

        # For non-data URLs, do normal detection
        return self._detect_secrets_in_text_content(text)

    def _detect_secrets_in_text_content(self, text: str) -> List[Dict[str, Any]]:
        """Core secret detection logic for text content."""
        detections = []

        # Check high-confidence patterns
        for secret_type, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                detection = {
                    "type": secret_type.replace("custom_", ""),
                    "pattern": (
                        "standard"
                        if not secret_type.startswith("custom_")
                        else "custom"
                    ),
                    "position": [match.start(), match.end()],
                    "action": self.action,
                    "confidence": "high",
                }
                detections.append(detection)

        # Check entropy-based detection for longer strings
        # Run alongside pattern detection (not as fallback) to catch unknown high-entropy secrets
        if self.entropy_detection["enabled"]:
            # Split text into potential secret-like tokens
            # Use negative lookbehind (?<!\\) to avoid matching chars after JSON escape sequences
            # (e.g., the 'n' in '\n' should not start a token, as this corrupts JSON during redaction)
            min_len = self.entropy_detection.get("min_length", 20)
            tokens = re.findall(
                rf"(?<!\\)[A-Za-z0-9+/=_-]{{{min_len},200}}", text
            )
            for token in tokens:
                if self._is_potential_secret_by_entropy(token):
                    start_pos = text.find(token)

                    # Skip tokens that are part of data URLs embedded in the text
                    # Look for "data:...;base64," pattern immediately before the token
                    prefix_start = max(0, start_pos - 100)
                    prefix_text = text[prefix_start:start_pos]
                    if re.search(r"data:[^;]*;base64,$", prefix_text):
                        continue  # This is the content portion of a data URL, skip it

                    # Avoid duplicate detection if token overlaps with pattern-based detection
                    is_duplicate = any(
                        d["position"][0] <= start_pos < d["position"][1]
                        or d["position"][0] < start_pos + len(token) <= d["position"][1]
                        for d in detections
                    )
                    if not is_duplicate:
                        detection = {
                            "type": "entropy_based",
                            "entropy_score": self._calculate_entropy(token),
                            "position": [start_pos, start_pos + len(token)],
                            "action": self.action,
                            "confidence": "medium",
                        }
                        detections.append(detection)

        # Check base64-encoded secrets (12+ characters) - only if enabled
        if self.scan_base64:
            base64_detections = self._detect_base64_encoded_secrets(text)
            detections.extend(base64_detections)

        return detections

    def _detect_base64_encoded_secrets(self, text: str) -> List[Dict[str, Any]]:
        """Detect secrets in base64-encoded content (12+ characters as per requirements).

        This method finds potential base64 strings, decodes them safely, and scans
        the decoded content for secret patterns. Implements requirement for base64
        secrets detection with minimum 12 character length.

        DoS Protection: Limits the number of base64 candidates processed to prevent
        attacks using many base64-like strings that could cause excessive decode operations.
        """
        from gatekit.utils.encoding import safe_decode_base64

        detections = []
        total_decoded_bytes = 0
        candidates_processed = 0

        # DoS protection: Limit base64 candidates to prevent time/memory exhaustion
        MAX_BASE64_CANDIDATES = 50  # Reasonable limit for legitimate content
        MAX_TOTAL_DECODED_BYTES = 100 * 1024  # 100KB total across all candidates

        # Find base64-like strings that are 12+ characters long (including padding)
        # Use word boundaries but make sure padding characters are included
        # Note: Regex is non-overlapping by design, which is correct behavior
        base64_pattern = re.compile(
            r"\b[A-Za-z0-9+/]{12,}={0,2}(?=\s|$|[^A-Za-z0-9+/=])"
        )

        for match in base64_pattern.finditer(text):
            base64_candidate = match.group()

            # DoS protection: Stop processing if we've hit limits
            if candidates_processed >= MAX_BASE64_CANDIDATES:
                logger.warning(
                    f"Base64 candidate limit reached ({MAX_BASE64_CANDIDATES}), skipping remaining candidates"
                )
                break

            if total_decoded_bytes >= MAX_TOTAL_DECODED_BYTES:
                logger.warning(
                    f"Total decoded bytes limit reached ({MAX_TOTAL_DECODED_BYTES}), skipping remaining candidates"
                )
                break

            candidates_processed += 1

            # Additional validation: must be proper base64 length (multiple of 4)
            if len(base64_candidate) % 4 != 0:
                continue

            # Skip if the full text is a data URL (handled separately by _detect_secrets_in_text)
            if is_data_url(text):
                continue

            # Skip if this base64 candidate appears to be part of a data URL
            # Look for "data:...;base64," pattern immediately before the candidate
            start_pos = match.start()
            prefix_start = max(0, start_pos - 100)  # Look back up to 100 chars
            prefix_text = text[prefix_start:start_pos]
            if re.search(r"data:[^;]*;base64,$", prefix_text):
                continue  # This is likely part of a data URL, skip it

            # Attempt safe base64 decoding
            decoded_content = safe_decode_base64(
                base64_candidate, max_decode_size=10240
            )

            if (
                decoded_content and len(decoded_content) >= 5
            ):  # Must decode to something meaningful
                # Track total decoded bytes for DoS protection
                total_decoded_bytes += len(decoded_content)

                # Scan decoded content for secrets using pattern detection only (no recursive base64)
                decoded_detections = self._detect_patterns_only(decoded_content)

                # Mark these detections as base64-encoded and adjust positions
                for detection in decoded_detections:
                    detection.update(
                        {
                            "encoding_type": "base64",
                            "base64_position": [match.start(), match.end()],
                            "original_base64": (
                                base64_candidate[:50] + "..."
                                if len(base64_candidate) > 50
                                else base64_candidate
                            ),
                            "decoded_length": len(decoded_content),
                        }
                    )
                    detections.append(detection)

        return detections

    def _detect_patterns_only(self, text: str) -> List[Dict[str, Any]]:
        """Detect secrets using pattern matching only (no base64 decoding or entropy).

        This method is used when scanning already-decoded base64 content to avoid
        recursive decoding and to focus on high-confidence pattern matches.
        """
        detections = []

        # Check high-confidence patterns only
        for secret_type, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(text):
                detection = {
                    "type": secret_type.replace("custom_", ""),
                    "pattern": (
                        "standard"
                        if not secret_type.startswith("custom_")
                        else "custom"
                    ),
                    "position": [match.start(), match.end()],
                    "action": self.action,
                    "confidence": "high",
                }
                detections.append(detection)

        return detections

    def _has_base64_detections(self, detections: List[Dict[str, Any]]) -> bool:
        """Check if any detections are from base64-encoded content.

        Base64-encoded content cannot be redacted - any modification corrupts
        the underlying binary data. Must block instead.
        """
        return any(d.get("encoding_type") == "base64" for d in detections)

    def _detect_secrets_in_request(self, request: MCPRequest) -> List[Dict[str, Any]]:
        """Detect secrets in an MCP request."""
        from gatekit.plugins.security import (
            MAX_CONTENT_SIZE,
            REASON_CONTENT_SIZE_EXCEEDED,
        )

        detections = []

        # Convert request params to JSON string for text analysis
        try:
            if request.params:
                request_text = json.dumps(request.params, default=str)

                # CRITICAL: Use byte length, not character count
                text_size_bytes = len(request_text.encode("utf-8"))
                if text_size_bytes > MAX_CONTENT_SIZE:
                    # Return a special detection that indicates size exceeded
                    return [
                        {
                            "type": "content_size_exceeded",
                            "size_bytes": text_size_bytes,
                            "max_size": MAX_CONTENT_SIZE,
                            "reason": f"Content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                            "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                        }
                    ]

                detections.extend(self._detect_secrets_in_text(request_text))
        except Exception as e:
            logger.warning(f"Error analyzing request for secrets: {e}")

        return detections

    def _redact_secrets_in_request(
        self, request: MCPRequest, detections: List[Dict[str, Any]]
    ) -> MCPRequest:
        """Create a redacted copy of the request."""
        redacted_request = copy.deepcopy(request)

        # Convert params to string, redact secrets, then parse back
        try:
            if redacted_request.params:
                request_text = json.dumps(redacted_request.params, default=str)

                # Sort detections by position (reverse order to maintain positions)
                sorted_detections = sorted(
                    detections, key=lambda x: x["position"][0], reverse=True
                )

                for detection in sorted_detections:
                    start, end = detection["position"]
                    if 0 <= start < end <= len(request_text):
                        request_text = (
                            request_text[:start]
                            + "[SECRET REDACTED by Gatekit]"
                            + request_text[end:]
                        )

                # Parse back to params object
                redacted_request.params = json.loads(request_text)

        except Exception as e:
            logger.warning(f"Error redacting secrets from request: {e}")

        return redacted_request

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Check if request should be allowed."""

        # Detect secrets
        detections = self._detect_secrets_in_request(request)

        # Check for content size exceeded (special case)
        if (
            detections
            and len(detections) == 1
            and detections[0].get("type") == "content_size_exceeded"
        ):
            size_detection = detections[0]
            return PluginResult(
                allowed=False,
                reason=size_detection["reason"],
                metadata={
                    "plugin": self.__class__.__name__,
                    "content_size_bytes": size_detection["size_bytes"],
                    "max_size": size_detection["max_size"],
                    "reason_code": size_detection["reason_code"],
                },
            )

        if not detections:
            from gatekit.plugins.security import REASON_NONE

            return PluginResult(
                allowed=True,
                reason="No secrets detected",
                metadata={
                    "plugin": self.__class__.__name__,
                    "secret_detected": False,
                    "reason_code": REASON_NONE,
                },
            )

        # Handle detections based on action mode
        from gatekit.plugins.security import REASON_SECRET_DETECTED

        # Check if any detections are from base64-encoded content
        # Base64 content cannot be redacted - force block instead of redact to avoid corruption
        has_base64 = self._has_base64_detections(detections)
        effective_action = "block" if (has_base64 and self.action == "redact") else self.action

        metadata = {
            "plugin": self.__class__.__name__,
            "secret_detected": True,
            "detection_mode": effective_action,
            "detections": detections,
            "reason_code": REASON_SECRET_DETECTED,
        }
        if has_base64 and self.action == "redact":
            metadata["base64_force_block"] = True

        if effective_action == "block":
            reason = f"Secret detected: {len(detections)} secret(s) found"
            if has_base64:
                reason = f"Secret detected in base64 content (blocking required): {len(detections)} secret(s) found"
            return PluginResult(
                allowed=False,
                reason=reason,
                metadata=metadata,
            )
        elif effective_action == "redact":
            redacted_request = self._redact_secrets_in_request(request, detections)
            return PluginResult(
                allowed=True,
                reason=f"Secret redacted: {len(detections)} secret(s) redacted",
                metadata=metadata,
                modified_content=redacted_request,
            )
        elif effective_action == "audit_only":
            return PluginResult(
                allowed=True,
                reason=f"Secret logged: {len(detections)} secret(s) detected and logged",
                metadata=metadata,
            )

        # Fallback (should not reach here)
        return PluginResult(
            allowed=False, reason="Unknown action mode", metadata=metadata
        )

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Check if response should be allowed."""
        from gatekit.plugins.security import (
            MAX_CONTENT_SIZE,
            REASON_CONTENT_SIZE_EXCEEDED,
        )

        # Convert response to text for analysis
        try:
            if response.result:
                response_text = json.dumps(response.result, default=str)

                # Check content size
                text_size_bytes = len(response_text.encode("utf-8"))
                if text_size_bytes > MAX_CONTENT_SIZE:
                    return PluginResult(
                        allowed=False,
                        reason=f"Response content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                        metadata={
                            "plugin": self.__class__.__name__,
                            "content_size_bytes": text_size_bytes,
                            "max_size": MAX_CONTENT_SIZE,
                            "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                        },
                    )

                detections = self._detect_secrets_in_text(response_text)
            else:
                detections = []
        except Exception as e:
            logger.warning(f"Error analyzing response for secrets: {e}")
            detections = []

        if not detections:
            from gatekit.plugins.security import REASON_NONE

            return PluginResult(
                allowed=True,
                reason="No secrets detected in response",
                metadata={
                    "plugin": self.__class__.__name__,
                    "secret_detected": False,
                    "reason_code": REASON_NONE,
                },
            )

        # Handle detections based on action mode
        from gatekit.plugins.security import REASON_SECRET_DETECTED

        # Check if any detections are from base64-encoded content
        # Base64 content cannot be redacted - force block instead of redact to avoid corruption
        has_base64 = self._has_base64_detections(detections)
        effective_action = "block" if (has_base64 and self.action == "redact") else self.action

        metadata = {
            "plugin": self.__class__.__name__,
            "secret_detected": True,
            "detection_mode": effective_action,
            "detections": detections,
            "reason_code": REASON_SECRET_DETECTED,
        }
        if has_base64 and self.action == "redact":
            metadata["base64_force_block"] = True

        if effective_action == "block":
            reason = f"Secret detected in response: {len(detections)} secret(s) found"
            if has_base64:
                reason = f"Secret detected in base64 content (blocking required): {len(detections)} secret(s) found"
            return PluginResult(
                allowed=False,
                reason=reason,
                metadata=metadata,
            )
        elif effective_action == "redact":
            # Create a redacted copy of the response
            try:
                response_text = json.dumps(response.result, default=str)

                # Sort detections by position (reverse order to maintain positions)
                sorted_detections = sorted(
                    detections, key=lambda x: x["position"][0], reverse=True
                )

                for detection in sorted_detections:
                    start, end = detection["position"]
                    if 0 <= start < end <= len(response_text):
                        response_text = (
                            response_text[:start]
                            + "[SECRET REDACTED by Gatekit]"
                            + response_text[end:]
                        )

                # Parse back to result object
                modified_result = json.loads(response_text)

                # Create modified response
                modified_response = MCPResponse(
                    jsonrpc=response.jsonrpc,
                    id=response.id,
                    result=modified_result,
                    error=response.error,
                    sender_context=response.sender_context,
                )

                return PluginResult(
                    allowed=True,
                    reason=f"Secret redacted from response: {len(detections)} secret(s) redacted",
                    metadata=metadata,
                    modified_content=modified_response,
                )

            except Exception as e:
                logger.warning(f"Error redacting secrets from response: {e}")
                # If redaction fails, fall back to blocking for security
                metadata["reason_code"] = REASON_SECRET_DETECTED
                return PluginResult(
                    allowed=False,
                    reason=f"Secret detected and redaction failed: {e}",
                    metadata=metadata,
                )

        elif effective_action == "audit_only":
            return PluginResult(
                allowed=True,
                reason=f"Secret logged: {len(detections)} secret(s) detected in response",
                metadata=metadata,
            )

        # Fallback (should not reach here)
        return PluginResult(
            allowed=False, reason="Unknown action mode", metadata=metadata
        )

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        """Check if notification contains secrets and apply configured action.

        Notifications can contain secrets in parameters or method names and should
        be checked with the same rigor as requests and responses.
        """
        from gatekit.plugins.security import (
            MAX_CONTENT_SIZE,
            REASON_CONTENT_SIZE_EXCEEDED,
        )

        detections = []

        # Check notification parameters for secrets
        try:
            if notification.params:
                notification_text = json.dumps(notification.params, default=str)

                # Check content size
                text_size_bytes = len(notification_text.encode("utf-8"))
                if text_size_bytes > MAX_CONTENT_SIZE:
                    return PluginResult(
                        allowed=False,
                        reason=f"Notification content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                        metadata={
                            "plugin": self.__class__.__name__,
                            "content_size_bytes": text_size_bytes,
                            "max_size": MAX_CONTENT_SIZE,
                            "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                        },
                    )

                detections.extend(self._detect_secrets_in_text(notification_text))

            # Also check method name for potential secrets (though less common)
            if notification.method:
                method_detections = self._detect_secrets_in_text(notification.method)
                # Adjust detections to indicate they came from the method field
                for detection in method_detections:
                    detection["field"] = "method"
                detections.extend(method_detections)
        except Exception as e:
            logger.warning(f"Error analyzing notification for secrets: {e}")

        # Generate decision based on action mode
        if not detections:
            from gatekit.plugins.security import REASON_NONE

            return PluginResult(
                allowed=True,
                reason="No secrets detected in notification",
                metadata={
                    "plugin": self.__class__.__name__,
                    "secret_detected": False,
                    "detection_mode": self.action,
                    "detections": [],
                    "reason_code": REASON_NONE,
                },
            )

        # Decide based on action mode
        from gatekit.plugins.security import REASON_SECRET_DETECTED

        # Check if any detections are from base64-encoded content
        # Base64 content cannot be redacted - force block instead of redact to avoid corruption
        has_base64 = self._has_base64_detections(detections)
        effective_action = "block" if (has_base64 and self.action == "redact") else self.action

        # Prepare metadata
        metadata = {
            "plugin": self.__class__.__name__,
            "secret_detected": True,
            "detection_mode": effective_action,
            "detections": detections,
            "notification_method": notification.method,
            "reason_code": REASON_SECRET_DETECTED,
        }
        if has_base64 and self.action == "redact":
            metadata["base64_force_block"] = True

        if effective_action == "block":
            reason = "Secrets detected in notification - blocking transmission"
            if has_base64:
                reason = "Secrets detected in base64 content in notification (blocking required)"
            return PluginResult(
                allowed=False,
                reason=reason,
                metadata=metadata,
            )
        elif effective_action == "redact":
            # Create a redacted copy of the notification
            try:
                notification_text = (
                    json.dumps(notification.params, default=str)
                    if notification.params
                    else ""
                )

                # Sort detections by position (reverse order to maintain positions)
                sorted_detections = sorted(
                    detections, key=lambda x: x["position"][0], reverse=True
                )

                for detection in sorted_detections:
                    start, end = detection["position"]
                    if 0 <= start < end <= len(notification_text):
                        notification_text = (
                            notification_text[:start]
                            + "[SECRET REDACTED by Gatekit]"
                            + notification_text[end:]
                        )

                # Parse back to params object
                modified_params = (
                    json.loads(notification_text) if notification_text else None
                )

                # Create modified notification
                modified_notification = MCPNotification(
                    jsonrpc=notification.jsonrpc,
                    method=notification.method,
                    params=modified_params,
                )

                return PluginResult(
                    allowed=True,
                    reason=f"Secrets redacted from notification: {len(detections)} secret(s) redacted",
                    metadata=metadata,
                    modified_content=modified_notification,
                )

            except Exception as e:
                logger.warning(f"Error redacting secrets from notification: {e}")
                # If redaction fails, fall back to blocking for security
                return PluginResult(
                    allowed=False,
                    reason=f"Secret detected and redaction failed: {e}",
                    metadata=metadata,
                )
        elif effective_action == "audit_only":
            metadata["reason_code"] = REASON_SECRET_DETECTED
            return PluginResult(
                allowed=True,
                reason="Secrets detected in notification - audit only",
                metadata=metadata,
            )

        # Default to blocking for unknown action (fail closed)
        return PluginResult(
            allowed=False, reason="Unknown action mode", metadata=metadata
        )


# Handler manifest for plugin discovery
HANDLERS = {"basic_secrets_filter": BasicSecretsFilterPlugin}
