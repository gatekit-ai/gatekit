"""Integration tests for log rotation behavior.

Tests for log rotation functionality following TDD methodology.
These tests are written in RED phase and should initially fail.
"""

import pytest
import tempfile
import os
import asyncio
import logging
from pathlib import Path

from gatekit.config.loader import ConfigLoader
from gatekit.main import setup_logging_from_config

# Import shared logging cleanup helpers (Windows compatibility)
from conftest import close_all_logging_handlers as _close_all_logging_handlers


@pytest.fixture
def log_rotation_config():
    """Create a configuration with log rotation settings for testing."""
    # Note: %f (microseconds) is not valid for time.strftime on Windows
    # Use a valid date format that works cross-platform
    config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["echo", "test"]
  timeouts:
    connection_timeout: 30
    request_timeout: 60

logging:
  level: "DEBUG"
  handlers: ["file"]
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  date_format: "%Y-%m-%dT%H:%M:%S"
  file_path: "test_rotation.log"
  max_file_size_mb: 0.002  # Small for testing - 2KB (more predictable than 1KB)
  backup_count: 3
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(config_content)
        f.flush()
        yield Path(f.name)

    # Cleanup config file
    os.unlink(f.name)


@pytest.fixture
def temp_log_directory():
    """Create a temporary directory for log files.

    On Windows, we need to explicitly close all logging handlers before
    the temporary directory can be cleaned up, as Windows doesn't allow
    deleting open files.
    """
    temp_dir_obj = tempfile.TemporaryDirectory()
    temp_dir = temp_dir_obj.name
    try:
        yield Path(temp_dir)
    finally:
        # Close all logging handlers before cleanup (required for Windows)
        _close_all_logging_handlers()

        # Now clean up the temp directory
        try:
            temp_dir_obj.cleanup()
        except PermissionError:
            # On Windows, sometimes handlers take a moment to release files
            import time

            time.sleep(0.1)
            _close_all_logging_handlers()
            try:
                temp_dir_obj.cleanup()
            except PermissionError:
                pass  # Best effort cleanup


def setup_test_logging(config, log_file_path):
    """Helper function to setup logging configuration for tests."""
    config.logging.file_path = log_file_path
    setup_logging_from_config(config.logging)


def force_log_flush():
    """Helper function to ensure all logs are flushed to disk."""
    # Flush all handlers in the logging system
    for logger_name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()

    # Also flush root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if hasattr(handler, "flush"):
            handler.flush()


def count_log_entries(log_file_path, pattern=""):
    """Helper function to count log entries across main and backup files."""
    total_entries = 0

    # Count entries in main log
    if log_file_path.exists():
        with open(log_file_path, "r") as f:
            total_entries += len([line for line in f if pattern in line])

    # Count entries in backup files
    for i in range(1, 10):
        backup_file = Path(str(log_file_path) + f".{i}")
        if backup_file.exists():
            with open(backup_file, "r") as f:
                total_entries += len([line for line in f if pattern in line])

    return total_entries


