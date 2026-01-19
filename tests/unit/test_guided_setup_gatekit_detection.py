"""Tests for Gatekit detection in guided setup."""

from pathlib import Path
from unittest.mock import patch

from gatekit.tui.guided_setup.detection import (
    extract_gatekit_config_path,
    detect_gatekit_in_client,
)
from gatekit.tui.guided_setup.models import (
    ClientType,
    DetectedClient,
    DetectedServer,
    TransportType,
)


def normalize_path(path: str) -> str:
    """Normalize path to use forward slashes for cross-platform comparison."""
    return path.replace("\\", "/")


class TestExtractGatekitConfigPath:
    """Test extraction of gatekit config path from server args."""

    def test_extract_from_config_flag_with_space(self):
        """Extract config path from --config FLAG."""
        args = ["--config", "/path/to/gatekit.yaml", "--verbose"]
        result = extract_gatekit_config_path(args)
        assert result == "/path/to/gatekit.yaml"

    def test_extract_from_config_flag_with_equals(self):
        """Extract config path from --config=PATH."""
        args = ["--config=/path/to/gatekit.yaml", "--verbose"]
        result = extract_gatekit_config_path(args)
        assert result == "/path/to/gatekit.yaml"

    @patch("gatekit.tui.guided_setup.detection.platform.system")
    @patch("gatekit.tui.guided_setup.detection.get_home_dir")
    def test_extract_returns_default_macos(self, mock_home, mock_system):
        """Return default macOS path when no --config arg."""
        mock_system.return_value = "Darwin"
        mock_home.return_value = Path("/Users/test")

        args = ["--verbose"]
        result = extract_gatekit_config_path(args)
        assert normalize_path(result) == "/Users/test/.config/gatekit/gatekit.yaml"

    @patch("gatekit.tui.guided_setup.detection.platform.system")
    @patch("gatekit.tui.guided_setup.detection.get_home_dir")
    def test_extract_returns_default_linux(self, mock_home, mock_system):
        """Return default Linux path when no --config arg."""
        mock_system.return_value = "Linux"
        mock_home.return_value = Path("/home/test")

        args = []
        result = extract_gatekit_config_path(args)
        assert normalize_path(result) == "/home/test/.config/gatekit/gatekit.yaml"

    @patch("gatekit.tui.guided_setup.detection.platform.system")
    @patch("gatekit.tui.guided_setup.detection.get_platform_appdata")
    def test_extract_returns_default_windows(self, mock_appdata, mock_system):
        """Return default Windows path when no --config arg."""
        mock_system.return_value = "Windows"
        mock_appdata.return_value = Path("C:/Users/test/AppData/Roaming")

        args = []
        result = extract_gatekit_config_path(args)
        assert normalize_path(result) == "C:/Users/test/AppData/Roaming/gatekit/gatekit.yaml"


class TestDetectGatekitInClient:
    """Test detection of Gatekit in client configs."""

    def test_detect_gatekit_gateway_command(self):
        """Detect Gatekit when command is gatekit-gateway."""
        server = DetectedServer(
            name="gatekit",
            transport=TransportType.STDIO,
            command=["gatekit-gateway", "--config", "/test/gatekit.yaml"],
            raw_config={"command": "gatekit-gateway", "args": ["--config", "/test/gatekit.yaml"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result == "/test/gatekit.yaml"

    def test_detect_gatekit_ending_with_gatekit(self):
        """Detect Gatekit when command ends with 'gatekit'."""
        server = DetectedServer(
            name="my-gatekit",
            transport=TransportType.STDIO,
            command=["/usr/local/bin/gatekit", "--config=/custom/path.yaml"],
            raw_config={"command": "/usr/local/bin/gatekit", "args": ["--config=/custom/path.yaml"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result == "/custom/path.yaml"

    def test_detect_returns_none_when_no_gatekit(self):
        """Return None when client has no Gatekit servers."""
        server = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-filesystem"],
            raw_config={"command": "npx", "args": ["@modelcontextprotocol/server-filesystem"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result is None

    def test_detect_returns_none_when_gatekit_is_directory_argument(self):
        """Don't falsely detect when 'gatekit' is just a directory path argument.

        Regression test for false positive when filesystem server points to
        a directory named 'gatekit'.
        """
        server = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects/gatekit"],
            raw_config={
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects/gatekit"],
            },
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result is None

    def test_detect_ignores_http_servers(self):
        """Ignore HTTP servers (no command) when detecting Gatekit."""
        server = DetectedServer(
            name="http-server",
            transport=TransportType.HTTP,
            url="http://localhost:8080",
            raw_config={"url": "http://localhost:8080"},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result is None

    def test_detect_finds_gatekit_among_multiple_servers(self):
        """Find Gatekit server among multiple servers."""
        server1 = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-filesystem"],
            raw_config={"command": "npx", "args": ["@modelcontextprotocol/server-filesystem"]},
        )
        server2 = DetectedServer(
            name="gatekit",
            transport=TransportType.STDIO,
            command=["gatekit-gateway", "--config", "/my/config.yaml"],
            raw_config={"command": "gatekit-gateway", "args": ["--config", "/my/config.yaml"]},
        )
        server3 = DetectedServer(
            name="brave-search",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-brave-search"],
            raw_config={"command": "npx", "args": ["@modelcontextprotocol/server-brave-search"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/test/.claude.json"),
            servers=[server1, server2, server3],
        )

        result = detect_gatekit_in_client(client)
        assert result == "/my/config.yaml"

    def test_detect_gatekit_via_uv_run_wrapper(self):
        """Detect Gatekit when launched via 'uv run gatekit-gateway'."""
        server = DetectedServer(
            name="gatekit",
            transport=TransportType.STDIO,
            command=["uv", "run", "gatekit-gateway", "--config", "/test/gatekit.yaml"],
            raw_config={"command": "uv", "args": ["run", "gatekit-gateway", "--config", "/test/gatekit.yaml"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result == "/test/gatekit.yaml"

    def test_detect_gatekit_via_python_module(self):
        """Detect Gatekit when launched via 'python -m gatekit.main'."""
        server = DetectedServer(
            name="gatekit",
            transport=TransportType.STDIO,
            command=["python", "-m", "gatekit.main", "--config=/custom/path.yaml"],
            raw_config={"command": "python", "args": ["-m", "gatekit.main", "--config=/custom/path.yaml"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        assert result == "/custom/path.yaml"

    def test_detect_gatekit_via_uv_run_without_config_arg(self):
        """Detect Gatekit via uv run without --config (returns default)."""
        server = DetectedServer(
            name="gatekit",
            transport=TransportType.STDIO,
            command=["uv", "run", "gatekit-gateway", "--verbose"],
            raw_config={"command": "uv", "args": ["run", "gatekit-gateway", "--verbose"]},
        )

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[server],
        )

        result = detect_gatekit_in_client(client)
        # Should return default path (platform-specific, just check it's not None)
        assert result is not None
        assert "gatekit.yaml" in result


class TestDetectedClientHasGatekit:
    """Test DetectedClient.has_gatekit() method."""

    def test_has_gatekit_returns_true_when_config_path_set(self):
        """has_gatekit() returns True when gatekit_config_path is set."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            gatekit_config_path="/test/gatekit.yaml",
        )

        assert client.has_gatekit() is True

    def test_has_gatekit_returns_false_when_config_path_none(self):
        """has_gatekit() returns False when gatekit_config_path is None."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            gatekit_config_path=None,
        )

        assert client.has_gatekit() is False

    def test_has_gatekit_defaults_to_false(self):
        """has_gatekit() defaults to False when not set."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
        )

        assert client.has_gatekit() is False
