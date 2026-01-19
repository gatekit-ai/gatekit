"""Tests for JsonAuditingPlugin path resolution improvements.

This test suite follows Test-Driven Development (TDD) methodology to verify
that JsonAuditingPlugin implements proper path resolution with the PathResolvablePlugin
interface and replaces silent fallbacks with proper error reporting.
"""

import os
import pytest
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock
from gatekit.plugins.auditing.json_lines import JsonAuditingPlugin
from gatekit.plugins.interfaces import PathResolvablePlugin

# Import shared logging cleanup helpers (Windows compatibility)
from conftest import close_all_logging_handlers as _close_all_logging_handlers


def get_nonexistent_absolute_path() -> str:
    """Get an absolute path that definitely doesn't exist on any platform."""
    # Use a UUID to ensure the path doesn't exist
    random_dir = f"nonexistent_{uuid.uuid4().hex}"
    # Use Path to build paths correctly on all platforms (avoids escape char issues)
    if sys.platform == "win32":
        base = Path(tempfile.gettempdir())
    else:
        base = Path("/tmp")
    return str(base / random_dir / "deeply" / "nested" / "test.log")


def paths_equal(p1, p2) -> bool:
    """Compare paths in a cross-platform way, normalizing separators."""
    return Path(p1).resolve() == Path(p2).resolve()