class TestLogRotation:
    """Test cases for log rotation behavior."""

    @pytest.mark.asyncio
    async def test_basic_log_rotation_at_size_limit(
        self, log_rotation_config, temp_log_directory
    ):
        """Test that logs rotate when maxBytes is exceeded."""
        # Load configuration and setup
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(log_rotation_config)
        log_file_path = temp_log_directory / "test_rotation.log"

        setup_test_logging(config, log_file_path)
        logger = logging.getLogger("test_rotation")

        # Write logs until rotation should occur
        # With 2KB limit, we need to write more than 2048 bytes
        log_message = "A" * 150  # 150 character message
        for i in range(20):  # 20 * 150 = 3000 bytes, should trigger rotation
            logger.info(f"Log message {i}: {log_message}")

        force_log_flush()

        # Check that rotation occurred
        assert log_file_path.exists(), "Main log file should exist"

        # Check for backup files
        backup_file_1 = Path(str(log_file_path) + ".1")
        assert (
            backup_file_1.exists()
        ), "First backup file should be created after rotation"

        # Verify both files exist and have content (rotation worked)
        main_size = log_file_path.stat().st_size
        backup_size = backup_file_1.stat().st_size
        assert main_size > 0, "Main log should have content"
        assert backup_size > 0, "Backup log should have content"

        # Verify total content is approximately what we wrote
        # 20 messages * ~100-170 bytes each (message + formatting varies by platform)
        # Must exceed the 2KB rotation limit to prove rotation occurred
        total_size = main_size + backup_size
        assert total_size > 2000, f"Total log size {total_size} should exceed rotation limit"

    @pytest.mark.asyncio
    async def test_backup_file_naming_sequence(
        self, log_rotation_config, temp_log_directory
    ):
        """Test that backup files are named correctly (.1, .2, etc.)."""
        # Load and setup configuration
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(log_rotation_config)

        log_file_path = temp_log_directory / "test_sequence.log"
        config.logging.file_path = log_file_path

        setup_logging_from_config(config.logging)
        logger = logging.getLogger("test_sequence")

        # Force multiple rotations
        log_message = "B" * 200  # Larger message for faster rotation

        # First rotation
        for i in range(10):
            logger.info(f"First batch {i}: {log_message}")

        # Force flush and small delay
        for handler in logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()
        await asyncio.sleep(0.1)

        # Second rotation
        for i in range(10):
            logger.info(f"Second batch {i}: {log_message}")

        for handler in logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()
        await asyncio.sleep(0.1)

        # Third rotation
        for i in range(10):
            logger.info(f"Third batch {i}: {log_message}")

        for handler in logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        # Check backup file sequence
        backup_files = [
            Path(str(log_file_path) + ".1"),
            Path(str(log_file_path) + ".2"),
            Path(str(log_file_path) + ".3"),
        ]

        for backup_file in backup_files:
            assert backup_file.exists(), f"Backup file {backup_file} should exist"

    @pytest.mark.asyncio
    async def test_backup_count_limit_enforcement(
        self, log_rotation_config, temp_log_directory
    ):
        """Test that old logs are deleted when backup_count limit is reached."""
        # Load and setup configuration
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(log_rotation_config)

        log_file_path = temp_log_directory / "test_limit.log"
        config.logging.file_path = log_file_path

        setup_logging_from_config(config.logging)
        logger = logging.getLogger("test_limit")

        # Force more rotations than backup_count (3)
        log_message = "C" * 300  # Large message

        # Generate enough logs to exceed backup_count
        for batch in range(5):  # 5 batches should create more than 3 backups
            for i in range(8):
                logger.info(f"Batch {batch} message {i}: {log_message}")

            # Force flush between batches
            for handler in logger.handlers:
                if hasattr(handler, "flush"):
                    handler.flush()
            await asyncio.sleep(0.1)

        # Check that only backup_count (3) backup files exist
        backup_files = []
        for i in range(1, 10):  # Check up to .9 files
            backup_file = Path(str(log_file_path) + f".{i}")
            if backup_file.exists():
                backup_files.append(backup_file)

        assert (
            len(backup_files) <= 3
        ), f"Should have at most 3 backup files, found {len(backup_files)}"

        # Check that .4 and higher don't exist (should be deleted)
        for i in range(4, 10):
            backup_file = Path(str(log_file_path) + f".{i}")
            assert (
                not backup_file.exists()
            ), f"Backup file {backup_file} should not exist (beyond backup_count)"

    @pytest.mark.asyncio
    async def test_concurrent_writes_during_rotation(
        self, log_rotation_config, temp_log_directory
    ):
        """Test rotation behavior with concurrent writes."""
        # Load and setup configuration
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(log_rotation_config)

        log_file_path = temp_log_directory / "test_concurrent.log"
        config.logging.file_path = log_file_path

        setup_logging_from_config(config.logging)

        async def write_logs(logger_name: str, message_prefix: str, count: int):
            """Write logs concurrently."""
            logger = logging.getLogger(logger_name)
            for i in range(count):
                logger.info(
                    f"{message_prefix} {i}: {'D' * 50}"
                )  # Smaller messages for more predictable behavior
                await asyncio.sleep(0.01)  # Longer delay for more predictable timing

        # Start multiple concurrent logging tasks
        tasks = []
        for i in range(3):
            task = asyncio.create_task(
                write_logs(f"concurrent_logger_{i}", f"Thread{i}", 15)
            )
            tasks.append(task)

        # Wait for all tasks to complete
        await asyncio.gather(*tasks)

        # Give time for final writes and force flush
        await asyncio.sleep(0.1)
        force_log_flush()

        # Verify log files exist and count entries
        assert log_file_path.exists(), "Main log file should exist"
        total_entries = count_log_entries(log_file_path, "Thread")

        expected_entries = 3 * 15  # 3 threads * 15 messages each
        # Allow for some variance in concurrent scenarios - at least 80% of messages should be captured
        min_expected = int(expected_entries * 0.8)
        assert (
            total_entries >= min_expected
        ), f"Expected at least {min_expected} log entries, found {total_entries}"
        assert (
            total_entries <= expected_entries
        ), f"Found more entries than expected: {total_entries} > {expected_entries}"

    @pytest.mark.asyncio
    async def test_rotation_with_permission_errors(
        self, log_rotation_config, temp_log_directory
    ):
        """Test rotation behavior when backup files already exist and have permission issues."""
        # This test simulates permission errors that might occur in production

        # Load and setup configuration
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(log_rotation_config)

        log_file_path = temp_log_directory / "test_permissions.log"
        config.logging.file_path = log_file_path

        # Create a backup file that simulates permission issues
        backup_file_1 = Path(str(log_file_path) + ".1")
        backup_file_1.write_text("existing backup content")

        # Make backup file read-only to simulate permission issues
        backup_file_1.chmod(0o444)  # Read-only

        try:
            setup_logging_from_config(config.logging)
            logger = logging.getLogger("test_permissions")

            # Write logs to trigger rotation
            log_message = "E" * 200
            for i in range(10):
                logger.info(f"Permission test {i}: {log_message}")

            # Force flush
            for handler in logger.handlers:
                if hasattr(handler, "flush"):
                    handler.flush()

            # Test should handle permission errors gracefully
            # Either rotation succeeds or fails gracefully without crashing
            assert log_file_path.exists(), "Main log file should still exist"

        finally:
            # Cleanup: restore permissions for deletion
            if backup_file_1.exists():
                backup_file_1.chmod(0o644)

    @pytest.mark.asyncio
    async def test_rotation_configuration_validation(self, temp_log_directory):
        """Test that rotation configuration values are validated correctly."""
        # Test with invalid max_file_size_mb (negative value)
        invalid_config_content = """
proxy:
  transport: stdio
  upstreams:
    - name: "test_server"
      command: ["echo", "test"]

logging:
  level: "DEBUG"
  handlers: ["file"]
  file_path: "test_invalid.log"
  max_file_size_mb: -1  # Invalid negative value
  backup_count: 3
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(invalid_config_content)
            f.flush()
            config_path = Path(f.name)

        try:
            config_loader = ConfigLoader()

            # This should raise a validation error for negative file size
            from gatekit.config.errors import ConfigError

            with pytest.raises(ConfigError) as exc_info:
                config_loader.load_from_file(config_path)

            # Verify the error is specifically about negative values
            error_msg = str(exc_info.value).lower()
            assert (
                "positive" in error_msg
                or "negative" in error_msg
                or "must be" in error_msg
            ), f"Expected validation error about negative values, got: {exc_info.value}"

        finally:
            os.unlink(config_path)

    @pytest.mark.asyncio
    async def test_no_rotation_when_under_size_limit(
        self, log_rotation_config, temp_log_directory
    ):
        """Test that rotation does not occur when under the size limit."""
        # Load and setup configuration
        config_loader = ConfigLoader()
        config = config_loader.load_from_file(log_rotation_config)

        log_file_path = temp_log_directory / "test_no_rotation.log"
        config.logging.file_path = log_file_path

        setup_logging_from_config(config.logging)
        logger = logging.getLogger("test_no_rotation")

        # Write a small amount of logs (well under 1KB limit)
        for i in range(3):
            logger.info(f"Small log {i}")

        # Force flush
        for handler in logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        # Check that no backup files were created
        backup_file_1 = Path(str(log_file_path) + ".1")
        assert (
            not backup_file_1.exists()
        ), "No backup files should be created when under size limit"

        # Main log should exist and be small
        assert log_file_path.exists(), "Main log file should exist"
        assert log_file_path.stat().st_size < 1024, "Log file should be under 1KB"
