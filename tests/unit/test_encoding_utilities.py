"""Tests for the shared encoding utilities module."""

from gatekit.utils.encoding import looks_like_base64, is_data_url, safe_decode_base64


class TestLooksLikeBase64:
    """Test the looks_like_base64 function."""

    def test_valid_base64_detected(self):
        """Test that valid base64 strings are detected."""
        # 20+ character valid base64
        valid_base64 = "SGVsbG8gV29ybGQhISEhISEhISEh"  # "Hello World!!!!!!!!!"
        assert looks_like_base64(valid_base64) is True

    def test_short_base64_not_detected(self):
        """Test that short base64 strings are not detected (below threshold)."""
        short_base64 = "SGVsbG8="  # "Hello" - only 8 chars
        assert looks_like_base64(short_base64, min_length=20) is False

    def test_invalid_characters_not_detected(self):
        """Test that strings with invalid base64 characters are not detected."""
        invalid_base64 = "Hello@World#123456789012345"  # 25 chars but invalid
        assert looks_like_base64(invalid_base64) is False

    def test_wrong_padding_not_detected(self):
        """Test that strings with wrong padding are not detected."""
        wrong_padding = "SGVsbG8gV29ybGQhISEhISEhISE"  # Missing padding
        assert looks_like_base64(wrong_padding) is False

    def test_data_urls_not_detected(self):
        """Test that data URLs are not flagged as base64."""
        data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        assert looks_like_base64(data_url) is False

    def test_custom_min_length_threshold(self):
        """Test custom minimum length threshold."""
        medium_base64 = "SGVsbG8gV29ybGQ="  # "Hello World" - 16 chars
        assert looks_like_base64(medium_base64, min_length=10) is True
        assert looks_like_base64(medium_base64, min_length=20) is False

    def test_url_safe_base64_detected(self):
        """Test that URL-safe base64 (with - and _) is detected."""
        url_safe_base64 = "SGVsbG8gV29ybGQhISEhISEh_-_-"  # 32 chars with URL-safe chars
        assert looks_like_base64(url_safe_base64) is True


class TestIsDataUrl:
    """Test the is_data_url function."""

    def test_image_data_urls_detected(self):
        """Test that image data URLs are detected."""
        image_data_urls = [
            "data:image/png;base64,iVBORw0KGgo=",
            "data:image/jpeg;base64,/9j/4AAQSkZJRgAB",
            "data:image/gif;base64,R0lGODlhAQABAIAA",
        ]
        for url in image_data_urls:
            assert is_data_url(url) is True

    def test_application_data_urls_detected(self):
        """Test that application data URLs are detected."""
        app_data_urls = [
            "data:application/pdf;base64,JVBERi0xLjQ=",
            "data:application/json;base64,eyJrZXkiOiJ2YWx1ZSJ9",
        ]
        for url in app_data_urls:
            assert is_data_url(url) is True

    def test_text_data_urls_detected(self):
        """Test that text data URLs are detected."""
        text_data_urls = [
            "data:text/plain;base64,SGVsbG8gV29ybGQ=",
            "data:text/html;base64,PGh0bWw+SGVsbG88L2h0bWw+",
        ]
        for url in text_data_urls:
            assert is_data_url(url) is True

    def test_media_data_urls_detected(self):
        """Test that audio/video/font data URLs are detected."""
        media_data_urls = [
            "data:audio/wav;base64,UklGRiQAAABXQVZF",
            "data:video/mp4;base64,AAAAIGZ0eXBpc29t",
            "data:font/woff;base64,d09GRgABAAAAAC4AAAA=",
        ]
        for url in media_data_urls:
            assert is_data_url(url) is True

    def test_case_insensitive_detection(self):
        """Test that data URL detection is case-insensitive."""
        case_variations = [
            "DATA:IMAGE/PNG;BASE64,iVBORw0KGgo=",
            "Data:Image/Png;Base64,iVBORw0KGgo=",
            "data:IMAGE/png;BASE64,iVBORw0KGgo=",
        ]
        for url in case_variations:
            assert is_data_url(url) is True

    def test_non_data_urls_not_detected(self):
        """Test that non-data URLs are not detected."""
        non_data_urls = [
            "http://example.com/image.png",
            "https://example.com/file.pdf",
            "file:///path/to/file.txt",
            "base64:SGVsbG8gV29ybGQ=",
            "SGVsbG8gV29ybGQhISEhISEhISEh",  # Plain base64
        ]
        for url in non_data_urls:
            assert is_data_url(url) is False


class TestSafeDecodeBase64:
    """Test the safe_decode_base64 function."""

    def test_valid_base64_decoded(self):
        """Test that valid base64 is properly decoded."""
        base64_text = "SGVsbG8gV29ybGQ="  # "Hello World"
        result = safe_decode_base64(base64_text)
        assert result == "Hello World"

    def test_invalid_base64_returns_none(self):
        """Test that invalid base64 returns None."""
        invalid_base64 = "This is not base64!"
        result = safe_decode_base64(invalid_base64)
        assert result is None

    def test_size_limit_enforced(self):
        """Test that size limits are enforced."""
        # Create a string that would decode to >10KB (default limit)
        large_base64 = "QQ==" * 5000  # "A" repeated many times
        result = safe_decode_base64(large_base64, max_decode_size=100)
        assert result is None

    def test_custom_size_limit(self):
        """Test custom size limits."""
        medium_base64 = "SGVsbG8gV29ybGQ="  # "Hello World" - 11 chars decoded
        result = safe_decode_base64(medium_base64, max_decode_size=20)
        assert result == "Hello World"

        result = safe_decode_base64(medium_base64, max_decode_size=5)
        assert result is None

    def test_malformed_base64_returns_none(self):
        """Test that malformed base64 returns None."""
        malformed_cases = [
            "SGVsbG8",  # Missing padding
            "SGVsbG8g===",  # Too much padding
            "SGVs bG8gV29ybGQ=",  # Spaces in middle
        ]
        for case in malformed_cases:
            result = safe_decode_base64(case)
            assert result is None

    def test_binary_content_handled(self):
        """Test that binary content that can't be decoded to UTF-8 returns None."""
        # Create base64 that decodes to invalid UTF-8
        import base64

        invalid_utf8_bytes = b"\xff\xfe\xfd"
        invalid_utf8_base64 = base64.b64encode(invalid_utf8_bytes).decode()
        result = safe_decode_base64(invalid_utf8_base64)
        # Should return None or empty string due to errors='ignore'
        assert result is None or result == ""

    def test_data_urls_processed_normally(self):
        """Test that data URLs are processed like any other base64 (caller should check is_data_url first)."""
        # The function doesn't check for data URLs - that's the caller's responsibility
        data_url = "data:text/plain;base64,SGVsbG8gV29ybGQ="
        result = safe_decode_base64(data_url)
        # Should return None because the whole data URL isn't valid base64
        assert result is None

        # But if we extract just the base64 part:
        base64_part = "SGVsbG8gV29ybGQ="
        result = safe_decode_base64(base64_part)
        assert result == "Hello World"
