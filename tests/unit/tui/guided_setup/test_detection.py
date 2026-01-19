"""Unit tests for MCP client detection logic."""

import json
import platform
import pytest
from unittest.mock import patch

from gatekit.tui.guided_setup.detection import (
    detect_claude_desktop,
    detect_claude_code,
    detect_codex,
    detect_all_clients,
)
from gatekit.tui.guided_setup.models import ClientType, ServerScope


class TestClaudeDesktopDetection:
    """Test suite for Claude Desktop detection."""

    @pytest.mark.posix_only
    def test_detect_claude_desktop_macos(self, tmp_path):
        """Detect Claude Desktop on macOS."""
        if platform.system() != "Darwin":
            pytest.skip("macOS-specific test")

        # Create fake config structure
        config_dir = tmp_path / "Library" / "Application Support" / "Claude"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "claude_desktop_config.json"

        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
            }
        }
        config_file.write_text(json.dumps(config))

        # Mock Path.home() to return our tmp_path
        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            client = detect_claude_desktop()

        assert client is not None
        assert client.client_type == ClientType.CLAUDE_DESKTOP
        assert client.has_servers()
        assert len(client.servers) == 1
        assert client.servers[0].name == "filesystem"

    @pytest.mark.platform_specific(["Linux"])
    def test_detect_claude_desktop_linux(self, tmp_path):
        """Detect Claude Desktop on Linux."""
        # Create fake config structure
        config_dir = tmp_path / ".config" / "Claude"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "claude_desktop_config.json"

        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
            }
        }
        config_file.write_text(json.dumps(config))

        # Mock Path.home() to return our tmp_path
        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            client = detect_claude_desktop()

        assert client is not None
        assert client.client_type == ClientType.CLAUDE_DESKTOP
        assert client.has_servers()

    @pytest.mark.platform_specific(["Windows"])
    def test_detect_claude_desktop_windows(self, tmp_path):
        """Detect Claude Desktop on Windows."""
        # Create fake config structure
        appdata = tmp_path / "AppData" / "Roaming"
        config_dir = appdata / "Claude"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "claude_desktop_config.json"

        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\tmp"]}
            }
        }
        config_file.write_text(json.dumps(config))

        # Mock get_platform_appdata to return our tmp AppData
        with patch("gatekit.tui.guided_setup.detection.get_platform_appdata", return_value=appdata):
            client = detect_claude_desktop()

        assert client is not None
        assert client.client_type == ClientType.CLAUDE_DESKTOP
        assert client.has_servers()

    def test_detect_claude_desktop_not_found(self, isolated_home):
        """Return None when Claude Desktop config doesn't exist."""
        # Don't create any config file
        # isolated_home fixture handles HOME, APPDATA, and get_home_dir
        client = detect_claude_desktop()

        assert client is None

    def test_detect_claude_desktop_empty_servers(self, tmp_path):
        """Detect Claude Desktop with empty mcpServers section."""
        # Create platform-appropriate path
        if platform.system() == "Darwin":
            config_dir = tmp_path / "Library" / "Application Support" / "Claude"
        elif platform.system() == "Linux":
            config_dir = tmp_path / ".config" / "Claude"
        elif platform.system() == "Windows":
            appdata = tmp_path / "AppData" / "Roaming"
            config_dir = appdata / "Claude"
        else:
            pytest.skip("Unknown platform")

        config_dir.mkdir(parents=True)
        config_file = config_dir / "claude_desktop_config.json"

        config = {"mcpServers": {}}
        config_file.write_text(json.dumps(config))

        if platform.system() == "Windows":
            with patch("gatekit.tui.guided_setup.detection.get_platform_appdata", return_value=appdata):
                client = detect_claude_desktop()
        else:
            with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
                client = detect_claude_desktop()

        assert client is not None
        assert not client.has_servers()
        assert len(client.servers) == 0


