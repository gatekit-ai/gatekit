"""Unit tests for logging configuration models."""

import pytest
from pathlib import Path

from gatekit.config.models import LoggingConfig


class TestLoggingConfig:
    """Test LoggingConfig dataclass creation and validation."""

    def test_default_config(self):
        """Test default logging configuration (stderr only)."""
        logging_config = LoggingConfig()

        assert logging_config.level == "INFO"
        assert logging_config.handlers == ["stderr"]
        assert logging_config.file_path is None
        assert logging_config.max_file_size_mb == 10
        assert logging_config.backup_count == 5
        assert (
            logging_config.format == "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        assert logging_config.date_format == "%Y-%m-%d %H:%M:%S"

    def test_file_logging_config(self):
        """Test file-based logging configuration."""
        logging_config = LoggingConfig(
            level="DEBUG", handlers=["file"], file_path=Path("logs/gatekit.log")
        )

        assert logging_config.level == "DEBUG"
        assert logging_config.handlers == ["file"]
        assert logging_config.file_path == Path("logs/gatekit.log")

    def test_combined_logging_config(self):
        """Test combined stderr and file logging."""
        logging_config = LoggingConfig(
            level="WARNING",
            handlers=["stderr", "file"],
            file_path=Path("logs/gatekit.log"),
            max_file_size_mb=50,
            backup_count=10,
        )

        assert logging_config.level == "WARNING"
        assert logging_config.handlers == ["stderr", "file"]
        assert logging_config.file_path == Path("logs/gatekit.log")
        assert logging_config.max_file_size_mb == 50
        assert logging_config.backup_count == 10

    def test_invalid_level(self):
        """Test invalid log level raises ValueError."""
        with pytest.raises(ValueError, match="Invalid log level"):
            LoggingConfig(level="INVALID")

    def test_invalid_handler(self):
        """Test invalid handler raises ValueError."""
        with pytest.raises(ValueError, match="Invalid handler"):
            LoggingConfig(handlers=["invalid"])

    def test_file_handler_without_path(self):
        """Test file handler without file_path raises ValueError."""
        with pytest.raises(
            ValueError, match="file_path is required when using file handler"
        ):
            LoggingConfig(handlers=["file"])

    def test_invalid_file_size(self):
        """Test invalid max file size raises ValueError."""
        with pytest.raises(TypeError, match="max_file_size_mb must be positive"):
            LoggingConfig(max_file_size_mb=0)

    def test_invalid_backup_count(self):
        """Test invalid backup count raises ValueError."""
        with pytest.raises(TypeError, match="backup_count must be non-negative"):
            LoggingConfig(backup_count=-1)
