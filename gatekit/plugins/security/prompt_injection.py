"""Basic Prompt Injection Defense Plugin implementation.

⚠️  WARNING: This plugin provides only basic prompt injection protection and is NOT
suitable for production use. It uses simple regex patterns which can be bypassed.
For production environments, implement enterprise-grade prompt injection detection solutions.

This plugin provides basic detection of obvious prompt injection patterns using simple
regex matching. It targets common low-sophistication attacks such as delimiter injection,
crude role manipulation, and basic context hijacking attempts.

WARNING: This plugin provides only basic protection against unsophisticated attacks.
It will NOT detect:
- Semantic injections without obvious keywords
- Encoded attacks (Base64, ROT13, etc.)
- Synonym-based evasion techniques
- Multi-turn conversation attacks
- Context-dependent manipulation
- Advanced jailbreaking techniques

For production environments with serious security requirements, implement additional
AI-based detection systems or human review processes.
"""

import re
import time
import logging
from typing import Dict, Any, List, Tuple
from gatekit.plugins.interfaces import SecurityPlugin, PluginResult
from gatekit.protocol.messages import MCPRequest, MCPResponse, MCPNotification
from gatekit.utils.encoding import is_data_url

logger = logging.getLogger(__name__)

# Content processing constants
CHUNK_SIZE = 65536  # 64KB - optimal for performance and memory usage
OVERLAP_SIZE = 1024  # 1KB overlap to catch patterns at chunk boundaries