class TestClaudeCodeDetection:
    """Test suite for Claude Code detection."""

    def test_detect_claude_code_user_level(self, tmp_path):
        """Detect Claude Code with user-level config."""
        # Create user-level config
        config_file = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert client.client_type == ClientType.CLAUDE_CODE
        assert client.has_servers()
        assert len(client.servers) == 1

        # Check scope is set correctly
        assert client.servers[0].scope == ServerScope.USER

    def test_detect_claude_code_project_level(self, tmp_path):
        """Detect Claude Code with project-level config."""
        # Create project-level config
        config_file = tmp_path / ".mcp.json"
        config = {
            "mcpServers": {
                "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}
            }
        }
        config_file.write_text(json.dumps(config))

        # Mock cwd to be our tmp_path (where .mcp.json is)
        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path / "home"):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert client.client_type == ClientType.CLAUDE_CODE
        assert client.has_servers()

        # Check scope is set correctly
        assert client.servers[0].scope == ServerScope.PROJECT

    def test_detect_claude_code_both_configs(self, tmp_path):
        """Detect Claude Code with both user and project configs."""
        # Create user-level config
        user_config = tmp_path / ".claude.json"
        user_data = {"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}}}
        user_config.write_text(json.dumps(user_data))

        # Create project-level config
        project_config = tmp_path / ".mcp.json"
        project_data = {"mcpServers": {"github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}}}
        project_config.write_text(json.dumps(project_data))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert client.has_servers()
        # Should have servers from both configs
        assert len(client.servers) == 2

        # Check scopes are correctly assigned
        server_scopes = {s.name: s.scope for s in client.servers}
        assert server_scopes["filesystem"] == ServerScope.USER
        assert server_scopes["github"] == ServerScope.PROJECT

    def test_detect_claude_code_not_found(self, tmp_path):
        """Return None when Claude Code configs don't exist."""
        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is None

    def test_detect_claude_code_root_level_servers(self, tmp_path):
        """Root-level mcpServers still detected (backward compatibility)."""
        config_file = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]}
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 1
        assert client.servers[0].name == "filesystem"
        assert client.servers[0].scope == ServerScope.USER
        assert client.servers[0].project_path is None

    def test_detect_claude_code_project_servers(self, tmp_path):
        """Project servers in 'projects' section are detected."""
        config_file = tmp_path / ".claude.json"
        config = {
            "projects": {
                "/Users/test/project1": {
                    "mcpServers": {
                        "context7": {"command": "npx", "args": ["-y", "@upstash/context7-mcp"]}
                    }
                }
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 1
        assert client.servers[0].name == "context7"
        # Project-specific servers in ~/.claude.json use LOCAL scope (private, per-project)
        assert client.servers[0].scope == ServerScope.LOCAL
        assert client.servers[0].project_path == "/Users/test/project1"

    def test_detect_claude_code_multiple_projects(self, tmp_path):
        """Servers from multiple projects all detected."""
        config_file = tmp_path / ".claude.json"
        config = {
            "projects": {
                "/Users/test/project1": {
                    "mcpServers": {
                        "server1": {"command": "npx", "args": ["-y", "server1"]}
                    }
                },
                "/Users/test/project2": {
                    "mcpServers": {
                        "server2": {"command": "npx", "args": ["-y", "server2"]}
                    }
                }
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 2

        # Verify each server has correct project_path and scope
        servers_by_name = {s.name: s for s in client.servers}

        assert servers_by_name["server1"].project_path == "/Users/test/project1"
        # Project-specific servers in ~/.claude.json use LOCAL scope (private, per-project)
        assert servers_by_name["server1"].scope == ServerScope.LOCAL

        assert servers_by_name["server2"].project_path == "/Users/test/project2"
        # Project-specific servers in ~/.claude.json use LOCAL scope (private, per-project)
        assert servers_by_name["server2"].scope == ServerScope.LOCAL

    def test_detect_claude_code_mixed_root_and_project_servers(self, tmp_path):
        """Both root-level and project servers detected together."""
        config_file = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "global-server": {"command": "npx", "args": ["-y", "global-server"]}
            },
            "projects": {
                "/Users/test/project": {
                    "mcpServers": {
                        "project-server": {"command": "npx", "args": ["-y", "project-server"]}
                    }
                }
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 2

        servers_by_name = {s.name: s for s in client.servers}

        # Global server should have USER scope and no project_path
        assert servers_by_name["global-server"].scope == ServerScope.USER
        assert servers_by_name["global-server"].project_path is None

        # Project-specific server in ~/.claude.json uses LOCAL scope (private, per-project)
        assert servers_by_name["project-server"].scope == ServerScope.LOCAL
        assert servers_by_name["project-server"].project_path == "/Users/test/project"

    def test_detect_claude_code_empty_projects(self, tmp_path):
        """Empty projects section doesn't cause errors."""
        config_file = tmp_path / ".claude.json"
        config = {"projects": {}}
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 0
        assert len(client.parse_errors) == 0

    def test_detect_claude_code_malformed_project_data(self, tmp_path):
        """Malformed project data skipped, valid projects still processed."""
        config_file = tmp_path / ".claude.json"
        config = {
            "projects": {
                "/Users/test/bad": "not a dict",
                "/Users/test/good": {
                    "mcpServers": {
                        "server": {"command": "npx", "args": ["-y", "server"]}
                    }
                }
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        # Should get 1 server from good project, bad project skipped silently
        assert len(client.servers) == 1
        assert client.servers[0].name == "server"
        assert client.servers[0].project_path == "/Users/test/good"

    def test_detect_claude_code_project_with_no_mcpservers(self, tmp_path):
        """Project without mcpServers section is skipped."""
        config_file = tmp_path / ".claude.json"
        config = {
            "projects": {
                "/Users/test/project1": {
                    "mcpServers": {
                        "server1": {"command": "npx", "args": ["-y", "server1"]}
                    }
                },
                "/Users/test/project2": {
                    "someOtherKey": "value"
                }
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 1
        assert client.servers[0].name == "server1"

    def test_detect_claude_code_project_with_invalid_server(self, tmp_path):
        """Invalid server in project captured in parse_errors."""
        config_file = tmp_path / ".claude.json"
        config = {
            "projects": {
                "/Users/test/project": {
                    "mcpServers": {
                        "bad-server": {"invalid": "config"},
                        "good-server": {"command": "npx", "args": ["-y", "good"]}
                    }
                }
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        # Should get 1 good server
        assert len(client.servers) == 1
        assert client.servers[0].name == "good-server"

        # Should have error for bad server
        assert len(client.parse_errors) == 1
        assert "bad-server" in client.parse_errors[0]
        assert "/Users/test/project" in client.parse_errors[0]

    def test_detect_claude_code_projects_not_dict(self, tmp_path):
        """Non-dict projects value is handled gracefully."""
        config_file = tmp_path / ".claude.json"
        config = {
            "projects": "not a dict"
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 0
        # Should not crash, just skip invalid projects section


class TestCodexDetection:
    """Test suite for Codex detection."""

    def test_detect_codex_default_location(self, tmp_path):
        """Detect Codex at default ~/.codex/config.toml location."""
        # Create config
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"

        toml_content = """
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
"""
        config_file.write_text(toml_content)

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch.dict("os.environ", {}, clear=True):  # No CODEX_HOME
                client = detect_codex()

        assert client is not None
        assert client.client_type == ClientType.CODEX
        assert client.has_servers()
        assert len(client.servers) == 1
        assert client.servers[0].name == "filesystem"

    def test_detect_codex_with_codex_home_env(self, tmp_path):
        """Detect Codex using CODEX_HOME environment variable."""
        # Create config in custom location
        custom_dir = tmp_path / "custom_codex"
        custom_dir.mkdir()
        config_file = custom_dir / "config.toml"

        toml_content = """
[mcp_servers.sqlite]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-sqlite"]
"""
        config_file.write_text(toml_content)

        with patch.dict("os.environ", {"CODEX_HOME": str(custom_dir)}):
            client = detect_codex()

        assert client is not None
        assert client.client_type == ClientType.CODEX
        assert client.has_servers()
        assert client.servers[0].name == "sqlite"

    def test_detect_codex_not_found(self, tmp_path):
        """Return None when Codex config doesn't exist."""
        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch.dict("os.environ", {}, clear=True):
                client = detect_codex()

        assert client is None

    def test_detect_codex_empty_servers(self, tmp_path):
        """Detect Codex with empty mcp_servers section."""
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"

        toml_content = """
experimental_use_rmcp_client = true

[mcp_servers]
"""
        config_file.write_text(toml_content)

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch.dict("os.environ", {}, clear=True):
                client = detect_codex()

        assert client is not None
        assert not client.has_servers()


class TestDetectAllClients:
    """Test suite for detecting all clients at once."""

    @pytest.mark.posix_only
    def test_detect_all_finds_multiple(self, tmp_path):
        """Detect multiple clients when they all exist."""
        # Setup Claude Desktop
        if platform.system() == "Darwin":
            cd_dir = tmp_path / "Library" / "Application Support" / "Claude"
        else:
            # Linux
            cd_dir = tmp_path / ".config" / "Claude"

        cd_dir.mkdir(parents=True)
        (cd_dir / "claude_desktop_config.json").write_text(
            json.dumps({"mcpServers": {"fs1": {"command": "npx", "args": ["-y", "filesystem"]}}})
        )

        # Setup Claude Code
        (tmp_path / ".claude.json").write_text(
            json.dumps({"mcpServers": {"fs2": {"command": "npx", "args": ["-y", "filesystem"]}}})
        )

        # Setup Codex
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "config.toml").write_text('[mcp_servers.fs3]\ncommand = "npx"\nargs = ["-y", "filesystem"]')

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                with patch.dict("os.environ", {}, clear=True):
                    clients = detect_all_clients()

        # Should find all 3 clients
        assert len(clients) == 3

        client_types = {c.client_type for c in clients}
        assert ClientType.CLAUDE_DESKTOP in client_types
        assert ClientType.CLAUDE_CODE in client_types
        assert ClientType.CODEX in client_types

    def test_detect_all_finds_none(self, tmp_path):
        """Return empty list when no clients exist."""
        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                with patch.dict("os.environ", {}, clear=True):
                    clients = detect_all_clients()

        assert len(clients) == 0

    def test_detect_all_partial_detection(self, tmp_path):
        """Detect only the clients that exist."""
        # Only setup Claude Code
        (tmp_path / ".claude.json").write_text(
            json.dumps({"mcpServers": {"github": {"command": "npx", "args": ["-y", "github"]}}})
        )

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                with patch.dict("os.environ", {}, clear=True):
                    clients = detect_all_clients()

        assert len(clients) == 1
        assert clients[0].client_type == ClientType.CLAUDE_CODE


class TestHTTPServerFiltering:
    """Test suite for HTTP/SSE server filtering (stdio-only support)."""

    def test_filter_stdio_servers_only(self, tmp_path):
        """Filter to include only stdio servers, excluding HTTP."""
        config_file = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
                "linear": {"url": "https://mcp.linear.app/mcp"},
                "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 3  # All servers detected

        # Filter to stdio only
        stdio_servers = client.get_stdio_servers()
        assert len(stdio_servers) == 2
        assert {s.name for s in stdio_servers} == {"filesystem", "github"}

        # Get HTTP servers for reporting
        http_servers = client.get_http_servers()
        assert len(http_servers) == 1
        assert http_servers[0].name == "linear"

    def test_all_http_servers_skipped(self, tmp_path):
        """All HTTP servers should be filtered out when only HTTP configs exist."""
        config_file = tmp_path / ".claude.json"
        config = {
            "mcpServers": {
                "linear": {"url": "https://mcp.linear.app/mcp"},
                "figma": {"url": "https://mcp.figma.com/mcp"},
            }
        }
        config_file.write_text(json.dumps(config))

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                client = detect_claude_code()

        assert client is not None
        assert len(client.servers) == 2  # Both detected

        # No stdio servers
        stdio_servers = client.get_stdio_servers()
        assert len(stdio_servers) == 0

        # All are HTTP
        http_servers = client.get_http_servers()
        assert len(http_servers) == 2
        assert {s.name for s in http_servers} == {"linear", "figma"}

    def test_codex_http_server_with_bearer_token(self, tmp_path):
        """Codex HTTP servers with bearer_token_env_var should be filtered."""
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        config_file = config_dir / "config.toml"

        toml_content = """
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[mcp_servers.figma]
url = "https://mcp.figma.com/mcp"
bearer_token_env_var = "FIGMA_TOKEN"
"""
        config_file.write_text(toml_content)

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch.dict("os.environ", {}, clear=True):
                client = detect_codex()

        assert client is not None
        assert len(client.servers) == 2

        # Only filesystem should be stdio
        stdio_servers = client.get_stdio_servers()
        assert len(stdio_servers) == 1
        assert stdio_servers[0].name == "filesystem"

        # Figma should be HTTP
        http_servers = client.get_http_servers()
        assert len(http_servers) == 1
        assert http_servers[0].name == "figma"
