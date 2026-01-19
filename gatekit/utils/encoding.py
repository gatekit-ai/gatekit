"""Shared utilities for encoding detection and handling.

These utilities will be replaced when we migrate to third-party libraries,
so they are intentionally simple and focused.
"""

import re
from typing import Optional


def looks_like_base64(text: str, min_length: int = 20) -> bool:
    """Simple heuristic to detect base64-encoded strings.

    Args:
        text: String to check
        min_length: Minimum length to consider (default 20 - conservative for low FP)

    Returns:
        True if string appears to be base64-encoded

    Note:
        This is a simple heuristic that will be replaced by proper
        detection libraries (e.g., Presidio) in the future.
    """
    if len(text) < min_length:
        return False

    # Check for data URLs - these are legitimate (case-insensitive)
    if text.lower().startswith(
        (
            "data:image/",
            "data:application/",
            "data:text/",
            "data:audio/",
            "data:video/",
            "data:font/",
        )
    ):
        return False

    # Basic base64 character set check
    # Include URL-safe variants (-_) and padding (=)
    if not re.match(r"^[A-Za-z0-9+/\-_]*={0,2}$", text):
        return False

    # Check proper padding
    return len(text) % 4 == 0


def is_data_url(text: str) -> bool:
    """Check if text is a data URL (case-insensitive).

    Args:
        text: String to check

    Returns:
        True if string is a data URL
    """
    return text.lower().startswith(
        (
            "data:image/",
            "data:application/",
            "data:text/",
            "data:audio/",
            "data:video/",
            "data:font/",
        )
    )


def safe_decode_base64(text: str, max_decode_size: int = 10240) -> Optional[str]:
    """Safely attempt to decode base64 with size limits and validation.

    Note: Callers should check is_data_url() first if they want to skip data URLs.

    Args:
        text: Potentially base64-encoded string
        max_decode_size: Maximum size to decode (default 10KB)

    Returns:
        Decoded string if successful, None otherwise
    """
    # Skip if input is too large (base64 is ~1.37x larger than decoded)
    if len(text) > max_decode_size * 1.4:
        return None

    try:
        import base64
        import binascii

        # Additional validation - check for proper base64 format
        # No spaces allowed, proper length, proper padding
        if " " in text or len(text) % 4 != 0:
            return None

        # Check for excessive padding
        if text.count("=") > 2:
            return None

        # Use validate=True to prevent garbage decodes
        decoded_bytes = base64.b64decode(text, validate=True)
        # Check decoded size before converting to string
        if len(decoded_bytes) > max_decode_size:
            return None
        decoded = decoded_bytes.decode("utf-8", errors="ignore")
        return decoded if decoded else None  # Return None for empty strings
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
