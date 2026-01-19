"""Security plugins for Gatekit MCP gateway.

This package contains security handler plugins that evaluate incoming MCP
requests and determine whether they should be allowed to proceed.
"""

# Security limits to prevent DoS attacks
MAX_CONTENT_SIZE = 1024 * 1024  # 1MB limit for content processing

# Standard reason codes for consistent logging
REASON_NONE = "none"  # No issues detected
REASON_CONTENT_SIZE_EXCEEDED = "content_size_exceeded"
REASON_SECRET_DETECTED = "secret_detected"
REASON_PII_DETECTED = "pii_detected"
REASON_INJECTION_DETECTED = "injection_detected"
REASON_ENCODED_INJECTION_DETECTED = "encoded_injection_detected"


def create_plugin_metadata(
    plugin_instance, reason_code=REASON_NONE, **additional_metadata
):
    """Create standardized plugin metadata with consistent structure.

    Args:
        plugin_instance: The plugin instance (for class name)
        reason_code: The reason code for this decision
        **additional_metadata: Any plugin-specific metadata to include

    Returns:
        Dict containing standardized metadata structure
    """
    base_metadata = {
        "plugin": plugin_instance.__class__.__name__,
        "reason_code": reason_code,
    }
    base_metadata.update(additional_metadata)
    return base_metadata


__all__ = [
    "MAX_CONTENT_SIZE",
    "REASON_NONE",
    "REASON_CONTENT_SIZE_EXCEEDED",
    "REASON_SECRET_DETECTED",
    "REASON_PII_DETECTED",
    "REASON_INJECTION_DETECTED",
    "REASON_ENCODED_INJECTION_DETECTED",
    "create_plugin_metadata",
]
