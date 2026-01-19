"""Basic PII Filter security plugin implementation.

⚠️  WARNING: This plugin provides only basic PII protection and is NOT suitable for
production use. It uses simple regex-based pattern matching which can be
bypassed. For production environments, implement enterprise-grade PII detection solutions.

This module provides a security plugin that detects and filters personally
identifiable information (PII) across all MCP communications using configurable
pattern matching with three operation modes: block, redact, and audit_only.

The plugin supports:
- Credit card numbers (with automatic Luhn validation)
- Email addresses (RFC 5322 compliant)
- US Phone numbers (parentheses, dash, and dot formats)
- IP addresses (IPv4 and IPv6)
- National ID numbers (US SSN, UK NI, Canadian SIN)

NOTE: This plugin uses regex-based pattern matching for PII detection. While effective
for common PII formats, it may not catch:
- Context-dependent PII (names, addresses without clear patterns)
- Obfuscated or encoded PII
- Novel or region-specific PII formats
- PII split across multiple fields

For higher accuracy PII detection, consider integrating with ML-based solutions
like Microsoft Presidio or cloud-based PII detection services.
"""

import logging
import re
import json
from typing import Dict, Any, List, Tuple
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.utils.encoding import is_data_url, safe_decode_base64

logger = logging.getLogger(__name__)

# Content processing constants
CHUNK_SIZE = 65536  # 64KB - optimal for performance and memory usage
OVERLAP_SIZE = 1024  # 1KB overlap to catch patterns at chunk boundaries


# Redaction format: [PII_TYPE REDACTED by Gatekit]
def get_redaction_placeholder(pii_type: str) -> str:
    """Get redaction placeholder for a specific PII type."""
    return f"[{pii_type.upper()} REDACTED by Gatekit]"


