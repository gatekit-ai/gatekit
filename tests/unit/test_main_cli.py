"""Unit tests for CLI main entry point."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import pytest

from gatekit.main import tui_main, gateway_main, run_proxy, setup_logging


class TestTUICLIArgumentParsing:
    """Test TUI argument parsing functionality."""

    @patch("gatekit.tui.run_tui")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_default_config_path(self, mock_run_tui):
        """Test TUI with no config argument."""
        with patch("sys.argv", ["gatekit"]):
            tui_main()
            mock_run_tui.assert_called_once_with(
                None,
                tui_debug=False,
                config_error=None,
                initial_plugin_modal=None,
            )

    @patch("gatekit.tui.run_tui")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_open_plugin_argument(self, mock_run_tui):
        """Test that --open-plugin converts to PluginModalTarget."""
        from gatekit.tui.screens.config_editor.base import PluginModalTarget

        with patch(
            "sys.argv",
            ["gatekit", "--open-plugin", "middleware:tool_manager:server-alpha"],
        ):
            tui_main()

        mock_run_tui.assert_called_once()
        _, kwargs = mock_run_tui.call_args
        assert kwargs["initial_plugin_modal"] == PluginModalTarget(
            "middleware", "tool_manager", "server-alpha"
        )

    @patch("gatekit.tui.run_tui")
    @patch("gatekit.main._resolve_config_path")
    @patch("gatekit.main.ConfigLoader")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_custom_config_path(self, mock_loader, mock_resolve, mock_run_tui):
        """Test TUI with custom configuration file."""

        mock_resolve.return_value = Path("/custom/path/config.yaml")
        mock_loader.return_value.load_from_file.return_value = MagicMock()

        with patch("sys.argv", ["gatekit", "/custom/path/config.yaml"]):
            tui_main()
            mock_run_tui.assert_called_once_with(
                Path("/custom/path/config.yaml"),
                tui_debug=False,
                config_error=None,
                initial_plugin_modal=None,
            )

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_help_output(self):
        """Test TUI help text generation."""
        with patch("sys.argv", ["gatekit", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                tui_main()
            # argparse exits with code 0 for --help
            assert exc_info.value.code == 0


class TestGatewayCLIArgumentParsing:
    """Test gateway argument parsing functionality."""

    @patch("gatekit.main.run_gateway")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_basic_config(self, mock_run_gateway):
        """Test gateway with configuration file."""
        with patch("sys.argv", ["gatekit-gateway", "--config", "gatekit.yaml"]):
            gateway_main()
            mock_run_gateway.assert_called_once_with(Path("gatekit.yaml"), False)

    @patch("gatekit.main.run_gateway")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_custom_config_path(self, mock_run_gateway):
        """Test gateway with custom configuration file."""
        custom_path = Path("/custom/path/config.yaml")
        with patch("sys.argv", ["gatekit-gateway", "--config", str(custom_path)]):
            gateway_main()
            mock_run_gateway.assert_called_once_with(custom_path, False)

    @patch("gatekit.main.run_gateway")
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_verbose_flag(self, mock_run_gateway):
        """Test gateway verbose logging activation."""
        with patch(
            "sys.argv", ["gatekit-gateway", "--config", "gatekit.yaml", "--verbose"]
        ):
            gateway_main()
            mock_run_gateway.assert_called_once_with(Path("gatekit.yaml"), True)

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_requires_config(self):
        """Test that gateway requires config argument."""
        with patch("sys.argv", ["gatekit-gateway"]):
            with pytest.raises(SystemExit) as exc_info:
                with patch("sys.stderr"):
                    gateway_main()
            # argparse exits with code 2 for missing required arguments
            assert exc_info.value.code == 2

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_gateway_help_output(self):
        """Test gateway help text generation."""
        with patch("sys.argv", ["gatekit-gateway", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                gateway_main()
            # argparse exits with code 0 for --help
            assert exc_info.value.code == 0


class TestGatewayIntegration:
    """Test gateway integration with proxy components."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_config_file_not_found(self):
        """Test proper error handling for missing config files."""
        non_existent_path = Path("/non/existent/config.yaml")

        with patch("gatekit.main.setup_logging"):
            with patch("gatekit.main.ConfigLoader") as mock_loader_class:
                mock_loader = Mock()
                mock_loader.load_from_file.side_effect = FileNotFoundError(
                    "Config not found"
                )
                mock_loader_class.return_value = mock_loader

                # The startup error handler will call sys.exit
                with patch("gatekit.cli.startup_error_handler.sys.exit") as mock_exit:
                    # Mock the minimal server to prevent it from running
                    with patch(
                        "gatekit.cli.startup_error_handler.StartupErrorNotifier"
                    ):
                        await run_proxy(non_existent_path, verbose=False)
                        mock_exit.assert_called_with(1)

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_invalid_config_format(self):
        """Test error handling for malformed YAML configuration."""
        config_path = Path("test.yaml")

        with patch("gatekit.main.setup_logging"):
            with patch("gatekit.main.ConfigLoader") as mock_loader_class:
                mock_loader = Mock()
                mock_loader.load_from_file.side_effect = ValueError("Invalid YAML")
                mock_loader_class.return_value = mock_loader

                # The startup error handler will call sys.exit
                with patch("gatekit.cli.startup_error_handler.sys.exit") as mock_exit:
                    # Mock the minimal server to prevent it from running
                    with patch(
                        "gatekit.cli.startup_error_handler.StartupErrorNotifier"
                    ):
                        await run_proxy(config_path, verbose=False)
                        mock_exit.assert_called_with(1)

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_keyboard_interrupt_handling(self):
        """Test graceful shutdown on Ctrl+C (SIGINT)."""
        config_path = Path("test.yaml")

        with patch("gatekit.main.setup_logging_from_config"):
            with patch("gatekit.main.ConfigLoader") as mock_loader_class:
                mock_loader = Mock()
                mock_config = Mock()
                mock_loader.load_from_file.return_value = mock_config
                mock_loader_class.return_value = mock_loader

                with patch("gatekit.main.MCPProxy") as mock_proxy_class:
                    # Create a proper AsyncMock for the proxy context manager
                    mock_proxy = Mock()
                    mock_proxy.__aenter__ = AsyncMock(return_value=mock_proxy)
                    mock_proxy.__aexit__ = AsyncMock(return_value=None)
                    mock_proxy.run = AsyncMock(side_effect=KeyboardInterrupt())
                    mock_proxy_class.return_value = mock_proxy

                    # Should not raise exception or call sys.exit
                    await run_proxy(config_path, verbose=False)

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_async_proxy_integration(self):
        """Test CLI integration with asyncio-based proxy server."""
        config_path = Path("test.yaml")

        with patch("gatekit.main.setup_logging_from_config"):
            with patch("gatekit.main.ConfigLoader") as mock_loader_class:
                mock_loader = Mock()
                mock_config = Mock()
                mock_loader.load_from_file.return_value = mock_config
                mock_loader_class.return_value = mock_loader

                with patch("gatekit.main.MCPProxy") as mock_proxy_class:
                    # Create a proper AsyncMock for the proxy context manager
                    mock_proxy = Mock()
                    mock_proxy.__aenter__ = AsyncMock(return_value=mock_proxy)
                    mock_proxy.__aexit__ = AsyncMock(return_value=None)
                    mock_proxy.run = AsyncMock(return_value=None)
                    mock_proxy_class.return_value = mock_proxy

                    await run_proxy(config_path, verbose=False)

                    # Verify proxy was created with config and config_directory and run
                    mock_proxy_class.assert_called_once_with(
                        mock_config, mock_loader.config_directory
                    )
                    # Use assert_awaited_once for async mock
                    mock_proxy.run.assert_awaited_once()


