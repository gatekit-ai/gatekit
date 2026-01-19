"""Integration tests for console script functionality.

Tests that the gatekit console script works correctly.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from gatekit._version import __version__


def get_scripts_dir() -> Path:
    """Get the Scripts/bin directory for the current Python environment."""
    if sys.platform == "win32":
        return Path(sys.prefix) / "Scripts"
    else:
        return Path(sys.prefix) / "bin"


def get_gatekit_exe() -> str:
    """Get path to gatekit executable."""
    scripts_dir = get_scripts_dir()
    exe_name = "gatekit.exe" if sys.platform == "win32" else "gatekit"
    exe_path = scripts_dir / exe_name
    if exe_path.exists():
        return str(exe_path)
    # Fall back to PATH lookup
    path = shutil.which("gatekit")
    return path if path else "gatekit"


def get_gatekit_gateway_exe() -> str:
    """Get path to gatekit-gateway executable."""
    scripts_dir = get_scripts_dir()
    exe_name = "gatekit-gateway.exe" if sys.platform == "win32" else "gatekit-gateway"
    exe_path = scripts_dir / exe_name
    if exe_path.exists():
        return str(exe_path)
    # Fall back to PATH lookup
    path = shutil.which("gatekit-gateway")
    return path if path else "gatekit-gateway"


class TestConsoleScript:
    """Test the gatekit console script functionality."""

    def test_console_script_help(self):
        """Test that gatekit --help works and shows correct program name."""
        # Use sys.executable -m for cross-platform compatibility
        result = subprocess.run(
            [sys.executable, "-m", "gatekit", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "Gatekit Security Gateway Configuration Interface" in result.stdout
        assert "CONFIG_FILE" in result.stdout
        assert "--verbose" in result.stdout

    def test_console_script_version(self):
        """Test that gatekit --version works."""
        result = subprocess.run(
            [sys.executable, "-m", "gatekit", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert f"Gatekit v{__version__}" in result.stdout

    def test_console_script_config_file_error(self):
        """Test that gatekit launches TUI gracefully with missing config file."""
        # Use echo to provide input to TUI and then exit
        result = subprocess.run(
            [sys.executable, "-m", "gatekit", "/nonexistent/config.yaml"],
            input="\x03",  # Send Ctrl+C to exit TUI gracefully
            text=True,
            timeout=5,
        )

        # TUI should exit with error code 1 when config file is not found
        # The error is reported to stderr before exiting
        assert result.returncode == 1

    def test_console_script_gateway_config_file_error(self):
        """Test that gatekit-gateway handles missing config file gracefully."""
        # Use the actual gateway executable
        gateway_exe = get_gatekit_gateway_exe()
        result = subprocess.run(
            [gateway_exe, "--config", "/nonexistent/config.yaml"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 1
        # Should show configuration error in gateway mode
        assert (
            "Configuration file not found" in result.stderr
            or "FileNotFoundError" in result.stderr
            or "No such file" in result.stderr
        )

    def test_console_script_is_available(self):
        """Test that both console scripts are properly installed and runnable.

        This test verifies:
        1. The executables exist in the expected Scripts/bin directory
        2. Both scripts can actually be invoked (via --version flag)

        Note: More detailed functionality tests are in test_console_script_help,
        test_gatekit_gateway_help, etc.
        """
        # Check that the executables exist in the scripts directory
        scripts_dir = get_scripts_dir()
        exe_suffix = ".exe" if sys.platform == "win32" else ""

        gatekit_exe = scripts_dir / f"gatekit{exe_suffix}"
        assert gatekit_exe.exists(), f"gatekit not found at {gatekit_exe}"

        gateway_exe = scripts_dir / f"gatekit-gateway{exe_suffix}"
        assert gateway_exe.exists(), f"gatekit-gateway not found at {gateway_exe}"

        # Verify scripts can actually be invoked (not just that files exist)
        # Use --version which should work and exit quickly
        result = subprocess.run(
            [str(gatekit_exe), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"gatekit --version failed: {result.stderr}"

        result = subprocess.run(
            [str(gateway_exe), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"gatekit-gateway --version failed: {result.stderr}"

    def test_gatekit_gateway_help(self):
        """Test that gatekit-gateway --help works."""
        gateway_exe = get_gatekit_gateway_exe()
        result = subprocess.run(
            [gateway_exe, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0
        assert "Gatekit Security Gateway for MCP" in result.stdout
        assert "--config" in result.stdout
        assert "--verbose" in result.stdout
        assert "--validate-only" in result.stdout

    def test_gatekit_gateway_requires_config(self):
        """Test that gatekit-gateway requires --config argument."""
        gateway_exe = get_gatekit_gateway_exe()
        result = subprocess.run(
            [gateway_exe],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Should exit with error code 2 (argparse error for missing required argument)
        assert result.returncode == 2
        assert "required" in result.stderr
