"""Unit tests for sandbox platform detection and backend selection."""

import sys
from unittest.mock import patch, MagicMock

import pytest

from gatekit.sandbox.detection import (
    get_sandbox_backend,
    is_sandbox_available,
    get_sandbox_backend_or_raise,
    _detect_backend,
)
from gatekit.sandbox.errors import SandboxUnavailableError


class TestDetectBackend:
    """Test _detect_backend platform routing."""

    @patch("gatekit.sandbox.detection.sys")
    def test_darwin_returns_seatbelt(self, mock_sys):
        mock_sys.platform = "darwin"
        backend = _detect_backend()
        assert backend is not None
        assert backend.name == "seatbelt"

    @patch("gatekit.sandbox.detection.sys")
    def test_linux_returns_bubblewrap(self, mock_sys):
        mock_sys.platform = "linux"
        backend = _detect_backend()
        assert backend is not None
        assert backend.name == "bubblewrap"

    @patch("gatekit.sandbox.detection.sys")
    def test_windows_returns_none(self, mock_sys):
        mock_sys.platform = "win32"
        backend = _detect_backend()
        assert backend is None


class TestGetSandboxBackend:
    """Test get_sandbox_backend with availability checks."""

    @patch("gatekit.sandbox.detection._detect_backend")
    def test_returns_backend_when_available(self, mock_detect):
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_detect.return_value = mock_backend
        assert get_sandbox_backend() is mock_backend

    @patch("gatekit.sandbox.detection._detect_backend")
    def test_returns_none_when_unavailable(self, mock_detect):
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = False
        mock_detect.return_value = mock_backend
        assert get_sandbox_backend() is None

    @patch("gatekit.sandbox.detection._detect_backend")
    def test_returns_none_on_unsupported_platform(self, mock_detect):
        mock_detect.return_value = None
        assert get_sandbox_backend() is None


class TestIsSandboxAvailable:
    """Test is_sandbox_available convenience function."""

    @patch("gatekit.sandbox.detection.get_sandbox_backend")
    def test_true_when_backend_available(self, mock_get):
        mock_get.return_value = MagicMock()
        assert is_sandbox_available() is True

    @patch("gatekit.sandbox.detection.get_sandbox_backend")
    def test_false_when_no_backend(self, mock_get):
        mock_get.return_value = None
        assert is_sandbox_available() is False


class TestGetSandboxBackendOrRaise:
    """Test get_sandbox_backend_or_raise error messages."""

    @patch("gatekit.sandbox.detection._detect_backend")
    def test_raises_on_unsupported_platform(self, mock_detect):
        mock_detect.return_value = None
        with pytest.raises(SandboxUnavailableError, match="not supported"):
            get_sandbox_backend_or_raise()

    @patch("gatekit.sandbox.detection._detect_backend")
    def test_raises_with_diagnostic_when_unavailable(self, mock_detect):
        mock_backend = MagicMock()
        mock_backend.name = "bubblewrap"
        mock_backend.is_available.return_value = False
        mock_backend.availability_diagnostic.return_value = "bwrap not installed"
        mock_detect.return_value = mock_backend

        with pytest.raises(SandboxUnavailableError) as exc_info:
            get_sandbox_backend_or_raise()

        assert "bubblewrap" in str(exc_info.value)
        assert exc_info.value.diagnostic == "bwrap not installed"

    @patch("gatekit.sandbox.detection._detect_backend")
    def test_returns_backend_when_available(self, mock_detect):
        mock_backend = MagicMock()
        mock_backend.is_available.return_value = True
        mock_detect.return_value = mock_backend
        assert get_sandbox_backend_or_raise() is mock_backend
