"""CLI smoke tests for gatekit-gateway.

These tests verify that the gateway boots successfully with various configurations.
They are slow (subprocess startup) and skipped by default. Run with --run-slow.

Unlike other integration tests, these test the actual CLI entry point and
configuration loading from files - the real user experience.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

# Timeout for waiting for gateway startup (seconds)
STARTUP_TIMEOUT = 15


def _write_config(tmp_path: Path, name: str, content: str) -> Path:
    """Write a config file and return its path."""
    config_path = tmp_path / f"{name}.yaml"
    config_path.write_text(dedent(content))
    return config_path


@pytest.fixture
def minimal_security_config(tmp_path: Path) -> Path:
    """Minimal config with a security plugin."""
    return _write_config(
        tmp_path,
        "security",
        """
        proxy:
          transport: stdio
          upstreams:
            - name: test-server
              command: ["true"]

        plugins:
          security:
            _global:
              - handler: basic_secrets_filter
        """,
    )


@pytest.fixture
def minimal_auditing_config(tmp_path: Path) -> Path:
    """Minimal config with an auditing plugin."""
    log_file = tmp_path / "audit.jsonl"
    return _write_config(
        tmp_path,
        "auditing",
        f"""
        proxy:
          transport: stdio
          upstreams:
            - name: test-server
              command: ["true"]

        plugins:
          auditing:
            _global:
              - handler: audit_jsonl
                config:
                  output_file: "{log_file}"
        """,
    )


@pytest.fixture
def minimal_middleware_config(tmp_path: Path) -> Path:
    """Minimal config with a middleware plugin."""
    return _write_config(
        tmp_path,
        "middleware",
        """
        proxy:
          transport: stdio
          upstreams:
            - name: test-server
              command: ["true"]

        plugins:
          middleware:
            test-server:
              - handler: tool_manager
                config:
                  tools:
                    - tool: read_file
        """,
    )


@pytest.fixture
def minimal_bare_config(tmp_path: Path) -> Path:
    """Absolute minimal config - no plugins, just proxy and upstream."""
    return _write_config(
        tmp_path,
        "bare",
        """
        proxy:
          transport: stdio
          upstreams:
            - name: test-server
              command: ["true"]
        """,
    )


def _boot_gateway_and_wait_for_ready(config_path: Path, timeout: int = STARTUP_TIMEOUT) -> None:
    """Boot the gateway and wait for it to signal readiness.

    Args:
        config_path: Path to the configuration file.
        timeout: Maximum seconds to wait for ready signal.

    Raises:
        AssertionError: If gateway doesn't reach ready state.
    """
    proc = subprocess.Popen(
        ["uv", "run", "gatekit-gateway", "--config", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        output_lines = []
        import select

        # Use select for timeout on stdout (Unix only, but that's fine for dev)
        while True:
            # Check if there's data to read (with timeout)
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
            if not ready:
                # Timeout waiting for output
                proc.terminate()
                proc.wait(timeout=5)
                raise AssertionError(
                    f"Gateway startup timed out after {timeout}s. Output:\n"
                    + "\n".join(output_lines[-20:])
                )

            line = proc.stdout.readline()
            if not line:
                # EOF - process ended
                break

            sys.stdout.write(line)
            sys.stdout.flush()
            output_lines.append(line.rstrip())

            if "Gatekit is ready" in line:
                # Success - gateway booted
                return

        # If we get here, process ended without ready signal
        raise AssertionError(
            "Gateway exited without reaching ready state. Output:\n"
            + "\n".join(output_lines[-20:])
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.mark.smoke
@pytest.mark.slow
class TestGatewayStartup:
    """Smoke tests for gateway CLI startup.

    These tests verify that gatekit-gateway boots successfully with
    various configuration types. They test the actual CLI entry point,
    not the MCPProxy class directly.
    """

    def test_boots_with_bare_config(self, minimal_bare_config: Path) -> None:
        """Gateway boots with minimal config (no plugins)."""
        _boot_gateway_and_wait_for_ready(minimal_bare_config)

    def test_boots_with_security_plugin(self, minimal_security_config: Path) -> None:
        """Gateway boots with a security plugin configured."""
        _boot_gateway_and_wait_for_ready(minimal_security_config)

    def test_boots_with_auditing_plugin(self, minimal_auditing_config: Path) -> None:
        """Gateway boots with an auditing plugin configured."""
        _boot_gateway_and_wait_for_ready(minimal_auditing_config)

    def test_boots_with_middleware_plugin(self, minimal_middleware_config: Path) -> None:
        """Gateway boots with a middleware plugin configured."""
        _boot_gateway_and_wait_for_ready(minimal_middleware_config)


@pytest.mark.smoke
@pytest.mark.slow
class TestGatewayStartupErrors:
    """Tests for gateway startup error handling."""

    def test_fails_with_missing_config(self, tmp_path: Path) -> None:
        """Gateway fails gracefully when config file doesn't exist."""
        nonexistent = tmp_path / "does_not_exist.yaml"

        proc = subprocess.run(
            ["uv", "run", "gatekit-gateway", "--config", str(nonexistent)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode != 0
        # Should mention the missing file in error output
        assert "does_not_exist.yaml" in proc.stderr or "does_not_exist.yaml" in proc.stdout

    def test_fails_with_invalid_yaml(self, tmp_path: Path) -> None:
        """Gateway fails gracefully with invalid YAML syntax."""
        bad_config = _write_config(
            tmp_path,
            "bad",
            """
            proxy:
              listen: stdio
              upstreams:
                - this: is: invalid: yaml: syntax
            """,
        )

        proc = subprocess.run(
            ["uv", "run", "gatekit-gateway", "--config", str(bad_config)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode != 0

    def test_fails_with_invalid_config_schema(self, tmp_path: Path) -> None:
        """Gateway fails gracefully with valid YAML but invalid config schema."""
        bad_schema = _write_config(
            tmp_path,
            "bad_schema",
            """
            proxy:
              listen: stdio
              # Missing required 'upstreams' field
            """,
        )

        proc = subprocess.run(
            ["uv", "run", "gatekit-gateway", "--config", str(bad_schema)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode != 0
