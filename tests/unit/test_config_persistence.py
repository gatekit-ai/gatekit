"""Tests for configuration persistence (atomic writes and save_config)."""

import tempfile
from pathlib import Path
import pytest
import yaml

from gatekit.config.models import ProxyConfig, UpstreamConfig, TimeoutConfig
from gatekit.config.persistence import save_config
from gatekit.config.errors import ConfigWriteError
from gatekit.config.loader import ConfigLoader
from gatekit.utils.filesystem import atomic_write_text


class TestConfigWriteError:
    """Tests for ConfigWriteError exception class."""

    def test_config_write_error_basic_attributes(self):
        """ConfigWriteError should store path, reason, and inherit from ConfigError."""
        path = Path("/tmp/test.yaml")
        reason = "Permission denied"

        error = ConfigWriteError(path, reason)

        assert error.path == path
        assert error.cause is None
        assert "Failed to write config to" in str(error)
        assert str(path) in str(error)
        assert reason in str(error)
        assert error.error_type == "write_error"

    def test_config_write_error_with_cause(self):
        """ConfigWriteError should preserve the original exception as cause."""
        path = Path("/tmp/test.yaml")
        reason = "Permission denied"
        original_error = PermissionError("Cannot write to file")

        error = ConfigWriteError(path, reason, cause=original_error)

        assert error.path == path
        assert error.cause == original_error
        assert isinstance(error.cause, PermissionError)

    def test_config_write_error_inherits_config_error(self):
        """ConfigWriteError should inherit from ConfigError."""
        from gatekit.config.errors import ConfigError

        path = Path("/tmp/test.yaml")
        error = ConfigWriteError(path, "test reason")

        assert isinstance(error, ConfigError)


class TestAtomicWriteText:
    """Tests for atomic_write_text filesystem helper."""

    def test_atomic_write_creates_file(self):
        """atomic_write_text should create a new file with the given content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            content = "Hello, world!"

            atomic_write_text(file_path, content)

            assert file_path.exists()
            assert file_path.read_text() == content

    def test_atomic_write_overwrites_existing_file(self):
        """atomic_write_text should overwrite an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            file_path.write_text("Old content")

            new_content = "New content"
            atomic_write_text(file_path, new_content)

            assert file_path.read_text() == new_content

    def test_atomic_write_uses_temp_file(self):
        """atomic_write_text should use a temp file in the same directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            content = "Test content"

            # Track files in directory before and after
            files_before = set(Path(tmpdir).iterdir())
            atomic_write_text(file_path, content)
            files_after = set(Path(tmpdir).iterdir())

            # Should only have our target file, no temp files left behind
            assert files_after == {file_path}

    def test_atomic_write_cleans_up_temp_file_on_error(self):
        """atomic_write_text should clean up temp file even on failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a directory where we want to write (will cause rename to fail)
            file_path = Path(tmpdir) / "test"
            file_path.mkdir()

            # This should fail because we're trying to write to a directory
            with pytest.raises(Exception):
                atomic_write_text(file_path, "content")

            # No temp files should be left behind
            remaining_files = list(Path(tmpdir).iterdir())
            temp_files = [f for f in remaining_files if ".tmp" in f.name]
            assert len(temp_files) == 0

    def test_atomic_write_preserves_utf8_encoding(self):
        """atomic_write_text should preserve UTF-8 encoding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.txt"
            content = "Hello 世界 🌍"

            atomic_write_text(file_path, content)

            assert file_path.read_text(encoding="utf-8") == content


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config_creates_valid_yaml(self):
        """save_config should create a valid YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            save_config(config_path, config)

            assert config_path.exists()
            # Verify it's valid YAML
            with open(config_path) as f:
                parsed = yaml.safe_load(f)
            assert parsed is not None
            assert "proxy" in parsed

    def test_save_config_without_header(self):
        """save_config should not add header when header=None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            save_config(config_path, config, header=None)

            content = config_path.read_text()
            # Should start with "proxy:", not with comments
            assert content.strip().startswith("proxy:")

    def test_save_config_with_header(self):
        """save_config should add header when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            header = "# Test Header\n# Generated by test\n"
            save_config(config_path, config, header=header)

            content = config_path.read_text()
            assert content.startswith(header)
            # Verify YAML is still valid
            with open(config_path) as f:
                parsed = yaml.safe_load(f)
            assert parsed is not None

    def test_save_config_with_empty_header(self):
        """save_config should treat empty string header as no header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            save_config(config_path, config, header="")

            content = config_path.read_text()
            # Should start with "proxy:", not with comments or empty lines
            assert content.strip().startswith("proxy:")

    def test_save_config_allow_incomplete_false_rejects_drafts(self):
        """save_config should reject draft configs when allow_incomplete=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            # Create config with draft upstream
            upstream = UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["node", "server.js"],
            )
            upstream.is_draft = True

            config = ProxyConfig(
                transport="stdio",
                upstreams=[upstream],
                timeouts=TimeoutConfig(),
            )

            # Should raise ValueError for draft config
            with pytest.raises(ValueError, match="incomplete"):
                save_config(config_path, config, allow_incomplete=False)

    def test_save_config_allow_incomplete_true_accepts_drafts(self):
        """save_config should accept draft configs when allow_incomplete=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            # Create config with draft upstream
            upstream = UpstreamConfig(
                name="test-server",
                transport="stdio",
                command=["node", "server.js"],
            )
            upstream.is_draft = True

            config = ProxyConfig(
                transport="stdio",
                upstreams=[upstream],
                timeouts=TimeoutConfig(),
            )

            # Should succeed with allow_incomplete=True
            save_config(config_path, config, allow_incomplete=True)

            assert config_path.exists()

    def test_save_config_atomic_true_uses_atomic_write(self):
        """save_config should use atomic writes by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"
            config_path.write_text("old content")

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            save_config(config_path, config, atomic=True)

            # File should be updated
            content = config_path.read_text()
            assert "old content" not in content
            assert "proxy:" in content

            # No temp files should remain
            temp_files = [f for f in Path(tmpdir).iterdir() if ".tmp" in f.name]
            assert len(temp_files) == 0

    def test_save_config_atomic_false_direct_write(self):
        """save_config should support direct write when atomic=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            save_config(config_path, config, atomic=False)

            assert config_path.exists()
            content = config_path.read_text()
            assert "proxy:" in content

    def test_save_config_raises_config_write_error_on_failure(self):
        """save_config should raise ConfigWriteError on write failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Try to write to a directory (will fail)
            config_path = Path(tmpdir) / "somedir"
            config_path.mkdir()

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            with pytest.raises(ConfigWriteError) as exc_info:
                save_config(config_path, config)

            error = exc_info.value
            assert error.path == config_path
            assert error.cause is not None


