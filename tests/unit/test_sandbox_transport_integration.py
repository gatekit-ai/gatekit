"""Tests for sandbox integration with StdioTransport and ServerManager."""

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from gatekit.config.models import SandboxConfig, UpstreamConfig
from gatekit.transport.stdio import StdioTransport
from gatekit.server_manager import ServerManager
from gatekit.sandbox.errors import SandboxUnavailableError


class TestStdioTransportSandboxInit:
    """Test StdioTransport accepts sandbox_config parameter."""

    def test_default_no_sandbox(self):
        transport = StdioTransport(command=["echo", "test"])
        assert transport._sandbox_config is None
        assert transport._sandbox_backend is None

    def test_sandbox_config_stored(self):
        cfg = SandboxConfig(enabled=True)
        transport = StdioTransport(command=["echo", "test"], sandbox_config=cfg)
        assert transport._sandbox_config is cfg


class TestStdioTransportSandboxConnect:
    """Test that connect() wraps commands when sandbox is enabled."""

    @pytest.fixture
    def mock_subprocess(self):
        """Mock asyncio.create_subprocess_exec to avoid actually starting a process."""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.returncode = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        mock_proc.stdout.readline = AsyncMock(return_value=b"")
        mock_proc.stderr.readline = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    @pytest.mark.asyncio
    async def test_connect_without_sandbox(self, mock_subprocess):
        transport = StdioTransport(command=["echo", "test"])

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_subprocess) as mock_exec:
            await transport.connect()

            # Should call with original command
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "echo"
            assert call_args[1] == "test"

        await transport.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_sandbox_wraps_command(self, mock_subprocess):
        cfg = SandboxConfig(enabled=True)
        transport = StdioTransport(command=["echo", "test"], sandbox_config=cfg)

        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["sandbox-wrapper", "echo", "test"]

        with patch("gatekit.sandbox.resolve_and_wrap", return_value=(["sandbox-wrapper", "echo", "test"], mock_backend)) as mock_wrap:
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_subprocess):
                await transport.connect()

                # resolve_and_wrap should have been called with new API
                mock_wrap.assert_called_once_with(
                    ["echo", "test"],
                    enabled=True,
                    paths=[],
                    network=True,
                )

                # Backend should be stored for cleanup
                assert transport._sandbox_backend is mock_backend

        await transport.disconnect()

    @pytest.mark.asyncio
    async def test_connect_passes_network_false(self, mock_subprocess):
        cfg = SandboxConfig(enabled=True, network=False, paths=["~/data"])
        transport = StdioTransport(command=["echo", "test"], sandbox_config=cfg)

        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["sandbox-wrapper", "echo", "test"]

        with patch("gatekit.sandbox.resolve_and_wrap", return_value=(["sandbox-wrapper", "echo", "test"], mock_backend)) as mock_wrap:
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_subprocess):
                await transport.connect()

                mock_wrap.assert_called_once_with(
                    ["echo", "test"],
                    enabled=True,
                    paths=["~/data"],
                    network=False,
                )

        await transport.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_sandbox(self, mock_subprocess):
        cfg = SandboxConfig(enabled=True)
        transport = StdioTransport(command=["echo", "test"], sandbox_config=cfg)

        mock_backend = MagicMock()
        mock_backend.name = "test-backend"

        with patch("gatekit.sandbox.resolve_and_wrap", return_value=(["wrapper", "echo", "test"], mock_backend)):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_subprocess):
                await transport.connect()

        await transport.disconnect()

        mock_backend.cleanup.assert_called_once()
        assert transport._sandbox_backend is None

    @pytest.mark.asyncio
    async def test_connect_fails_when_sandbox_unavailable(self):
        cfg = SandboxConfig(enabled=True)
        transport = StdioTransport(command=["echo", "test"], sandbox_config=cfg)

        with patch("gatekit.sandbox.resolve_and_wrap", side_effect=SandboxUnavailableError("not available")):
            from gatekit.transport.errors import TransportProcessError
            with pytest.raises(TransportProcessError, match="not available"):
                await transport.connect()


class TestStdioTransportSandboxCleanup:
    """Test sandbox cleanup on error paths."""

    @pytest.mark.asyncio
    async def test_sandbox_cleanup_on_spawn_oserror(self):
        """Sandbox backend should be cleaned up if create_subprocess_exec raises OSError."""
        cfg = SandboxConfig(enabled=True)
        transport = StdioTransport(command=["echo", "test"], sandbox_config=cfg)

        mock_backend = MagicMock()
        mock_backend.name = "test-backend"
        mock_backend.wrap_command.return_value = ["wrapper", "echo", "test"]

        with patch("gatekit.sandbox.resolve_and_wrap", return_value=(["wrapper", "echo", "test"], mock_backend)):
            with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=OSError("spawn failed")):
                from gatekit.transport.errors import TransportProcessError
                with pytest.raises(TransportProcessError, match="spawn failed"):
                    await transport.connect()

        # Backend cleanup should have been called despite the error
        mock_backend.cleanup.assert_called_once()
        assert transport._sandbox_backend is None


class TestServerManagerSandboxPassthrough:
    """Test ServerManager passes sandbox config to StdioTransport."""

    def test_create_transport_passes_sandbox(self):
        cfg = UpstreamConfig(
            name="test",
            command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True, network=False),
        )
        manager = ServerManager(configs=[cfg])

        transport = manager._create_transport(cfg)

        assert isinstance(transport, StdioTransport)
        assert transport._sandbox_config is not None
        assert transport._sandbox_config.enabled is True
        assert transport._sandbox_config.network is False

    def test_create_transport_no_sandbox(self):
        cfg = UpstreamConfig(name="test", command=["echo", "test"])
        manager = ServerManager(configs=[cfg])

        transport = manager._create_transport(cfg)

        assert isinstance(transport, StdioTransport)
        assert transport._sandbox_config is None


class TestServerManagerSandboxReconnect:
    """Test _needs_reconnect detects sandbox config changes."""

    def test_no_sandbox_change(self):
        old = UpstreamConfig(name="test", command=["echo", "test"])
        new = UpstreamConfig(name="test", command=["echo", "test"])
        manager = ServerManager(configs=[old])
        assert manager._needs_reconnect(old, new) is False

    def test_sandbox_enabled(self):
        old = UpstreamConfig(name="test", command=["echo", "test"])
        new = UpstreamConfig(
            name="test",
            command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True),
        )
        manager = ServerManager(configs=[old])
        assert manager._needs_reconnect(old, new) is True

    def test_sandbox_disabled(self):
        old = UpstreamConfig(
            name="test",
            command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True),
        )
        new = UpstreamConfig(name="test", command=["echo", "test"])
        manager = ServerManager(configs=[old])
        assert manager._needs_reconnect(old, new) is True

    def test_sandbox_config_changed(self):
        old = UpstreamConfig(
            name="test",
            command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True, network=True),
        )
        new = UpstreamConfig(
            name="test",
            command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True, network=False),
        )
        manager = ServerManager(configs=[old])
        assert manager._needs_reconnect(old, new) is True

    def test_sandbox_same_config_no_reconnect(self):
        old = UpstreamConfig(
            name="test", command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True, paths=["~/docs"]),
        )
        new = UpstreamConfig(
            name="test", command=["echo", "test"],
            sandbox=SandboxConfig(enabled=True, paths=["~/docs"]),
        )
        manager = ServerManager(configs=[old])
        assert manager._needs_reconnect(old, new) is False
