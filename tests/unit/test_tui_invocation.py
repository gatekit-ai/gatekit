"""Tests for TUI invocation and command-line argument parsing."""

import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import pytest

from gatekit.main import tui_main, gateway_main


class TestTUICommandLineParsing:
    """Test TUI command-line argument parsing."""

    def test_tui_help(self):
        """Test that gatekit --help works."""
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["gatekit", "--help"]):
                with patch("sys.stdout"):
                    tui_main()

    @patch("gatekit.tui.run_tui")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_default_behavior(self, mock_run_tui):
        """Test that TUI launches with no arguments."""
        with patch("sys.argv", ["gatekit"]):
            tui_main()

        mock_run_tui.assert_called_once_with(
            None,
            tui_debug=False,
            config_error=None,
            initial_plugin_modal=None,
        )

    @patch("gatekit.tui.run_tui")
    @patch("gatekit.main._resolve_config_path")
    @patch("gatekit.main.ConfigLoader")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_with_config(self, mock_loader, mock_resolve, mock_run_tui):
        """Test that TUI launches with config file."""
        # Mock successful config resolution and loading
        mock_resolve.return_value = Path("test.yaml")
        mock_loader.return_value.load_from_file.return_value = MagicMock()

        with patch("sys.argv", ["gatekit", "test.yaml"]):
            tui_main()

        mock_run_tui.assert_called_once_with(
            Path("test.yaml"),
            tui_debug=False,
            config_error=None,
            initial_plugin_modal=None,
        )


class TestGatewayCommandLineParsing:
    """Test gateway command-line argument parsing."""

    def test_gateway_help(self):
        """Test that gatekit-gateway --help works."""
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["gatekit-gateway", "--help"]):
                with patch("sys.stdout"):
                    gateway_main()

    def test_gateway_requires_config(self):
        """Test that gateway requires --config argument."""
        with pytest.raises(SystemExit) as exc_info:
            with patch("sys.argv", ["gatekit-gateway"]):
                with patch("sys.stderr"):
                    gateway_main()

        # argparse exits with code 2 for missing required arguments
        assert exc_info.value.code == 2

    @patch("gatekit.main.run_gateway")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_with_config(self, mock_run_gateway):
        """Test that gateway runs with config."""
        with patch("sys.argv", ["gatekit-gateway", "--config", "test.yaml"]):
            gateway_main()

        mock_run_gateway.assert_called_once_with(Path("test.yaml"), False)

    @patch("gatekit.main.run_gateway")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_with_verbose(self, mock_run_gateway):
        """Test that gateway runs with verbose flag."""
        with patch(
            "sys.argv", ["gatekit-gateway", "--config", "test.yaml", "--verbose"]
        ):
            gateway_main()

        mock_run_gateway.assert_called_once_with(Path("test.yaml"), True)


class TestTUIHandling:
    """Test TUI mode handling and fallbacks."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_textual_import_error_handling(self):
        """Test graceful handling when Textual is not installed."""
        import builtins

        original_import = builtins.__import__

        # Mock ImportError when trying to import TUI
        with patch("sys.argv", ["gatekit"]):
            with patch("sys.exit") as mock_exit:
                with patch("sys.stderr"):  # Suppress error output
                    # Mock the specific import to raise ImportError
                    def import_side_effect(name, *args, **kwargs):
                        if name == "gatekit.tui":
                            raise ImportError("Textual not found")
                        return original_import(name, *args, **kwargs)

                    with patch("builtins.__import__", side_effect=import_side_effect):
                        tui_main()

        mock_exit.assert_called_once_with(1)

    @patch("gatekit.tui.run_tui")
    @patch("gatekit.main._resolve_config_path")
    @patch("gatekit.main.ConfigLoader")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_successful_tui_launch(self, mock_loader, mock_resolve, mock_run_tui):
        """Test successful TUI launch."""
        # Mock successful config resolution and loading
        mock_resolve.return_value = Path("config.yaml")
        mock_loader.return_value.load_from_file.return_value = MagicMock()

        with patch("sys.argv", ["gatekit", "config.yaml"]):
            tui_main()

        mock_run_tui.assert_called_once_with(
            Path("config.yaml"),
            tui_debug=False,
            config_error=None,
            initial_plugin_modal=None,
        )


class TestGatewayValidation:
    """Test gateway validation functionality."""

    @patch("gatekit.config.loader.ConfigLoader")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_validate_only_success(self, mock_loader_class):
        """Test successful config validation."""
        mock_loader = Mock()
        mock_config = Mock()
        mock_loader.load_from_file.return_value = mock_config
        mock_loader_class.return_value = mock_loader

        with patch(
            "sys.argv",
            ["gatekit-gateway", "--config", "test.yaml", "--validate-only"],
        ):
            with patch("sys.exit") as mock_exit:
                with patch("sys.stdout"):
                    gateway_main()

        mock_exit.assert_called_once_with(0)

    @patch("gatekit.config.loader.ConfigLoader")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_validate_only_failure(self, mock_loader_class):
        """Test failed config validation."""
        mock_loader = Mock()
        mock_loader.load_from_file.side_effect = ValueError("Invalid config")
        mock_loader_class.return_value = mock_loader

        with patch(
            "sys.argv",
            ["gatekit-gateway", "--config", "test.yaml", "--validate-only"],
        ):
            with patch("sys.exit") as mock_exit:
                with patch("sys.stderr"):
                    gateway_main()

        mock_exit.assert_called_once_with(1)


class TestCommandLineInterface:
    """Test the actual command-line interface behavior."""

    @pytest.mark.skipif(
        shutil.which("gatekit") is None,
        reason="gatekit not installed in PATH",
    )
    def test_tui_help_output(self):
        """Test that installed gatekit TUI shows correct help."""
        # Use explicit .exe on Windows for subprocess
        cmd = "gatekit.exe" if sys.platform == "win32" else "gatekit"
        result = subprocess.run([cmd, "--help"], capture_output=True, text=True)

        # Help should show TUI description
        assert "Gatekit Security Gateway Configuration Interface" in result.stdout
        assert "CONFIG_FILE" in result.stdout
        assert "--verbose" in result.stdout

    @pytest.mark.skipif(
        shutil.which("gatekit-gateway") is None,
        reason="gatekit-gateway not installed in PATH",
    )
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_without_config_shows_error(self):
        """Test that gateway without config shows helpful error."""
        # Use explicit .exe on Windows for subprocess
        cmd = "gatekit-gateway.exe" if sys.platform == "win32" else "gatekit-gateway"
        result = subprocess.run([cmd], capture_output=True, text=True)

        # Should exit with error code and show config requirement
        assert result.returncode != 0
        assert "required" in result.stderr