class TestRoundTripSaveLoad:
    """Tests for round-trip save→load→save stability."""

    def test_roundtrip_preserves_semantic_equivalence(self):
        """Loading and re-saving config should preserve semantic meaning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            # Create original config
            original_config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            # Save, load, save again
            save_config(config_path, original_config)

            loader = ConfigLoader()
            loaded_config = loader.load_from_file(config_path)

            config_path2 = Path(tmpdir) / "test2.yaml"
            save_config(config_path2, loaded_config)

            # Load again and compare
            final_config = loader.load_from_file(config_path2)

            # Semantic comparison (not byte-for-byte)
            assert final_config.transport == original_config.transport
            assert len(final_config.upstreams) == len(original_config.upstreams)
            assert final_config.upstreams[0].name == original_config.upstreams[0].name
            assert final_config.upstreams[0].command == original_config.upstreams[0].command

    def test_roundtrip_with_header_preserves_config(self):
        """Round-trip with header should preserve config data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
            )

            header = "# Generated Config\n# Test Header\n"
            save_config(config_path, config, header=header)

            # Load and verify
            loader = ConfigLoader()
            loaded_config = loader.load_from_file(config_path)

            assert loaded_config.transport == config.transport
            assert len(loaded_config.upstreams) == 1
            assert loaded_config.upstreams[0].name == "test-server"

    def test_roundtrip_formatting_may_differ(self):
        """Round-trip may change formatting but preserves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"

            # Write a config manually with specific formatting
            yaml_content = """proxy:
  transport: stdio
  upstreams:
    - name: test-server
      transport: stdio
      command:
        - node
        - server.js
"""
            config_path.write_text(yaml_content)

            # Load and save
            loader = ConfigLoader()
            config = loader.load_from_file(config_path)

            config_path2 = Path(tmpdir) / "test2.yaml"
            save_config(config_path2, config)

            # Content may differ (indentation, key order, etc.)
            content1 = config_path.read_text()
            content2 = config_path2.read_text()
            # But both should be valid and equivalent
            loader2 = ConfigLoader()
            config1 = loader.load_from_file(config_path)
            config2 = loader2.load_from_file(config_path2)

            assert config1.transport == config2.transport
            assert config1.upstreams[0].name == config2.upstreams[0].name

    def test_roundtrip_preserves_logging_config(self):
        """Round-trip should preserve all logging configuration fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test.yaml"
            log_path = Path(tmpdir) / "gatekit.log"

            # Create config with custom logging settings
            from gatekit.config.models import LoggingConfig

            config = ProxyConfig(
                transport="stdio",
                upstreams=[
                    UpstreamConfig(
                        name="test-server",
                        transport="stdio",
                        command=["node", "server.js"],
                    )
                ],
                timeouts=TimeoutConfig(),
                logging=LoggingConfig(
                    level="DEBUG",
                    handlers=["stderr", "file"],
                    file_path=log_path,
                    max_file_size_mb=25.5,
                    backup_count=10,
                    format="%(levelname)s: %(message)s",
                    date_format="%Y/%m/%d %H:%M:%S",
                ),
            )

            # Save and load
            save_config(config_path, config)

            loader = ConfigLoader()
            loaded_config = loader.load_from_file(config_path)

            # Verify all logging fields are preserved
            assert loaded_config.logging is not None
            assert loaded_config.logging.level == "DEBUG"
            assert loaded_config.logging.handlers == ["stderr", "file"]
            assert str(loaded_config.logging.file_path) == str(log_path)
            assert loaded_config.logging.max_file_size_mb == 25.5
            assert loaded_config.logging.backup_count == 10
            assert loaded_config.logging.format == "%(levelname)s: %(message)s"
            assert loaded_config.logging.date_format == "%Y/%m/%d %H:%M:%S"