class TestJsonAuditingPluginPathResolution:
    """Test JsonAuditingPlugin path resolution with PathResolvablePlugin interface."""

    def test_implements_path_resolvable_interface(self):
        """Test that JsonAuditingPlugin implements PathResolvablePlugin interface."""
        # JsonAuditingPlugin should implement PathResolvablePlugin
        assert issubclass(JsonAuditingPlugin, PathResolvablePlugin)

        # Test that it can be instantiated
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "test.log")
            config = {"output_file": log_file, "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Should have PathResolvablePlugin methods
            assert hasattr(plugin, "set_config_directory")
            assert hasattr(plugin, "validate_paths")

    def test_set_config_directory_resolves_relative_paths(self):
        """Test that set_config_directory properly resolves relative paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Use a relative path within the temp directory
            relative_path = "logs/audit.log"
            config = {
                "output_file": relative_path,
                "critical": True,
            }  # Use critical=True to prevent file creation
            plugin = JsonAuditingPlugin(config)

            # Relative paths remain as provided until the config directory is known
            assert plugin.output_file == relative_path

            # Set config directory - should resolve relative path
            config_dir = Path(temp_dir) / "config_dir"
            plugin.set_config_directory(config_dir)

            # Should have resolved relative path
            expected_path = config_dir / relative_path
            assert Path(plugin.output_file) == expected_path.resolve()

    def test_set_config_directory_preserves_absolute_paths(self):
        """Test that set_config_directory preserves absolute paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Use a real absolute path that exists
            absolute_path = os.path.join(temp_dir, "audit.log")
            config = {"output_file": absolute_path, "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Absolute paths are resolved to their canonical form for security
            expected_resolved = Path(absolute_path).resolve()
            assert Path(plugin.output_file) == expected_resolved

            # Set config directory to a DIFFERENT directory - should preserve absolute path
            with tempfile.TemporaryDirectory() as other_dir:
                plugin.set_config_directory(other_dir)

                # Should still resolve to the same canonical absolute path (not relative to other_dir)
                assert Path(plugin.output_file) == expected_resolved

    def test_set_config_directory_handles_home_expansion(self):
        """Test that set_config_directory handles home directory expansion."""
        config = {
            "output_file": "~/logs/audit.log",
            "critical": True,
        }  # Use critical=True to prevent file creation
        plugin = JsonAuditingPlugin(config)

        # Set config directory
        config_dir = Path("/config/dir")
        plugin.set_config_directory(config_dir)

        # Should have expanded ~ to home directory (not relative to config)
        import os

        expected_path = Path(os.path.expanduser("~/logs/audit.log"))
        assert Path(plugin.output_file) == expected_path

    def test_set_config_directory_with_invalid_type_raises_error(self):
        """Test that set_config_directory raises error for invalid config_directory type."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "test.log")
            config = {"output_file": log_file, "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Should raise TypeError for invalid type
            with pytest.raises(TypeError, match="config_directory must be str or Path"):
                plugin.set_config_directory(123)  # Invalid type

    def test_validate_paths_returns_empty_for_valid_paths(self):
        """Test that validate_paths returns empty list for valid paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "test.log")
            config = {"output_file": log_file, "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Should return no errors for valid path
            errors = plugin.validate_paths()
            assert errors == []

    def test_validate_paths_skips_nonexistent_directories(self):
        """Test that validate_paths skips non-existent directories (they'll be auto-created).

        Per ADR-012 R3.3: "Create parent directories if they don't exist"
        Validation no longer errors on missing directories - they are created at runtime.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Path with non-existent parent directories
            nonexistent_path = str(Path(temp_dir) / "nonexistent" / "subdir" / "audit.log")
            config = {"output_file": nonexistent_path, "critical": False}

            plugin = JsonAuditingPlugin(config)
            errors = plugin.validate_paths()

            # No validation error - directory will be auto-created at runtime
            assert errors == []

    def test_validate_paths_returns_errors_for_unwritable_directory(self):
        """Test that validate_paths returns errors for unwritable directory.

        We mock os.access because:
        1. On Windows, os.chmod doesn't actually restrict permissions
        2. On Unix, changing permissions requires specific conditions
        3. This test is about validation logic, not OS permission enforcement

        The mock simulates what happens when a user tries to write to a
        directory they don't have write access to.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "test.log")
            config = {"output_file": log_file, "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Mock os.access to simulate a directory without write permission
            temp_dir_resolved = Path(temp_dir).resolve()
            original_access = os.access

            def mock_access(path, mode):
                # Return False for write check on temp_dir (the parent of our log file)
                if mode == os.W_OK and Path(path).resolve() == temp_dir_resolved:
                    return False  # Simulate no write permission
                return original_access(path, mode)

            with patch("os.access", side_effect=mock_access):
                # Should return error for unwritable directory
                errors = plugin.validate_paths()
                assert len(errors) == 1
                assert "No write permission" in errors[0]


class TestJsonAuditingPluginImprovedErrorHandling:
    """Test improved error handling that replaces silent fallbacks."""

    def test_path_resolution_error_raises_for_critical_plugin(self):
        """Test that path resolution errors raise exceptions for critical plugins."""
        # Mock resolve_config_path to raise an error
        with patch(
            "gatekit.plugins.auditing.base.resolve_config_path"
        ) as mock_resolve:
            mock_resolve.side_effect = ValueError("Invalid path")

            config = {
                "output_file": "test.log",
                "critical": True,  # Should be honored for audit plugins
            }

            plugin = JsonAuditingPlugin(config)

            # Audit plugins should respect critical configuration
            assert plugin.critical is True

            # Path errors should raise for critical audit plugins
            with pytest.raises(ValueError, match="Invalid path"):
                plugin.set_config_directory("/config")

    def test_path_resolution_error_logs_for_non_critical_plugin(self):
        """Test that path resolution errors are logged for non-critical plugins."""
        # Mock resolve_config_path to raise an error
        with (
            patch(
                "gatekit.plugins.auditing.base.resolve_config_path"
            ) as mock_resolve,
            patch(
                "gatekit.plugins.auditing.base.logging.getLogger"
            ) as mock_get_logger,
        ):

            mock_resolve.side_effect = ValueError("Invalid path")
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            config = {"output_file": "test.log", "critical": False}

            # Should handle error gracefully for non-critical plugin
            plugin = JsonAuditingPlugin(config)

            # Set config directory - should log error but not raise
            plugin.set_config_directory("/config")

            # Should have logged the error using exception()
            mock_logger.exception.assert_called()
            error_call = mock_logger.exception.call_args[0][0]
            assert "path resolution failed" in error_call.lower()

    def test_no_silent_fallback_on_path_resolution_failure(self, tmp_path):
        """Test that there are no silent fallbacks on path resolution failure."""
        # Mock resolve_config_path to raise an error
        with patch(
            "gatekit.plugins.auditing.base.resolve_config_path"
        ) as mock_resolve:
            mock_resolve.side_effect = ValueError("Invalid path")

            relative_log_path = tmp_path / "relative_path.log"
            config = {
                "output_file": str(relative_log_path),
                "config_directory": "/config",
                "critical": False,
            }

            # For non-critical plugins, should not silently fall back
            # Instead should use the original path and log the error
            plugin = JsonAuditingPlugin(config)

            # Should still have the original path, not a "resolved" fallback
            assert plugin.output_file == str(relative_log_path)

    def test_proper_error_context_in_initialization_failure(self):
        """Test that initialization failures are handled gracefully for audit plugins."""
        # Use a path in a temp directory - the directory exists but we'll mock mkdir to fail
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = os.path.join(temp_dir, "subdir", "test.log")
            config = {"output_file": log_path, "critical": True}

            # Mock mkdir to simulate a permission error during directory creation
            # This tests the error handling path for critical plugins
            with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
                # Critical audit plugins should raise when they can't initialize
                with pytest.raises(
                    Exception, match="Critical auditing plugin.*failed to initialize"
                ):
                    JsonAuditingPlugin(config)

    def test_initialization_provides_absolute_path_guidance(self):
        """Test that initialization failure provides guidance about absolute paths."""
        # Use a relative path that will fail once we attempt to resolve it
        # Mock os.access to return False for write permission to force an error
        with (
            patch("os.access", return_value=False),
            patch("pathlib.Path.mkdir") as mock_mkdir,
        ):
            # Make mkdir fail to trigger the exception path
            mock_mkdir.side_effect = PermissionError("Permission denied")

            relative_path = "logs/test.log"
            config = {"output_file": relative_path, "critical": True}
            plugin = JsonAuditingPlugin(config)

            # Critical audit plugins should raise once resolution occurs via config directory
            with pytest.raises(
                Exception, match="Critical auditing plugin.*failed to initialize"
            ):
                plugin.set_config_directory("/config")

    def test_set_config_directory_validates_path_type(self):
        """Test that set_config_directory validates path type properly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "test.log")
            config = {"output_file": log_file, "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Should validate input type
            with pytest.raises(TypeError, match="config_directory must be str or Path"):
                plugin.set_config_directory(None)

            with pytest.raises(TypeError, match="config_directory must be str or Path"):
                plugin.set_config_directory(123)

            with pytest.raises(TypeError, match="config_directory must be str or Path"):
                plugin.set_config_directory(["path"])

    def test_validate_paths_allows_nonexistent_directories(self):
        """Test that validate_paths allows non-existent directories (auto-created at runtime).

        Per ADR-012 R3.3: "Create parent directories if they don't exist"
        """
        # Path with non-existent parent directory
        nonexistent_path = "/definitely/does/not/exist/test.log"
        config = {"output_file": nonexistent_path, "critical": False}
        plugin = JsonAuditingPlugin(config)

        errors = plugin.validate_paths()
        # No validation error - directory will be auto-created at runtime
        assert len(errors) == 0


class TestJsonAuditingPluginConfigDirectoryHandling:
    """Test config_directory parameter handling improvements."""

    def test_config_directory_none_uses_raw_path(self, tmp_path):
        """Test that config_directory=None uses raw path without resolution."""
        relative_log_path = tmp_path / "relative_path.log"
        config = {
            "output_file": str(relative_log_path),
            "config_directory": None,
            "critical": False,
        }
        plugin = JsonAuditingPlugin(config)

        # Should use raw path when config_directory is None
        assert plugin.output_file == str(relative_log_path)

    def test_config_directory_present_resolves_path(self):
        """Test that presence of config_directory triggers path resolution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {"output_file": "logs/audit.log", "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Set config directory after initialization
            plugin.set_config_directory(temp_dir)

            # Should have resolved path relative to config directory
            expected_path = Path(temp_dir) / "logs/audit.log"
            assert Path(plugin.output_file) == expected_path.resolve()

    def test_home_expansion_works_without_config_directory(self):
        """Test that home expansion works even without config_directory."""
        config = {
            "output_file": "~/test.log",
            "critical": True,  # Use critical=True to prevent file creation
        }
        plugin = JsonAuditingPlugin(config)

        # Should have expanded ~ even without config_directory
        # Use Path for cross-platform comparison (normalizes separators)
        expected_path = Path(os.path.expanduser("~/test.log"))
        assert Path(plugin.output_file) == expected_path

    def test_invalid_config_directory_type_handled_properly(self):
        """Test that invalid config_directory types are handled properly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "test.log")
            config = {
                "output_file": log_file,
                "config_directory": 123,  # Invalid type
                "critical": False,
            }

            # Should handle invalid type gracefully and resolve path to canonical form
            plugin = JsonAuditingPlugin(config)
            expected_resolved = Path(log_file).resolve()
            assert Path(plugin.output_file) == expected_resolved

    def test_logging_reconfiguration_on_path_change(self):
        """Test that logging reconfigures when set_config_directory changes the output path."""
        with (
            tempfile.TemporaryDirectory() as temp_dir1,
            tempfile.TemporaryDirectory() as temp_dir2,
        ):

            # Initial relative path
            config = {"output_file": "audit.log", "critical": False}
            plugin = JsonAuditingPlugin(config)

            # Set first config directory - should trigger logging setup
            plugin.set_config_directory(temp_dir1)
            initial_path = plugin.output_file
            initial_logger_name = plugin._get_logger_name()

            # Verify logging is set up
            assert plugin._logging_setup_complete
            assert plugin.logger is not None
            initial_handler = plugin.file_handler

            # Log a message to the first location
            from gatekit.plugins.interfaces import (
                PluginResult,
                ProcessingPipeline,
                PipelineStage,
                StageOutcome,
                PipelineOutcome,
            )
            from gatekit.protocol.messages import MCPRequest

            request = MCPRequest(
                jsonrpc="2.0",
                id="test-reconfig",
                method="tools/call",
                params={"name": "test_tool"},
            )
            # Create proper pipeline for auditing
            pipeline = ProcessingPipeline(original_content=request)
            result = PluginResult(
                allowed=True, reason="Test before reconfigure", metadata={}
            )
            stage = PipelineStage(
                plugin_name="test_plugin",
                plugin_type="security",
                input_content=request,
                output_content=request,
                content_hash="hash",
                result=result,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline.add_stage(stage)
            pipeline.pipeline_outcome = PipelineOutcome.ALLOWED

            import asyncio

            asyncio.run(plugin.log_request(request, pipeline, "test-server"))

            # Verify first file was created and has content
            assert os.path.exists(initial_path)
            with open(initial_path, "r") as f:
                content1 = f.read()
            assert len(content1) > 0
            assert "Test before reconfigure" in content1

            # Change config directory - should trigger reconfiguration
            plugin.set_config_directory(temp_dir2)
            new_path = plugin.output_file
            new_logger_name = plugin._get_logger_name()

            # Verify path changed
            assert new_path != initial_path
            assert Path(new_path).parent.resolve() == Path(temp_dir2).resolve()

            # Verify logger name changed (different file hash)
            assert new_logger_name != initial_logger_name

            # Verify logging is still set up with new handler
            assert plugin._logging_setup_complete
            assert plugin.logger is not None
            assert plugin.file_handler is not None
            assert plugin.file_handler != initial_handler  # Should be a new handler

            # Log a message to the new location
            request2 = MCPRequest(
                jsonrpc="2.0",
                id="test-reconfig-2",
                method="tools/call",
                params={"name": "test_tool_2"},
            )
            # Create proper pipeline for second auditing
            pipeline2 = ProcessingPipeline(original_content=request2)
            result2 = PluginResult(
                allowed=True, reason="Test after reconfigure", metadata={}
            )
            stage2 = PipelineStage(
                plugin_name="test_plugin",
                plugin_type="security",
                input_content=request2,
                output_content=request2,
                content_hash="hash",
                result=result2,
                processing_time_ms=1.0,
                outcome=StageOutcome.ALLOWED,
                security_evaluated=True,
            )
            pipeline2.add_stage(stage2)
            pipeline2.pipeline_outcome = PipelineOutcome.ALLOWED

            asyncio.run(plugin.log_request(request2, pipeline2, "test-server"))

            # Verify new file was created and has content
            assert os.path.exists(new_path)
            with open(new_path, "r") as f:
                content2 = f.read()
            assert len(content2) > 0
            assert "Test after reconfigure" in content2

            # Verify old file still has only old content
            with open(initial_path, "r") as f:
                content1_after = f.read()
            assert content1_after == content1  # Unchanged
            assert "Test after reconfigure" not in content1_after

            # Cleanup before temp directory is removed (required for Windows)
            plugin.cleanup()
            _close_all_logging_handlers()