class BasicPromptInjectionDefensePlugin(SecurityPlugin):
    """Security plugin that detects basic, obvious prompt injection patterns."""

    # Pattern category identifiers and display names
    PATTERN_CATEGORIES = {
        "delimiter_injection": "Delimiter",
        "role_manipulation": "Role",
        "context_hijacking": "Context",
    }

    # TUI Display Metadata
    DISPLAY_NAME = "Basic Prompt Injection Defense"
    DESCRIPTION = "Basic regex-based prompt injection detection. Not suitable for production use - can be bypassed by sophisticated attacks."
    DISPLAY_SCOPE = "global"

    @classmethod
    def describe_status(cls, config: Dict[str, Any]) -> str:
        """Generate status description from prompt injection configuration."""
        if not config or not config.get("enabled", False):
            return "Disabled"

        action = config.get("action", "redact")
        sensitivity = config.get("sensitivity", "standard")
        detection_methods = config.get("detection_methods", {})

        # Count enabled detection methods using constants
        enabled = []
        for pattern_category, display_name in cls.PATTERN_CATEGORIES.items():
            if detection_methods.get(pattern_category, {}).get("enabled", True):
                enabled.append(display_name)

        if not enabled:
            return "No detection methods configured"

        methods_text = ", ".join(enabled)
        return f"{action.title()}: {methods_text} ({sensitivity})"

    @classmethod
    def get_display_actions(cls, config: Dict[str, Any]) -> List[str]:
        """Return actions based on configuration state."""
        if config and config.get("enabled", False):
            return ["Configure", "Test"]
        return ["Setup"]

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for Prompt Injection Defense configuration."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://gatekit.ai/schemas/prompt-injection.json",
            "type": "object",
            "description": "Prompt Injection detection plugin configuration",
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
                        "• Block: Reject the request (this usually appears to the MCP Client as an error)\n"
                        "• Redact: Replace prompt injection patterns with placeholders\n"
                        "• Audit Only: Log detection but allow through"
                    ),
                    "default": "redact",
                },
                "sensitivity": {
                    "type": "string",
                    "title": "Detection Sensitivity",
                    "enum": ["relaxed", "standard", "strict"],
                    "x-enum-labels": {
                        "relaxed": "Relaxed",
                        "standard": "Standard",
                        "strict": "Strict",
                    },
                    "description": "• Relaxed: Fewer false positives\n• Standard: Balanced detection\n• Strict: Maximum protection",
                    "default": "standard",
                },
                "detection_methods": {
                    "type": "object",
                    "title": "Detection Methods",
                    "description": "Detection methods to enable",
                    "properties": {
                        "delimiter_injection": {
                            "type": "object",
                            "title": "Delimiter Injection",
                            "properties": {
                                "enabled": {"type": "boolean", "default": True}
                            },
                            "additionalProperties": False,
                        },
                        "role_manipulation": {
                            "type": "object",
                            "title": "Role Manipulation",
                            "properties": {
                                "enabled": {"type": "boolean", "default": True}
                            },
                            "additionalProperties": False,
                        },
                        "context_hijacking": {
                            "type": "object",
                            "title": "Context Hijacking",
                            "properties": {
                                "enabled": {"type": "boolean", "default": True}
                            },
                            "additionalProperties": False,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        }

    def __init__(self, config: Dict[str, Any]):
        """Initialize plugin with configuration."""
        # Validate configuration type first
        if not isinstance(config, dict):
            raise TypeError("Configuration must be a dictionary")

        # Initialize base class to set priority
        super().__init__(config)

        self.action = config.get("action", "redact")
        self.sensitivity = config.get("sensitivity", "standard")

        # Initialize detection methods with defaults based on constants
        detection_methods = config.get("detection_methods", {})
        self.detection_methods = {}
        for pattern_category in self.PATTERN_CATEGORIES.keys():
            self.detection_methods[pattern_category] = detection_methods.get(
                pattern_category, {"enabled": True}
            )

        # Compile detection patterns based on sensitivity
        self._compile_detection_patterns()

    def _compile_detection_patterns(self):
        """Compile regex patterns for injection detection based on sensitivity level.

        Sensitivity levels:
        - relaxed: Fewer patterns, only the most obvious attacks. Fewer false positives.
        - standard: Balanced detection with good coverage and acceptable false positive rate.
        - strict: Maximum protection, more patterns, may have higher false positive rate.
        """
        self.compiled_patterns = {}

        # Delimiter injection patterns
        if self.detection_methods.get("delimiter_injection", {}).get("enabled", False):
            if self.sensitivity == "relaxed":
                # Relaxed: Only the most obvious delimiter injections
                delimiter_patterns = [
                    r"\[(?:SYSTEM|ADMIN)\].*?\[/(?:SYSTEM|ADMIN)\]",  # Role delimiters only
                    r"<(?:system|admin)>.*?</(?:system|admin)>",  # XML system/admin tags only
                ]
            else:
                # Standard patterns
                delimiter_patterns = [
                    r'["\']{3,}.*?(?:system|admin|override|ignore).*?["\']{3,}',  # Triple quotes with injection keywords
                    r"```.*?(?:system|admin|override|ignore).*?```",  # Markdown code blocks
                    r"~~~.*?(?:system|admin|override|ignore).*?~~~",  # Alternative code blocks
                    r"<(?:system|admin|instruction|override)>.*?</(?:system|admin|instruction|override)>",  # XML/HTML tags
                    r"\[(?:SYSTEM|ADMIN|USER|ASSISTANT)\].*?\[/(?:SYSTEM|ADMIN|USER|ASSISTANT)\]",  # Role delimiters
                ]

                if self.sensitivity == "strict":
                    # More aggressive patterns for strict mode
                    delimiter_patterns.extend(
                        [
                            r'["\']{{2,}}.*?(?:bypass|disable|cancel).*?["\']{{2,}}',
                            r"```[^`]*(?:bypass|disable|cancel)[^`]*```",
                        ]
                    )

            self.compiled_patterns["delimiter_injection"] = [
                re.compile(pattern, re.IGNORECASE | re.DOTALL)
                for pattern in delimiter_patterns
            ]

        # Role manipulation patterns - More specific to reduce false positives while maintaining security
        if self.detection_methods.get("role_manipulation", {}).get("enabled", False):
            if self.sensitivity == "relaxed":
                # Relaxed: Only the most explicit role manipulation attempts
                role_patterns = [
                    r"you\s+are\s+now\s+(?:an?\s+)?(?:admin|administrator|root|superuser|DAN)\b",
                    r"you\s+are\s+now\s+operating\s+as\s+(?:root|admin|system)\b",
                ]
            else:
                # Standard patterns
                role_patterns = [
                    r"(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+(?:an?\s+)?(?:admin|administrator|system|root|superuser|DAN)\b",
                    r"(?:ignore|disregard)\s+(?:previous|earlier|original)\s+(?:role|instructions|commands)\b",
                    r"(?:as\s+)?(?:admin|administrator|system)\s*[:,]?\s*(?:execute|run|bypass)\b",
                    r"(?:with|using)\s+(?:elevated|admin|administrative|system)\s+(?:privileges|access|rights)\b",
                    r"administrator\s+mode\s*:",
                    r"you\s+are\s+now\s+operating\s+as\s+(?:root|admin|system)\b",
                    r"act\s+as\s+if\s+you\s+are\s+(?:a|an)?\s*(?:security|admin|system)\s+(?:bypass|override)\b",
                ]

                if self.sensitivity == "strict":
                    # More aggressive patterns for strict mode
                    role_patterns.extend(
                        [
                            r"(?:you\s+are|act\s+as)\s+(?:an?\s+)?(?:admin|administrator)\b",
                            r"admin\s+(?:mode|access|override)\b",
                        ]
                    )

            self.compiled_patterns["role_manipulation"] = [
                re.compile(pattern, re.IGNORECASE) for pattern in role_patterns
            ]

        # Context hijacking patterns - More specific to reduce false positives on legitimate conversation starters
        if self.detection_methods.get("context_hijacking", {}).get("enabled", False):
            if self.sensitivity == "relaxed":
                # Relaxed: Only the most obvious context hijacking attempts
                context_patterns = [
                    r"ignore\s+all\s+previous\s+instructions\b",
                    r"forget\s+everything\s+(?:you|that)\s+(?:were|was)\s+told\b",
                    r"(?:override|bypass)\s+all\s+safety\s+(?:protocols|instructions|rules)\b",
                ]
            else:
                # Standard patterns
                context_patterns = [
                    r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|earlier|original|everything)?\s*(?:instructions|commands|rules)\b",
                    r"(?:forget|ignore)\s+(?:everything|all)\s+(?:you|that|previous|above)\b",
                    r"(?:reset|clear)\s+(?:context|conversation|session|memory|all)\b",
                    r"(?:start|begin)\s+(?:fresh|new)\s+(?:and|then)\s+(?:ignore|reset|forget)\b",
                    r"(?:new|fresh)\s+(?:conversation|session)\s*[:,]\s*(?:reset|ignore|forget)\b",
                    r"(?:begin|start)\s+(?:new\s+session|fresh)\s+without\s+(?:restrictions|limitations|rules)\b",
                    r"reset\s+(?:context|all\s+parameters)\s+and\s+start\s+over\b",
                    r"(?:override|bypass|disable)\s+(?:all|safety|security)\s*(?:instructions|protocols|rules)?\b",
                    r"(?:override|bypass|disable)\s+(?:all|any)\s+(?:safety|security)\s+(?:instructions|protocols|rules)\b",
                    r"(?:start|begin)\s+(?:fresh|new|over)\s+(?:by|with)\s+(?:ignoring|forgetting|disregarding)\s+(?:all|everything|previous|instructions)\b",
                ]

                if self.sensitivity == "strict":
                    # More aggressive patterns for strict mode
                    context_patterns.extend(
                        [
                            r"(?:ignore|forget)\s+(?:this|that|instructions)\b",
                            r"(?:new|fresh)\s+(?:conversation|session)\b",
                        ]
                    )

            self.compiled_patterns["context_hijacking"] = [
                re.compile(pattern, re.IGNORECASE) for pattern in context_patterns
            ]

    def _extract_text_from_request(self, request: MCPRequest) -> List[str]:
        """Extract text content from MCP request for analysis."""
        text_content = []

        if request.params:
            # Recursively extract string values from params
            def extract_strings(obj):
                if isinstance(obj, str):
                    text_content.append(obj)
                elif isinstance(obj, dict):
                    for value in obj.values():
                        extract_strings(value)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_strings(item)

            extract_strings(request.params)

        return text_content

    def _decode_potential_encodings(self, text: str) -> List[Tuple[str, str]]:
        """Attempt to decode potentially encoded attack payloads.

        Returns list of (decoded_text, encoding_type) tuples.
        Only decodes strings that look like they might be encoded.
        Includes deduplication and validation.
        """
        from gatekit.utils.encoding import safe_decode_base64

        decoded_versions = []
        seen_texts = {text}  # Track to avoid duplicates

        # Skip data URLs entirely
        if is_data_url(text):
            return []

        # Check for base64 encoding (min 40 chars to minimize false positives)
        # Note: Higher threshold dramatically reduces false positives on legitimate data
        if (
            len(text) >= 40
            and re.match(r"^[A-Za-z0-9+/]*={0,2}$", text)
            and len(text) % 4 == 0
        ):
            # Use shared safe_decode_base64 utility
            decoded = safe_decode_base64(text, max_decode_size=10240)
            if decoded and len(decoded) > 5 and decoded not in seen_texts:
                decoded_versions.append((decoded, "base64"))
                seen_texts.add(decoded)

        # ROT13 detection removed - too many false positives for minimal benefit
        # Real-world prompt injection attacks rarely use ROT13 encoding

        return decoded_versions

    def _sanitize_detections_for_logging(
        self, detections: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove matched_text from detections before logging to prevent log replay attacks.

        The matched_text field is used internally for redaction verification but should
        not be included in audit logs. Including actual injection payloads in logs creates
        a security vulnerability: AI assistants reviewing logs could be affected by the
        injection attempts stored in matched_text (indirect prompt injection via log replay).

        This aligns with how PII and Secrets filters handle sensitive data - logging only
        metadata (type, position, pattern) without the actual matched content.
        """
        return [
            {k: v for k, v in detection.items() if k != "matched_text"}
            for detection in detections
        ]

    def _process_text_chunk(self, text: str, offset: int = 0) -> List[Dict[str, Any]]:
        """Process a single chunk of text for injection patterns."""
        detections = []

        # Check delimiter injection patterns
        if "delimiter_injection" in self.compiled_patterns:
            for i, pattern in enumerate(self.compiled_patterns["delimiter_injection"]):
                matches = pattern.finditer(text)
                for match in matches:
                    detections.append(
                        {
                            "category": "delimiter_injection",
                            "pattern": f"delimiter_pattern_{i}",
                            "matched_text": match.group()[:100],  # Used for redaction verification
                            "position": [match.start() + offset, match.end() + offset],
                            "confidence": "high",
                        }
                    )

        # Check role manipulation patterns
        if "role_manipulation" in self.compiled_patterns:
            for i, pattern in enumerate(self.compiled_patterns["role_manipulation"]):
                matches = pattern.finditer(text)
                for match in matches:
                    detections.append(
                        {
                            "category": "role_manipulation",
                            "pattern": f"role_pattern_{i}",
                            "matched_text": match.group()[:100],  # Used for redaction verification
                            "position": [match.start() + offset, match.end() + offset],
                            "confidence": "high",
                        }
                    )

        # Check context hijacking patterns
        if "context_hijacking" in self.compiled_patterns:
            for i, pattern in enumerate(self.compiled_patterns["context_hijacking"]):
                matches = pattern.finditer(text)
                for match in matches:
                    detections.append(
                        {
                            "category": "context_hijacking",
                            "pattern": f"context_pattern_{i}",
                            "matched_text": match.group()[:100],  # Used for redaction verification
                            "position": [match.start() + offset, match.end() + offset],
                            "confidence": "high",
                        }
                    )

        return detections

    def _detect_injections(self, text_content: List[str]) -> List[Dict[str, Any]]:
        """Detect injection patterns in text content, including encoded versions."""
        from gatekit.plugins.security import (
            MAX_CONTENT_SIZE,
        )

        detections = []
        total_decoded_size = 0

        for text in text_content:
            if not text:
                continue

            # Size check is now done earlier in process_request - no need to duplicate here

            # Check original text
            original_detections = self._process_single_text(text, "original")
            detections.extend(original_detections)

            # Also check decoded versions if they exist
            decoded_versions = self._decode_potential_encodings(text)
            for decoded_text, encoding_type in decoded_versions:
                # Limit total decoded content size to prevent DoS
                total_decoded_size += len(decoded_text.encode("utf-8"))
                if total_decoded_size > MAX_CONTENT_SIZE:
                    logger.warning(
                        "Decoded content size limit exceeded, skipping further decoding"
                    )
                    break

                # Process the decoded text
                decoded_detections = self._process_single_text(
                    decoded_text, encoding_type
                )
                detections.extend(decoded_detections)

        return detections

    def _process_single_text(
        self, text: str, encoding_type: str
    ) -> List[Dict[str, Any]]:
        """Process a single text string for injection patterns."""
        from gatekit.plugins.security import (
            REASON_INJECTION_DETECTED,
            REASON_ENCODED_INJECTION_DETECTED,
        )

        detections = []

        # Process in chunks if text is large
        if len(text) > CHUNK_SIZE:
            # Process with overlapping chunks to catch patterns at boundaries
            offset = 0
            while offset < len(text):
                # Calculate chunk boundaries with overlap
                chunk_end = min(offset + CHUNK_SIZE, len(text))
                chunk = text[offset:chunk_end]

                # Process this chunk
                chunk_detections = self._process_text_chunk(chunk, offset)

                # Add encoding_type to detections and set reason codes
                for detection in chunk_detections:
                    detection["encoding_type"] = encoding_type
                    if encoding_type != "original":
                        detection["reason_code"] = REASON_ENCODED_INJECTION_DETECTED
                    else:
                        detection["reason_code"] = REASON_INJECTION_DETECTED

                    # Check if this detection overlaps with existing ones
                    is_duplicate = False
                    for existing in detections:
                        if (
                            detection["category"] == existing["category"]
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
            chunk_detections = self._process_text_chunk(text, 0)

            # Add encoding_type to detections
            for detection in chunk_detections:
                detection["encoding_type"] = encoding_type
                if encoding_type != "original":
                    detection["reason_code"] = REASON_ENCODED_INJECTION_DETECTED
                else:
                    detection["reason_code"] = REASON_INJECTION_DETECTED
                detections.append(detection)

        return detections

    def _redact_injections_from_request(
        self, request: MCPRequest, detections: List[Dict[str, Any]]
    ) -> MCPRequest:
        """Create a redacted copy of the request by replacing injection patterns.

        Uses position-based slicing to ensure complete redaction even for long
        matches that were truncated in detection metadata for logging purposes.

        Tracks which detections have been consumed to prevent double-redaction
        when multiple strings contain similar content.
        """
        import copy

        if not detections:
            return request

        redacted_request = copy.deepcopy(request)

        # Track which detections have been applied to prevent double-redaction
        consumed_detections = set()

        def redact_in_structure(obj):
            if isinstance(obj, str):
                current_text = obj

                # Collect detections that match this text, tracking by index to mark consumed
                # Use a dict keyed by (start, end) to deduplicate overlapping pattern matches
                position_to_detection = {}
                for idx, detection in enumerate(detections):
                    if idx in consumed_detections:
                        continue  # Already applied to another string

                    pos = detection.get("position", [])
                    if len(pos) == 2:
                        start, end = pos
                        # Verify this detection is for this string by checking bounds and content
                        if start >= 0 and end <= len(current_text):
                            actual_text = current_text[start:end]
                            matched_text = detection.get("matched_text", "")
                            # matched_text is truncated to 100 chars, so compare prefix
                            if matched_text and actual_text.startswith(matched_text[:100]):
                                # Only keep first detection for each position span
                                if (start, end) not in position_to_detection:
                                    position_to_detection[(start, end)] = idx

                if not position_to_detection:
                    return current_text

                # Sort by position descending to avoid offset issues when replacing
                sorted_positions = sorted(position_to_detection.keys(), key=lambda x: x[0], reverse=True)

                # Apply redactions using position-based slicing (each span only once)
                result = current_text
                for start, end in sorted_positions:
                    idx = position_to_detection[(start, end)]
                    result = result[:start] + "[PROMPT INJECTION REDACTED by Gatekit]" + result[end:]
                    consumed_detections.add(idx)  # Mark as consumed

                return result
            elif isinstance(obj, dict):
                return {k: redact_in_structure(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [redact_in_structure(item) for item in obj]
            else:
                return obj

        if redacted_request.params:
            redacted_request.params = redact_in_structure(redacted_request.params)

        return redacted_request

    def _redact_injections_from_response(
        self, response: MCPResponse, detections: List[Dict[str, Any]]
    ) -> MCPResponse:
        """Create a redacted copy of the response by replacing injection patterns.

        Uses position-based slicing to ensure complete redaction even for long
        matches that were truncated in detection metadata for logging purposes.

        Tracks which detections have been consumed to prevent double-redaction
        when multiple strings contain similar content.
        """
        import copy

        if not detections:
            return response

        redacted_response = copy.deepcopy(response)

        # Track which detections have been applied to prevent double-redaction
        consumed_detections = set()

        def redact_in_structure(obj):
            if isinstance(obj, str):
                current_text = obj

                # Collect detections that match this text, tracking by index to mark consumed
                # Use a dict keyed by (start, end) to deduplicate overlapping pattern matches
                position_to_detection = {}
                for idx, detection in enumerate(detections):
                    if idx in consumed_detections:
                        continue  # Already applied to another string

                    pos = detection.get("position", [])
                    if len(pos) == 2:
                        start, end = pos
                        # Verify this detection is for this string by checking bounds and content
                        if start >= 0 and end <= len(current_text):
                            actual_text = current_text[start:end]
                            matched_text = detection.get("matched_text", "")
                            # matched_text is truncated to 100 chars, so compare prefix
                            if matched_text and actual_text.startswith(matched_text[:100]):
                                # Only keep first detection for each position span
                                if (start, end) not in position_to_detection:
                                    position_to_detection[(start, end)] = idx

                if not position_to_detection:
                    return current_text

                # Sort by position descending to avoid offset issues when replacing
                sorted_positions = sorted(position_to_detection.keys(), key=lambda x: x[0], reverse=True)

                # Apply redactions using position-based slicing (each span only once)
                result = current_text
                for start, end in sorted_positions:
                    idx = position_to_detection[(start, end)]
                    result = result[:start] + "[PROMPT INJECTION REDACTED by Gatekit]" + result[end:]
                    consumed_detections.add(idx)  # Mark as consumed

                return result
            elif isinstance(obj, dict):
                return {k: redact_in_structure(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [redact_in_structure(item) for item in obj]
            else:
                return obj

        if redacted_response.result:
            redacted_response.result = redact_in_structure(redacted_response.result)

        return redacted_response

    async def process_request(
        self, request: MCPRequest, server_name: str
    ) -> PluginResult:
        """Check if request contains prompt injection attempts."""
        start_time = time.time()

        try:

            # Extract text content from request
            text_content = self._extract_text_from_request(request)

            # Check content size before processing (early DoS protection)
            from gatekit.plugins.security import (
                MAX_CONTENT_SIZE,
                REASON_CONTENT_SIZE_EXCEEDED,
            )

            for text in text_content:
                if text:
                    text_size_bytes = len(text.encode("utf-8"))
                    if text_size_bytes > MAX_CONTENT_SIZE:
                        return PluginResult(
                            allowed=False,
                            reason=f"Content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                            metadata={
                                "plugin": self.__class__.__name__,
                                "content_size_bytes": text_size_bytes,
                                "max_size": MAX_CONTENT_SIZE,
                                "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                                "processing_time_ms": round(
                                    (time.time() - start_time) * 1000, 2
                                ),
                            },
                        )

            # Detect injection patterns
            detections = self._detect_injections(text_content)

            processing_time_ms = round((time.time() - start_time) * 1000, 2)

            # Prepare metadata - sanitize detections to remove matched_text before logging
            sanitized_detections = self._sanitize_detections_for_logging(detections)
            metadata = {
                "plugin": "basic_prompt_injection_defense",
                "injection_detected": len(detections) > 0,
                "detection_mode": self.action,
                "sensitivity_level": self.sensitivity,
                "detections": sanitized_detections,
                "total_detections": len(detections),
                "processing_time_ms": processing_time_ms,
            }

            # Return decision based on mode and detections
            if len(detections) == 0:
                return PluginResult(
                    allowed=True,
                    reason="No prompt injection detected",
                    metadata=metadata,
                )

            # Injection detected - handle based on mode
            if self.action == "block":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                return PluginResult(
                    allowed=False,
                    reason=f"Prompt injection detected: {len(detections)} pattern(s) found",
                    metadata=metadata,
                )
            elif self.action == "redact":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                # Redact the injection patterns from the request
                redacted_request = self._redact_injections_from_request(request, detections)

                return PluginResult(
                    allowed=True,
                    reason=f"Prompt injection redacted: {len(detections)} pattern(s) redacted",
                    metadata=metadata,
                    modified_content=redacted_request,
                )
            elif self.action == "audit_only":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                return PluginResult(
                    allowed=True,
                    reason=f"Injection attempt logged: {len(detections)} pattern(s) found",
                    metadata=metadata,
                )

        except Exception as e:
            # Fail closed on errors
            logger.exception(f"Error in prompt injection detection: {e}")
            return PluginResult(
                allowed=False,
                reason=f"Error during injection detection: {str(e)}",
                metadata={
                    "plugin": "basic_prompt_injection_defense",
                    "error": str(e),
                    "processing_time_ms": round((time.time() - start_time) * 1000, 2),
                },
            )

    async def process_response(
        self, request: MCPRequest, response: MCPResponse, server_name: str
    ) -> PluginResult:
        """Check if response contains prompt injection attempts.

        This is critical for preventing injection attacks embedded in file contents,
        API responses, or other data sources that might be returned to the user.
        """
        start_time = time.time()

        try:

            # Extract text content from response
            text_content = []
            if response.result:

                def extract_strings(obj):
                    if isinstance(obj, str):
                        text_content.append(obj)
                    elif isinstance(obj, dict):
                        for value in obj.values():
                            extract_strings(value)
                    elif isinstance(obj, list):
                        for item in obj:
                            extract_strings(item)

                extract_strings(response.result)

            # Check content size before processing (early DoS protection)
            from gatekit.plugins.security import (
                MAX_CONTENT_SIZE,
                REASON_CONTENT_SIZE_EXCEEDED,
            )

            for text in text_content:
                if text:
                    text_size_bytes = len(text.encode("utf-8"))
                    if text_size_bytes > MAX_CONTENT_SIZE:
                        return PluginResult(
                            allowed=False,
                            reason=f"Response content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                            metadata={
                                "plugin": self.__class__.__name__,
                                "content_size_bytes": text_size_bytes,
                                "max_size": MAX_CONTENT_SIZE,
                                "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                                "processing_time_ms": round(
                                    (time.time() - start_time) * 1000, 2
                                ),
                                "check_type": "response",
                            },
                        )

            # Detect injection patterns in response content
            detections = self._detect_injections(text_content)

            processing_time_ms = round((time.time() - start_time) * 1000, 2)

            # Prepare metadata - sanitize detections to remove matched_text before logging
            sanitized_detections = self._sanitize_detections_for_logging(detections)
            metadata = {
                "plugin": "basic_prompt_injection_defense",
                "injection_detected": len(detections) > 0,
                "detection_mode": self.action,
                "sensitivity_level": self.sensitivity,
                "detections": sanitized_detections,
                "total_detections": len(detections),
                "processing_time_ms": processing_time_ms,
                "check_type": "response",
            }

            # Return decision based on mode and detections
            if len(detections) == 0:
                return PluginResult(
                    allowed=True,
                    reason="No prompt injection detected in response",
                    metadata=metadata,
                )

            # Injection detected in response - handle based on mode
            if self.action == "block":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                return PluginResult(
                    allowed=False,
                    reason=f"Prompt injection detected in response: {len(detections)} pattern(s) found",
                    metadata=metadata,
                )
            elif self.action == "redact":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                # Redact the injection patterns from the response
                redacted_response = self._redact_injections_from_response(response, detections)

                return PluginResult(
                    allowed=True,
                    reason=f"Prompt injection redacted from response: {len(detections)} pattern(s) redacted",
                    metadata=metadata,
                    modified_content=redacted_response,
                )
            elif self.action == "audit_only":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                return PluginResult(
                    allowed=True,
                    reason=f"Injection attempt in response logged: {len(detections)} pattern(s) found",
                    metadata=metadata,
                )

        except Exception as e:
            # Fail closed on errors
            logger.exception(f"Error in prompt injection detection for response: {e}")
            return PluginResult(
                allowed=False,
                reason=f"Error during response injection detection: {str(e)}",
                metadata={
                    "plugin": "basic_prompt_injection_defense",
                    "error": str(e),
                    "processing_time_ms": round((time.time() - start_time) * 1000, 2),
                },
            )

    async def process_notification(
        self, notification: MCPNotification, server_name: str
    ) -> PluginResult:
        """Check if notification contains prompt injection attempts.

        Notifications can be another vector for injection attacks and should be
        checked with the same rigor as requests and responses.
        """
        start_time = time.time()

        try:
            # Extract text content from notification
            text_content = []
            if notification.params:

                def extract_strings(obj):
                    if isinstance(obj, str):
                        text_content.append(obj)
                    elif isinstance(obj, dict):
                        for value in obj.values():
                            extract_strings(value)
                    elif isinstance(obj, list):
                        for item in obj:
                            extract_strings(item)

                extract_strings(notification.params)

            # Also check the method name itself for injection patterns
            if notification.method:
                text_content.append(notification.method)

            # Check content size before processing (early DoS protection)
            from gatekit.plugins.security import (
                MAX_CONTENT_SIZE,
                REASON_CONTENT_SIZE_EXCEEDED,
            )

            for text in text_content:
                if text:
                    text_size_bytes = len(text.encode("utf-8"))
                    if text_size_bytes > MAX_CONTENT_SIZE:
                        return PluginResult(
                            allowed=False,
                            reason=f"Notification content exceeds maximum size limit ({MAX_CONTENT_SIZE} bytes)",
                            metadata={
                                "plugin": self.__class__.__name__,
                                "content_size_bytes": text_size_bytes,
                                "max_size": MAX_CONTENT_SIZE,
                                "reason_code": REASON_CONTENT_SIZE_EXCEEDED,
                                "processing_time_ms": round(
                                    (time.time() - start_time) * 1000, 2
                                ),
                                "check_type": "notification",
                            },
                        )

            # Detect injection patterns
            detections = self._detect_injections(text_content)

            processing_time_ms = round((time.time() - start_time) * 1000, 2)

            # Prepare metadata - sanitize detections to remove matched_text before logging
            sanitized_detections = self._sanitize_detections_for_logging(detections)
            metadata = {
                "plugin": "basic_prompt_injection_defense",
                "injection_detected": len(detections) > 0,
                "detection_mode": self.action,
                "sensitivity_level": self.sensitivity,
                "detections": sanitized_detections,
                "total_detections": len(detections),
                "processing_time_ms": processing_time_ms,
                "check_type": "notification",
            }

            # Return decision based on mode and detections
            if len(detections) == 0:
                return PluginResult(
                    allowed=True,
                    reason="No prompt injection detected in notification",
                    metadata=metadata,
                )

            # Injection detected in notification - handle based on mode
            if self.action == "block":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                return PluginResult(
                    allowed=False,
                    reason=f"Prompt injection detected in notification: {len(detections)} pattern(s) found",
                    metadata=metadata,
                )
            elif self.action == "redact":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                # Note: Notification redaction not implemented yet
                # For now, just log and allow through like audit mode
                return PluginResult(
                    allowed=True,
                    reason=f"Prompt injection in notification (redaction not implemented): {len(detections)} pattern(s) found",
                    metadata=metadata,
                )
            elif self.action == "audit_only":
                from gatekit.plugins.security import (
                    REASON_INJECTION_DETECTED,
                    REASON_ENCODED_INJECTION_DETECTED,
                )

                # Determine reason code based on detection types
                has_encoded = any(
                    d.get("encoding_type") != "original" for d in detections
                )
                reason_code = (
                    REASON_ENCODED_INJECTION_DETECTED
                    if has_encoded
                    else REASON_INJECTION_DETECTED
                )
                metadata["reason_code"] = reason_code

                return PluginResult(
                    allowed=True,
                    reason=f"Injection attempt in notification logged: {len(detections)} pattern(s) found",
                    metadata=metadata,
                )

        except Exception as e:
            # Fail closed on errors
            logger.exception(f"Error in prompt injection detection for notification: {e}")
            return PluginResult(
                allowed=False,
                reason=f"Error during notification injection detection: {str(e)}",
                metadata={
                    "plugin": "basic_prompt_injection_defense",
                    "error": str(e),
                    "processing_time_ms": round((time.time() - start_time) * 1000, 2),
                },
            )


# Handler manifest for handler-based plugin discovery
HANDLERS = {"basic_prompt_injection_defense": BasicPromptInjectionDefensePlugin}
