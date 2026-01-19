"""Unit tests for main application logging configuration."""

import pytest
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, call

from gatekit.config.models import LoggingConfig
from gatekit.main import setup_logging_from_config


class TestMainLogging:
    """Test main application logging setup."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_setup_logging_from_config_stderr_only(self):
        """Test setting up logging with stderr handler only."""
        logging_config = LoggingConfig(level="DEBUG", handlers=["stderr"])

        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.StreamHandler") as mock_stream_handler,
        ):

            mock_root_logger = MagicMock()
            mock_asyncio_logger = MagicMock()

            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = MagicMock()
            mock_stream_handler.return_value = mock_handler

            setup_logging_from_config(logging_config)

            # Verify root logger setup
            mock_root_logger.setLevel.assert_called_with(logging.DEBUG)
            mock_root_logger.handlers.clear.assert_called_once()
            mock_root_logger.addHandler.assert_called_with(mock_handler)

            # Verify asyncio logger setup
            mock_asyncio_logger.setLevel.assert_called_with(logging.WARNING)

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_setup_logging_from_config_file_only(self):
        """Test setting up logging with file handler only."""
        logging_config = LoggingConfig(
            level="INFO",
            handlers=["file"],
            file_path=Path("logs/test.log"),
            max_file_size_mb=5,
            backup_count=3,
        )

        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.handlers.RotatingFileHandler") as mock_file_handler,
            patch("logging.Formatter"),
        ):

            mock_root_logger = MagicMock()
            mock_asyncio_logger = MagicMock()

            # Return different mocks for different calls
            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = MagicMock()
            mock_file_handler.return_value = mock_handler

            setup_logging_from_config(logging_config)

            # Verify getLogger() was called for root logger (among other calls)
            assert call() in mock_get_logger.call_args_list

            # Verify file handler was created with correct parameters
            mock_file_handler.assert_called_once_with(
                Path("logs/test.log"),
                maxBytes=5 * 1024 * 1024,  # 5MB in bytes
                backupCount=3,
            )

            # Verify logger configuration
            mock_root_logger.setLevel.assert_called_with(logging.INFO)
            mock_root_logger.addHandler.assert_called_with(mock_handler)

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_setup_logging_from_config_combined_handlers(self):
        """Test setting up logging with both stderr and file handlers."""
        logging_config = LoggingConfig(
            level="WARNING",
            handlers=["stderr", "file"],
            file_path=Path("logs/combined.log"),
        )

        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.handlers.RotatingFileHandler") as mock_file_handler,
            patch("logging.Formatter"),
        ):

            mock_root_logger = MagicMock()
            mock_get_logger.return_value = mock_root_logger
            mock_handler = MagicMock()
            mock_file_handler.return_value = mock_handler

            setup_logging_from_config(logging_config)

            # Manual handler setup should be used (not basicConfig)
            assert mock_get_logger.call_args_list[0] == call()
            mock_file_handler.assert_called_once()
            mock_root_logger.setLevel.assert_called_with(logging.WARNING)
            # Should have been called twice (once for stderr, once for file)
            assert mock_root_logger.addHandler.call_count == 2

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_setup_logging_fallback_to_stderr(self):
        """Test fallback to stderr logging when no config provided."""
        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.StreamHandler") as mock_stream_handler,
        ):

            mock_root_logger = MagicMock()
            mock_asyncio_logger = MagicMock()

            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = MagicMock()
            mock_stream_handler.return_value = mock_handler

            setup_logging_from_config(None, verbose=True)

            # Should use DEBUG level due to verbose=True
            mock_root_logger.setLevel.assert_called_with(logging.DEBUG)
            mock_root_logger.handlers.clear.assert_called_once()
            mock_root_logger.addHandler.assert_called_with(mock_handler)

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_verbose_override_config_level(self):
        """Test that verbose flag overrides config log level."""
        logging_config = LoggingConfig(level="ERROR", handlers=["stderr"])  # High level

        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.StreamHandler") as mock_stream_handler,
        ):

            mock_root_logger = MagicMock()
            mock_asyncio_logger = MagicMock()

            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = MagicMock()
            mock_stream_handler.return_value = mock_handler

            setup_logging_from_config(logging_config, verbose=True)

            # Should use DEBUG level due to verbose=True, not ERROR from config
            mock_root_logger.setLevel.assert_called_with(logging.DEBUG)

    def test_config_level_used_when_not_verbose(self):
        """Test that config log level is used when verbose=False."""
        logging_config = LoggingConfig(level="ERROR", handlers=["stderr"])

        with (
            patch("logging.getLogger") as mock_get_logger,
            patch("logging.StreamHandler") as mock_stream_handler,
        ):

            mock_root_logger = MagicMock()
            mock_asyncio_logger = MagicMock()

            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = MagicMock()
            mock_stream_handler.return_value = mock_handler

            setup_logging_from_config(logging_config, verbose=False)

            # Should use ERROR level from config
            mock_root_logger.setLevel.assert_called_with(logging.ERROR)