class BasicPIIFilterPlugin(SecurityPlugin):
    """Security plugin for PII content filtering with configurable detection modes."""

    # PII type identifiers and display names
    PII_TYPES = {
        "email": "Email",
        "phone": "US Phone",
        "credit_card": "Credit Card",
        "ip_address": "IP Address",
        "national_id": "National ID",
    }

    # Note: action enum validation is handled by JSON schema

    # TUI Display Metadata
    DISPLAY_NAME = "Basic PII Filter"
    DESCRIPTION = "Basic regex-based PII detection. Not suitable for production use - can be bypassed with encoding or obfuscation."
    DISPLAY_SCOPE = "global"

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        """Generate status description from PII filter configuration."""
        if not config or not config.get("enabled", False):
            return "Disabled"

        action = config.get("action", "redact")
        pii_types = config.get("pii_types", {})

        # Count enabled PII types using constants
        # Per ADR-024: unspecified types default to enabled
        enabled = []
        for pii_type, display_name in cls.PII_TYPES.items():
            if pii_types.get(pii_type, {}).get("enabled", True):
                if (
                    display_name not in enabled
                ):  # Avoid duplicates for ssn/national_id aliases
                    enabled.append(display_name)

        if not enabled:
            return "No PII types enabled"
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
        """Return JSON Schema for PII Filter configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/pii-filter.json",
            "type": "object",
            "description": "PII Filter security plugin configuration",
            "$defs": {
                "piiTypeConfig": {
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
                    "title": "What to do when PII is detected",
                    "enum": ["block", "redact", "audit_only"],
                    "x-enum-labels": {
                        "block": "Block",
                        "redact": "Redact",
                        "audit_only": "Audit Only",
                    },
                    "description": (
                        "• Block: Reject request/response (usually appears to the MCP Client as an error)\n"
                        "• Redact: Replace PII with placeholders but allow the message\n"
                        "• Audit Only: Log PII detection but don't modify content"
                    ),
                    "default": "redact",
                },
                "pii_types": {
                    "type": "object",
                    "title": "PII Types",
                    "description": "Configure which PII types to detect",
                    "properties": {
                        pii_type: {
                            "title": display_name,
                            "$ref": "#/$defs/piiTypeConfig",
                        }
                        for pii_type, display_name in cls.PII_TYPES.items()
                    },
                    "additionalProperties": False,
                },
                "scan_base64": {
                    "type": "boolean",
                    "title": "Decode and scan base64-encoded content (blocks even on action=redact)",
                    "description": "When enabled, base64-encoded strings are decoded and scanned for PII patterns. Note: base64 content cannot be redacted (would corrupt data), so redact mode forces blocking for base64 detections. Includes DoS protection with candidate and size limits.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        }

    def __init__(self, config: Dict[str, Any]):
        """Initialize plugin with comprehensive configuration validation."""
        # Initialize parent class first
        super().__init__(config)

        # Validate configuration against supported options
        self._validate_configuration(config)

        # Store validated configuration
        self.action = config.get("action", "redact")

        # Initialize PII types with defaults (all enabled by default per ADR-024)
        default_pii_types = {
            pii_type: {"enabled": True} for pii_type in self.PII_TYPES.keys()
        }

        # Get PII types from config and merge with defaults
        self.pii_types = config.get("pii_types", {})
        for pii_type, default_config in default_pii_types.items():
            if pii_type not in self.pii_types:
                self.pii_types[pii_type] = default_config

        # Initialize base64 scanning - disabled by default due to false positives on images/files
        self.scan_base64 = config.get("scan_base64", False)

        # Pre-compile regex patterns for performance
        self._compile_patterns()

    def _validate_configuration(self, config: Dict[str, Any]) -> None:
        """Validate configuration against supported options.

        Note: action enum validation is handled by JSON schema.
        """
        # Validate PII types (business logic - not in schema)
        pii_types = config.get("pii_types", {})
        for pii_type in pii_types.keys():
            if pii_type not in self.PII_TYPES:
                raise ValueError(
                    f"Unsupported PII type '{pii_type}'. Must be one of: {', '.join(self.PII_TYPES.keys())}"
                )

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance.

        Compiles patterns into efficient regex objects that can be reused
        for multiple text processing operations.
        """
        self.compiled_patterns = {}

        try:
            # Compile patterns for each enabled PII type
            for pii_type in self.PII_TYPES.keys():
                if self.pii_types.get(pii_type, {}).get("enabled"):
                    self._compile_pii_type_patterns(pii_type)

        except re.error as e:
            logger.exception(f"Error compiling PII detection patterns: {e}")
            raise ValueError(f"Pattern compilation failed: {e}")

    def _compile_pii_type_patterns(self, pii_type: str) -> None:
        """Compile patterns for a specific PII type."""
        if pii_type == "credit_card":
            # Compile credit card patterns with Luhn validation
            self.compiled_patterns["credit_card"] = [
                # Visa (16 digits starting with 4)
                re.compile(r"\b4\d{15}\b"),  # Continuous
                re.compile(
                    r"\b4\d{3}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"
                ),  # Spaced/dashed (require separator)
                # MasterCard (16 digits, 51-55)
                re.compile(r"\b5[1-5]\d{14}\b"),  # Continuous
                re.compile(
                    r"\b5[1-5]\d{2}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"
                ),  # Spaced/dashed (require separator)
                # American Express (15 digits, 34/37)
                re.compile(r"\b3[47]\d{13}\b"),  # Continuous
                re.compile(
                    r"\b3[47]\d{2}[\s\-]\d{6}[\s\-]\d{5}\b"
                ),  # Spaced/dashed (4-6-5 format, require separator)
                # Discover (16 digits, 6011)
                re.compile(r"\b6011\d{12}\b"),  # Continuous
                re.compile(
                    r"\b6011[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b"
                ),  # Spaced/dashed (require separator)
            ]
        elif pii_type == "email":
            # Compile email patterns (RFC 5322 compliant)
            self.compiled_patterns["email"] = [
                re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
            ]
        elif pii_type == "ip_address":
            # Compile IP address patterns (IPv4 and IPv6)
            self.compiled_patterns["ip_address"] = [
                # IPv4 pattern
                re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"),
                # IPv6 pattern (basic form)
                re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
            ]
        elif pii_type == "phone":
            # Compile US phone patterns only
            # Note: UK/international formats removed due to false positives
            # with large numeric values in JSON schemas (e.g., MAX_SAFE_INTEGER)
            self.compiled_patterns["phone"] = [
                re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}"),  # (xxx) xxx-xxxx
                re.compile(r"\d{3}-\d{3}-\d{4}"),  # xxx-xxx-xxxx
                re.compile(r"\d{3}\.\d{3}\.\d{4}"),  # xxx.xxx.xxxx
            ]
        elif pii_type == "national_id":
            # Compile national ID patterns (US SSN, UK NI, Canadian SIN)
            self.compiled_patterns["national_id"] = [
                # US SSN (formatted only - unformatted causes false positives)
                re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
                # UK National Insurance number
                re.compile(r"\b[A-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-Z]\b"),
                # Canadian SIN
                re.compile(r"\b\d{3}-\d{3}-\d{3}\b"),
            ]

    def _luhn_validate(self, card_number: str) -> bool:
        """Validate credit card number using Luhn algorithm."""
        # Remove spaces and non-digits
        digits = [int(d) for d in card_number if d.isdigit()]

        # Apply Luhn algorithm
        for i in range(len(digits) - 2, -1, -2):
            digits[i] *= 2
            if digits[i] > 9:
                digits[i] -= 9

        return sum(digits) % 10 == 0

    def _should_skip_base64_content(self, text: str) -> bool:
        """Check if text should be skipped due to base64 content and configuration."""
        if self.scan_base64:
            return False  # Don't skip, scan everything (existing behavior)

        # Don't skip data URLs - they get special handling
        if is_data_url(text):
            return False

        # Simple base64 detection - if it looks like base64 and scanning is disabled, skip it
        if (
            len(text) > 20
            and re.match(r"^[A-Za-z0-9+/]*={0,2}$", text)
            and len(text) % 4 == 0
        ):
            return True

        return False

    def _detect_pii_in_chunk(self, text: str, offset: int = 0) -> List[Dict[str, Any]]:
        """Detect PII in a text chunk and return list of detections."""
        detections = []

        # Check credit cards with Luhn validation
        if "credit_card" in self.compiled_patterns:
            for pattern in self.compiled_patterns["credit_card"]:
                for match in pattern.finditer(text):
                    card_number = match.group()
                    if self._luhn_validate(card_number):
                        detections.append(
                            {
                                "type": "CREDIT_CARD",
                                "pattern": "luhn_validated",
                                "position": [
                                    match.start() + offset,
                                    match.end() + offset,
                                ],
                                "action": "detected",
                            }
                        )

        # Check emails
        if "email" in self.compiled_patterns:
            for pattern in self.compiled_patterns["email"]:
                for match in pattern.finditer(text):
                    detections.append(
                        {
                            "type": "EMAIL",
                            "pattern": "rfc5322",
                            "position": [match.start() + offset, match.end() + offset],
                            "action": "detected",
                        }
                    )

        # Check IP addresses
        if "ip_address" in self.compiled_patterns:
            for pattern in self.compiled_patterns["ip_address"]:
                for match in pattern.finditer(text):
                    detections.append(
                        {
                            "type": "IP_ADDRESS",
                            "pattern": "ip_format",
                            "position": [match.start() + offset, match.end() + offset],
                            "action": "detected",
                        }
                    )

        # Check phone numbers
        if "phone" in self.compiled_patterns:
            for pattern in self.compiled_patterns["phone"]:
                for match in pattern.finditer(text):
                    detections.append(
                        {
                            "type": "PHONE",
                            "pattern": "phone_format",
                            "position": [match.start() + offset, match.end() + offset],
                            "action": "detected",
                        }
                    )

        # Check national IDs
        if "national_id" in self.compiled_patterns:
            for pattern in self.compiled_patterns["national_id"]:
                for match in pattern.finditer(text):
                    detections.append(
                        {
                            "type": "NATIONAL_ID",
                            "pattern": "national_id_format",
                            "position": [match.start() + offset, match.end() + offset],
                            "action": "detected",
                        }
                    )

        return detections

    def _detect_base64_encoded_pii(self, text: str) -> List[Dict[str, Any]]:
        """Detect PII in base64-encoded content.

        This method finds potential base64 strings, decodes them safely, and scans
        the decoded content for PII patterns.

        DoS Protection: Limits the number of base64 candidates processed to prevent
        attacks using many base64-like strings that could cause excessive decode operations.
        """
        detections = []
        total_decoded_bytes = 0
        candidates_processed = 0

        # DoS protection: Limit base64 candidates to prevent time/memory exhaustion
        MAX_BASE64_CANDIDATES = 50  # Reasonable limit for legitimate content
        MAX_TOTAL_DECODED_BYTES = 100 * 1024  # 100KB total across all candidates

        # Find base64-like strings that are 12+ characters long (including padding)
        # Use word boundaries but make sure padding characters are included
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

            # Skip if the full text is a data URL (handled separately by _detect_pii_in_text)
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

                # Scan decoded content for PII using pattern detection only (no recursive base64)
                decoded_detections = self._detect_pii_in_chunk(decoded_content, 0)

                # Mark these detections as base64-encoded and adjust metadata
                for detection in decoded_detections:
                    detection.update(
                        {
                            "encoding": "base64",
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

    def _detect_pii_in_text(self, text: str) -> List[Dict[str, Any]]:
        """Detect PII in text, processing large content in chunks."""
        # Handle data URLs specially: check the URL itself but skip encoded content
        if is_data_url(text):
            # Extract the data URL prefix (before the base64 content) for pattern matching
            parts = text.split(",", 1)
            if len(parts) >= 1:
                # Check the data URL schema/MIME type part for patterns
                url_prefix = parts[0]
                return self._detect_pii_in_text_content(url_prefix)

            # Skip the base64 content portion - it's likely legitimate file data
            return []

        # For non-data URLs, do normal detection
        return self._detect_pii_in_text_content(text)

    def _detect_pii_in_text_content(self, text: str) -> List[Dict[str, Any]]:
        """Core PII detection logic for text content."""
        detections = []

        # Process in chunks if text is large
        if len(text) > CHUNK_SIZE:
            # Process with overlapping chunks to catch PII at boundaries
            offset = 0
            while offset < len(text):
                # Calculate chunk boundaries with overlap
                chunk_end = min(offset + CHUNK_SIZE, len(text))
                chunk = text[offset:chunk_end]

                # Process this chunk
                chunk_detections = self._detect_pii_in_chunk(chunk, offset)

                # Add detections, avoiding duplicates from overlapping regions
                for detection in chunk_detections:
                    # Check if this detection overlaps with existing ones
                    is_duplicate = False
                    for existing in detections:
                        if (
                            detection["type"] == existing["type"]
                            and detection["pattern"] == existing["pattern"]
                            and abs(detection["position"][0] - existing["position"][0])
                            < OVERLAP_SIZE
                        ):
                            is_duplicate = True
                            break

                    if not is_duplicate:
                        detections.append(detection)

                # Move to next chunk with overlap
                offset += CHUNK_SIZE - OVERLAP_SIZE
                if offset + OVERLAP_SIZE >= len(text):
                    break
        else:
            # Process small text directly
            detections = self._detect_pii_in_chunk(text, 0)

        # Check base64-encoded PII if scan_base64 is enabled
        if self.scan_base64:
            base64_detections = self._detect_base64_encoded_pii(text)
            detections.extend(base64_detections)

        return detections

    def _has_base64_detections(self, detections: List[Dict[str, Any]]) -> bool:
        """Check if any detections are from base64-encoded content.

        Base64-encoded content cannot be redacted - any modification corrupts
        the underlying binary data. Must block instead.
        """
        return any(d.get("encoding") == "base64" for d in detections)

    def _redact_pii_in_text(self, text: str, detections: List[Dict[str, Any]]) -> str:
        """Redact PII in text based on detections."""
        if not detections:
            return text

        # Sort detections by position (reverse order to maintain positions)
        sorted_detections = sorted(
            detections, key=lambda x: x["position"][0], reverse=True
        )

        redacted_text = text
        for detection in sorted_detections:
            start, end = detection["position"]
            redacted_text = (
                redacted_text[:start]
                + get_redaction_placeholder(detection["type"])
                + redacted_text[end:]
            )
            detection["action"] = "redacted"

        return redacted_text

    def _extract_text_from_data(self, data: Any) -> str:
        """Extract text content from various data types.

        Args:
            data: The data to extract text from

        Returns:
            String representation of the data

        Note:
            All content is processed regardless of size
        """
        if isinstance(data, str):
            text = data
        elif isinstance(data, dict):
            text = json.dumps(data)
        elif isinstance(data, list):
            text = json.dumps(data)
        else:
            text = str(data)

        return text

    def _process_message_content(
        self, content: Any
    ) -> Tuple[List[Dict[str, Any]], Any]:
        """Process message content and return detections and potentially modified content.

        Uses recursive structure walking to detect and redact PII in-place,
        avoiding JSON serialization/deserialization issues.
        """
        from gatekit.plugins.security import (
            MAX_CONTENT_SIZE,
            REASON_CONTENT_SIZE_EXCEEDED,
        )

        # First, check total content size for DoS protection
        text = self._extract_text_from_data(content)
        text_size_bytes = len(text.encode("utf-8"))
        if text_size_bytes > MAX_CONTENT_SIZE:
            return [
                {
                    "type": "content_size_exceeded",
                    "size_bytes": text_size_bytes,
                    "max_size": MAX_CONTENT_SIZE,
                    "reason": f"Content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                    "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                }
            ], content

        # Recursively walk the structure, detecting and optionally redacting PII
        all_detections = []

        def process_value(obj: Any) -> Any:
            """Recursively process a value, detecting and optionally redacting PII.

            Converts numeric primitives to strings for scanning to catch PII stored
            as numbers (credit cards without separators, etc.).
            """
            if isinstance(obj, str):
                # Skip base64 content if scanning is disabled
                if self._should_skip_base64_content(obj):
                    return obj

                # Detect PII in this string
                detections = self._detect_pii_in_text(obj)
                all_detections.extend(detections)

                # Redact if configured and detections found
                if self.action == "redact" and detections:
                    return self._redact_pii_in_text(obj, detections)
                return obj
            elif isinstance(obj, dict):
                return {k: process_value(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [process_value(item) for item in obj]
            elif isinstance(obj, (int, float)) and obj is not True and obj is not False:
                # Convert numbers to strings for scanning (credit card numbers, etc.)
                # Note: bool is a subclass of int in Python, so we explicitly exclude it
                str_value = str(obj)
                detections = self._detect_pii_in_text(str_value)
                all_detections.extend(detections)

                # If PII detected and we're in redact mode, coerce to string and redact
                # This changes the type but enforces the configured security action
                if self.action == "redact" and detections:
                    return self._redact_pii_in_text(str_value, detections)
                return obj
            else:
                # bool, None, or other types - pass through unchanged
                return obj

        modified_content = process_value(content)
        return all_detections, modified_content

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Check request for PII and apply configured mode."""

        # Process request content
        if request.params:
            detections, modified_params = self._process_message_content(request.params)
        else:
            detections = []
            modified_params = request.params

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

        # Generate decision based on mode
        if not detections:
            return PluginResult(
                allowed=True,
                reason="No PII detected",
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": False,
                    "detection_action": self.action,
                    "detections": [],
                },
            )

        from gatekit.plugins.security import REASON_PII_DETECTED

        # Check if any detections are from base64-encoded content
        # Base64 content cannot be redacted - force block instead of redact to avoid corruption
        has_base64 = self._has_base64_detections(detections)
        effective_action = "block" if (has_base64 and self.action == "redact") else self.action

        if effective_action == "block":
            reason = "PII detected - blocking transmission"
            if has_base64:
                reason = "PII detected in base64 content (blocking required)"
            return PluginResult(
                allowed=False,
                reason=reason,
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": True,
                    "detection_action": effective_action,
                    "detections": detections,
                    "reason_code": REASON_PII_DETECTED,
                    "base64_force_block": has_base64 and self.action == "redact",
                },
            )
        elif effective_action == "redact":
            if modified_params != request.params:
                # Create a new request with redacted content
                modified_request = MCPRequest(
                    jsonrpc=request.jsonrpc,
                    method=request.method,
                    id=request.id,
                    params=modified_params,
                    sender_context=request.sender_context,
                )

                return PluginResult(
                    allowed=True,
                    reason=f"PII detected and redacted from request: {', '.join([d['type'] for d in detections])}",
                    metadata={
                        "plugin": self.__class__.__name__,
                        "pii_detected": True,
                        "detection_action": effective_action,
                        "detections": detections,
                        "reason_code": REASON_PII_DETECTED,
                    },
                    modified_content=modified_request,
                )
            else:
                return PluginResult(
                    allowed=True,
                    reason="PII detected but no redaction needed",
                    metadata={
                        "plugin": self.__class__.__name__,
                        "pii_detected": True,
                        "detection_action": effective_action,
                        "detections": detections,
                        "reason_code": REASON_PII_DETECTED,
                    },
                )
        else:  # audit_only
            return PluginResult(
                allowed=True,
                reason="PII detected - audit only",
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": True,
                    "detection_action": self.action,
                    "detections": detections,
                    "reason_code": REASON_PII_DETECTED,
                },
            )

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Check response for PII and apply configured mode."""
        # Process response content
        if response.result:
            detections, modified_result = self._process_message_content(response.result)
        else:
            detections = []
            modified_result = response.result

        # Generate decision based on mode
        if not detections:
            return PluginResult(
                allowed=True,
                reason="No PII detected in response",
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": False,
                    "detection_action": self.action,
                    "detections": [],
                },
            )

        from gatekit.plugins.security import REASON_PII_DETECTED

        # Check if any detections are from base64-encoded content
        # Base64 content cannot be redacted - force block instead of redact to avoid corruption
        has_base64 = self._has_base64_detections(detections)
        effective_action = "block" if (has_base64 and self.action == "redact") else self.action

        if effective_action == "block":
            reason = "PII detected in response - blocking transmission"
            if has_base64:
                reason = "PII detected in base64 content in response (blocking required)"
            return PluginResult(
                allowed=False,
                reason=reason,
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": True,
                    "detection_action": effective_action,
                    "detections": detections,
                    "reason_code": REASON_PII_DETECTED,
                    "base64_force_block": has_base64 and self.action == "redact",
                },
            )
        elif effective_action == "redact":
            if modified_result != response.result:
                modified_response = MCPResponse(
                    jsonrpc=response.jsonrpc,
                    id=response.id,
                    result=modified_result,
                    error=response.error,
                    sender_context=response.sender_context,
                )

                return PluginResult(
                    allowed=True,
                    reason="PII detected in response and redacted",
                    metadata={
                        "plugin": self.__class__.__name__,
                        "pii_detected": True,
                        "detection_action": effective_action,
                        "detections": detections,
                        "reason_code": REASON_PII_DETECTED,
                    },
                    modified_content=modified_response,
                )
            else:
                return PluginResult(
                    allowed=True,
                    reason="PII detected in response but no modification needed",
                    metadata={
                        "plugin": self.__class__.__name__,
                        "pii_detected": True,
                        "detection_action": effective_action,
                        "detections": detections,
                        "reason_code": REASON_PII_DETECTED,
                    },
                )
        else:  # audit_only
            return PluginResult(
                allowed=True,
                reason="PII detected in response - audit only",
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": True,
                    "detection_action": effective_action,
                    "detections": detections,
                    "reason_code": REASON_PII_DETECTED,
                },
            )

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        """Check notification for PII and apply configured mode."""
        # Process notification content
        if notification.params:
            detections, modified_params = self._process_message_content(
                notification.params
            )
        else:
            detections = []
            modified_params = notification.params

        # Generate decision based on mode
        if not detections:
            return PluginResult(
                allowed=True,
                reason="No PII detected in notification",
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": False,
                    "detection_action": self.action,
                    "detections": [],
                },
            )

        from gatekit.plugins.security import REASON_PII_DETECTED

        # Check if any detections are from base64-encoded content
        # Base64 content cannot be redacted - force block instead of redact to avoid corruption
        has_base64 = self._has_base64_detections(detections)
        effective_action = "block" if (has_base64 and self.action == "redact") else self.action

        if effective_action == "block":
            reason = "PII detected in notification - blocking transmission"
            if has_base64:
                reason = "PII detected in base64 content in notification (blocking required)"
            return PluginResult(
                allowed=False,
                reason=reason,
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": True,
                    "detection_action": effective_action,
                    "detections": detections,
                    "reason_code": REASON_PII_DETECTED,
                    "base64_force_block": has_base64 and self.action == "redact",
                },
            )
        elif effective_action == "redact":
            if modified_params != notification.params:
                # Create a new notification with redacted content
                modified_notification = MCPNotification(
                    jsonrpc=notification.jsonrpc,
                    method=notification.method,
                    params=modified_params,
                )

                return PluginResult(
                    allowed=True,
                    reason=f"PII detected and redacted from notification: {', '.join([d['type'] for d in detections])}",
                    metadata={
                        "plugin": self.__class__.__name__,
                        "pii_detected": True,
                        "detection_action": effective_action,
                        "detections": detections,
                        "reason_code": REASON_PII_DETECTED,
                    },
                    modified_content=modified_notification,
                )
            else:
                return PluginResult(
                    allowed=True,
                    reason="PII detected in notification but no redaction needed",
                    metadata={
                        "plugin": self.__class__.__name__,
                        "pii_detected": True,
                        "detection_action": effective_action,
                        "detections": detections,
                        "reason_code": REASON_PII_DETECTED,
                    },
                )
        else:  # audit_only
            return PluginResult(
                allowed=True,
                reason="PII detected in notification - audit only",
                metadata={
                    "plugin": self.__class__.__name__,
                    "pii_detected": True,
                    "detection_action": effective_action,
                    "detections": detections,
                    "reason_code": REASON_PII_DETECTED,
                },
            )


# Handler manifest for handler-based plugin discovery
HANDLERS = {"basic_pii_filter": BasicPIIFilterPlugin}