class TestErrorHandling:
    """Test error handling and exit codes."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_unexpected_error_handling(self):
        """Test handling of unexpected errors with proper exit codes."""
        config_path = Path("test.yaml")

        with patch("gatekit.main.setup_logging"):
            with patch("gatekit.main.ConfigLoader") as mock_loader_class:
                mock_loader = Mock()
                mock_loader.load_from_file.side_effect = RuntimeError(
                    "Unexpected error"
                )
                mock_loader_class.return_value = mock_loader

                # The startup error handler will call sys.exit
                with patch("gatekit.cli.startup_error_handler.sys.exit") as mock_exit:
                    # Mock the minimal server to prevent it from running
                    with patch(
                        "gatekit.cli.startup_error_handler.StartupErrorNotifier"
                    ):
                        await run_proxy(config_path, verbose=False)
                        mock_exit.assert_called_with(1)

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_tui_import_error_handling(self):
        """Test TUI handles import errors gracefully."""
        import builtins

        original_import = builtins.__import__

        with patch("sys.argv", ["gatekit"]):
            with patch("sys.exit") as mock_exit:
                with patch("sys.stderr"):
                    # Mock the specific import to raise ImportError
                    def import_side_effect(name, *args, **kwargs):
                        if name == "gatekit.tui":
                            raise ImportError("Textual not found")
                        return original_import(name, *args, **kwargs)

                    with patch("builtins.__import__", side_effect=import_side_effect):
                        tui_main()
                mock_exit.assert_called_once_with(1)


class TestLoggingConfiguration:
    """Test logging setup and verbosity configuration."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_logging_configuration(self):
        """Test logging setup and verbosity level configuration."""
        # Test non-verbose logging
        with (
            patch("gatekit.main.logging.getLogger") as mock_get_logger,
            patch("gatekit.main.logging.StreamHandler") as mock_stream_handler,
        ):

            mock_root_logger = Mock()
            # Make handlers return an empty list that can be iterated
            mock_root_logger.handlers = []
            mock_asyncio_logger = Mock()

            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = Mock()
            mock_stream_handler.return_value = mock_handler

            setup_logging(verbose=False)

            # Verify root logger setup
            mock_root_logger.setLevel.assert_called_with(logging.INFO)
            # removeHandler should not have been called since handlers list was empty
            mock_root_logger.removeHandler.assert_not_called()
            mock_root_logger.addHandler.assert_called_with(mock_handler)

            # Verify asyncio logger setup
            mock_asyncio_logger.setLevel.assert_called_with(logging.WARNING)

        # Test verbose logging
        with (
            patch("gatekit.main.logging.getLogger") as mock_get_logger,
            patch("gatekit.main.logging.StreamHandler") as mock_stream_handler,
        ):

            mock_root_logger = Mock()
            # Make handlers return an empty list that can be iterated
            mock_root_logger.handlers = []
            mock_asyncio_logger = Mock()

            def mock_logger_side_effect(name=None):
                if name == "asyncio":
                    return mock_asyncio_logger
                else:  # name is None for root logger
                    return mock_root_logger

            mock_get_logger.side_effect = mock_logger_side_effect
            mock_handler = Mock()
            mock_stream_handler.return_value = mock_handler

            setup_logging(verbose=True)

            # Verify root logger setup with DEBUG level
            mock_root_logger.setLevel.assert_called_with(logging.DEBUG)
            # removeHandler should not have been called since handlers list was empty
            mock_root_logger.removeHandler.assert_not_called()
            mock_root_logger.addHandler.assert_called_with(mock_handler)


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
