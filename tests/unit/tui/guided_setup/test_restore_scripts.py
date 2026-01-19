"""Unit tests for restore script generation."""

from pathlib import Path
from unittest.mock import patch

from gatekit.tui.guided_setup.restore_scripts import (
    generate_restore_scripts,
    _generate_claude_desktop_restore,
    _generate_claude_code_restore,
    _generate_codex_restore,
    _build_mcp_servers_json,
    _get_scope_flag,
    _quote_powershell,
)
from gatekit.tui.guided_setup.models import (
    DetectedClient,
    DetectedServer,
    ClientType,
    TransportType,
    ServerScope,
)

# Test timestamp constant for restore filenames
TEST_TIMESTAMP = "20251112_142430"


class TestQuotePowerShell:
    """Test PowerShell quoting utility."""

    def test_quote_simple_string(self):
        """Quote a simple string for PowerShell."""
        assert _quote_powershell("simple") == '"simple"'

    def test_quote_with_double_quotes(self):
        """Quote string containing double quotes."""
        assert _quote_powershell('path/to/"file"') == '"path/to/`"file`""'

    def test_quote_with_spaces(self):
        """Quote string containing spaces."""
        assert _quote_powershell("path with spaces") == '"path with spaces"'

    def test_quote_env_var_format(self):
        """Quote environment variable assignment."""
        result = _quote_powershell("GITHUB_TOKEN=ghp_12345")
        assert result == '"GITHUB_TOKEN=ghp_12345"'
        assert result.startswith('"') and result.endswith('"')


class TestScopeHelpers:
    """Test scope determination helpers."""

    def test_get_scope_flag_user(self):
        """Get scope flag for user-level server."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["npx", "test"],
            scope=ServerScope.USER,
        )
        assert _get_scope_flag(server) == "--scope user"

    def test_get_scope_flag_project(self):
        """Get scope flag for project-level server."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["npx", "test"],
            scope=ServerScope.PROJECT,
        )
        assert _get_scope_flag(server) == "--scope project"

    def test_get_scope_flag_none_defaults_to_user(self):
        """Get scope flag defaults to user when not specified."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["npx", "test"],
            scope=None,
        )
        assert _get_scope_flag(server) == "--scope user"


class TestBuildMcpServersJson:
    """Test MCP servers JSON building."""

    def test_build_json_simple_server(self):
        """Build JSON for simple server without env vars."""
        servers = [
            DetectedServer(
                name="filesystem",
                transport=TransportType.STDIO,
                command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                raw_config={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
            )
        ]

        result = _build_mcp_servers_json(servers)

        assert '"mcpServers"' in result
        assert '"filesystem"' in result
        assert '"command": "npx"' in result

    def test_build_json_with_env_vars(self):
        """Build JSON for server with environment variables."""
        servers = [
            DetectedServer(
                name="github",
                transport=TransportType.STDIO,
                command=["npx", "-y", "@modelcontextprotocol/server-github"],
                env={"GITHUB_TOKEN": "ghp_12345"},
                raw_config={
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_12345"},
                },
            )
        ]

        result = _build_mcp_servers_json(servers)

        assert '"mcpServers"' in result
        assert '"github"' in result
        assert '"env"' in result
        assert '"GITHUB_TOKEN": "ghp_12345"' in result

    def test_build_json_multiple_servers(self):
        """Build JSON for multiple servers."""
        servers = [
            DetectedServer(
                "filesystem",
                TransportType.STDIO,
                ["npx", "filesystem"],
                raw_config={"command": "npx", "args": ["filesystem"]},
            ),
            DetectedServer(
                "github",
                TransportType.STDIO,
                ["npx", "github"],
                raw_config={"command": "npx", "args": ["github"]},
            ),
        ]

        result = _build_mcp_servers_json(servers)

        assert '"filesystem"' in result
        assert '"github"' in result


class TestClaudeDesktopRestore:
    """Test Claude Desktop restore script generation."""

    def test_generate_restore_text_file(self, tmp_path):
        """Generate restore instructions as text file."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    raw_config={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
                )
            ],
        )

        script_path = _generate_claude_desktop_restore(client, tmp_path, TEST_TIMESTAMP)

        assert script_path.exists()
        assert script_path.name == f"restore-claude-desktop-{TEST_TIMESTAMP}.txt"

        content = script_path.read_text()
        assert "Gatekit Restore Instructions for Claude Desktop" in content
        assert "SECURITY WARNING" not in content  # No env vars, no warning
        assert "filesystem" in content
        # Accept both Unix and Windows path formats
        assert "claude_desktop_config.json" in content

    def test_restore_includes_env_vars(self, tmp_path):
        """Restore script includes environment variables."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    "github",
                    TransportType.STDIO,
                    ["npx", "github"],
                    env={"GITHUB_TOKEN": "secret123"},
                    raw_config={"command": "npx", "args": ["github"], "env": {"GITHUB_TOKEN": "secret123"}},
                )
            ],
        )

        script_path = _generate_claude_desktop_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        assert "SECURITY WARNING" in content  # Has env vars, should warn
        assert "GITHUB_TOKEN" in content
        assert "secret123" in content
        assert '"env"' in content

    def test_restore_includes_timestamp(self, tmp_path):
        """Restore script includes generation timestamp."""
        from datetime import datetime

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer("test", TransportType.STDIO, ["npx", "test"], raw_config={"command": "npx", "args": ["test"]})
            ],
        )

        # Patch datetime.now() to return a fixed timestamp for deterministic testing
        fixed_time = datetime(2025, 1, 15, 14, 30, 0)
        with patch("gatekit.tui.guided_setup.restore_scripts.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_time
            script_path = _generate_claude_desktop_restore(client, tmp_path, TEST_TIMESTAMP)

        content = script_path.read_text()

        assert "Generated:" in content
        # Check for the fixed timestamp we patched
        assert "2025-01-15 14:30:00" in content


class TestClaudeCodeRestore:
    """Test Claude Code restore script generation."""

    @patch("platform.system", return_value="Darwin")
    def test_generate_restore_bash_script(self, mock_platform, tmp_path):
        """Generate bash restore script for POSIX."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path.home() / ".claude.json",
            servers=[
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    scope=ServerScope.USER,
                )
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)

        assert script_path.exists()
        assert script_path.name == f"restore-claude-code-{TEST_TIMESTAMP}.sh"
        # On POSIX, check that file is executable; skip on Windows where chmod doesn't set execute bits
        import sys
        if sys.platform != "win32":
            assert script_path.stat().st_mode & 0o111  # Check executable bit

        content = script_path.read_text()
        assert "#!/bin/bash" in content
        assert "claude mcp remove" in content
        assert "claude mcp add" in content
        assert "--scope user" in content
        assert "\\" in content  # Bash line continuation

    @patch("platform.system", return_value="Windows")
    def test_generate_restore_windows_text(self, mock_platform, tmp_path):
        """Generate text file for Windows."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("C:/Users/user/.claude.json"),
            servers=[
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\tmp"],
                    scope=ServerScope.USER,
                )
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)

        assert script_path.exists()
        assert script_path.name == f"restore-claude-code-{TEST_TIMESTAMP}.txt"

        content = script_path.read_text()
        assert "PowerShell" in content
        assert "claude mcp remove" in content
        assert "claude mcp add" in content
        assert "`" in content  # PowerShell line continuation

    @patch("platform.system", return_value="Darwin")
    def test_restore_respects_server_scopes(self, mock_platform, tmp_path):
        """Restore script respects individual server scopes in add commands."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path.home() / ".claude.json",
            servers=[
                DetectedServer("user_server", TransportType.STDIO, ["npx", "test1"], scope=ServerScope.USER),
                DetectedServer("project_server", TransportType.STDIO, ["npx", "test2"], scope=ServerScope.PROJECT),
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        # Each add command should have correct scope (no remove commands needed)
        assert "claude mcp add --transport stdio --scope user user_server" in content
        assert "claude mcp add --transport stdio --scope project project_server" in content

        # Should NOT remove original servers (only removes Gatekit)
        assert content.count("claude mcp remove") == 1  # Only "claude mcp remove gatekit"
        assert "claude mcp remove user_server" not in content
        assert "claude mcp remove project_server" not in content

    @patch("platform.system", return_value="Darwin")
    def test_restore_includes_env_vars_posix(self, mock_platform, tmp_path):
        """Restore script includes env vars in bash format."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path.home() / ".claude.json",
            servers=[
                DetectedServer(
                    "github",
                    TransportType.STDIO,
                    ["npx", "github"],
                    env={"GITHUB_TOKEN": "secret123"},
                    scope=ServerScope.USER,
                )
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        assert "--env" in content
        assert "GITHUB_TOKEN=secret123" in content

    @patch("platform.system", return_value="Windows")
    def test_restore_includes_env_vars_windows(self, mock_platform, tmp_path):
        """Restore script includes env vars in PowerShell format."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("C:/Users/user/.claude.json"),
            servers=[
                DetectedServer(
                    "github",
                    TransportType.STDIO,
                    ["npx", "github"],
                    env={"GITHUB_TOKEN": "secret123"},
                    scope=ServerScope.USER,
                )
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        assert "--env" in content
        assert "GITHUB_TOKEN=secret123" in content


class TestCodexRestore:
    """Test Codex restore script generation."""

    @patch("platform.system", return_value="Darwin")
    def test_generate_restore_bash_script(self, mock_platform, tmp_path):
        """Generate bash restore script for POSIX."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path.home() / ".codex" / "config.toml",
            servers=[
                DetectedServer("filesystem", TransportType.STDIO, ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
            ],
        )

        script_path = _generate_codex_restore(client, tmp_path, TEST_TIMESTAMP)

        assert script_path.exists()
        assert script_path.name == f"restore-codex-{TEST_TIMESTAMP}.sh"
        # On POSIX, check that file is executable; skip on Windows where chmod doesn't set execute bits
        import sys
        if sys.platform != "win32":
            assert script_path.stat().st_mode & 0o111  # Executable

        content = script_path.read_text()
        assert "#!/bin/bash" in content
        assert "codex mcp remove" in content
        assert "codex mcp add" in content
        assert "\\" in content  # Bash line continuation

    @patch("platform.system", return_value="Windows")
    def test_generate_restore_windows_text(self, mock_platform, tmp_path):
        """Generate text file for Windows."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("C:/Users/user/.codex/config.toml"),
            servers=[
                DetectedServer("filesystem", TransportType.STDIO, ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\tmp"])
            ],
        )

        script_path = _generate_codex_restore(client, tmp_path, TEST_TIMESTAMP)

        assert script_path.exists()
        assert script_path.name == f"restore-codex-{TEST_TIMESTAMP}.txt"

        content = script_path.read_text()
        assert "PowerShell" in content
        assert "codex mcp remove" in content
        assert "codex mcp add" in content
        assert "`" in content  # PowerShell line continuation

    @patch("platform.system", return_value="Darwin")
    def test_restore_includes_env_vars(self, mock_platform, tmp_path):
        """Restore script includes environment variables."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path.home() / ".codex" / "config.toml",
            servers=[
                DetectedServer(
                    "github",
                    TransportType.STDIO,
                    ["npx", "github"],
                    env={"GITHUB_TOKEN": "secret123"},
                )
            ],
        )

        script_path = _generate_codex_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        assert "--env" in content
        assert "GITHUB_TOKEN=secret123" in content


class TestGenerateRestoreScripts:
    """Test main restore script generation function."""

    @patch("platform.system", return_value="Darwin")
    def test_generate_for_all_clients(self, mock_platform, tmp_path):
        """Generate restore scripts for all detected clients."""
        clients = [
            DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                Path("/home/user/.config/claude_desktop_config.json"),
                [DetectedServer("fs1", TransportType.STDIO, ["npx", "fs"], raw_config={"command": "npx", "args": ["fs"]})],
            ),
            DetectedClient(
                ClientType.CLAUDE_CODE,
                Path.home() / ".claude.json",
                [DetectedServer("fs2", TransportType.STDIO, ["npx", "fs"], scope=ServerScope.USER)],
            ),
            DetectedClient(
                ClientType.CODEX,
                Path.home() / ".codex" / "config.toml",
                [DetectedServer("fs3", TransportType.STDIO, ["npx", "fs"])],
            ),
        ]

        restore_scripts = generate_restore_scripts(clients, tmp_path)

        # Should have 3 restore scripts
        assert len(restore_scripts) == 3
        assert ClientType.CLAUDE_DESKTOP in restore_scripts
        assert ClientType.CLAUDE_CODE in restore_scripts
        assert ClientType.CODEX in restore_scripts

        # All scripts should exist
        assert restore_scripts[ClientType.CLAUDE_DESKTOP].exists()
        assert restore_scripts[ClientType.CLAUDE_CODE].exists()
        assert restore_scripts[ClientType.CODEX].exists()

    @patch("platform.system", return_value="Darwin")
    def test_generate_creates_restore_dir(self, mock_platform, tmp_path):
        """Generate creates restore directory if it doesn't exist."""
        restore_dir = tmp_path / "restore"
        assert not restore_dir.exists()

        clients = [
            DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                Path("/test/config.json"),
                [DetectedServer("test", TransportType.STDIO, ["npx", "test"], raw_config={"command": "npx", "args": ["test"]})],
            )
        ]

        generate_restore_scripts(clients, restore_dir)

        assert restore_dir.exists()
        assert restore_dir.is_dir()

    @patch("platform.system", return_value="Darwin")
    def test_generate_for_single_client(self, mock_platform, tmp_path):
        """Generate restore script for single client."""
        clients = [
            DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                Path("/test/config.json"),
                [DetectedServer("test", TransportType.STDIO, ["npx", "test"], raw_config={"command": "npx", "args": ["test"]})],
            )
        ]

        restore_scripts = generate_restore_scripts(clients, tmp_path)

        assert len(restore_scripts) == 1
        assert ClientType.CLAUDE_DESKTOP in restore_scripts

    def test_generate_handles_empty_client_list(self, tmp_path):
        """Generate handles empty client list gracefully."""
        clients = []

        restore_scripts = generate_restore_scripts(clients, tmp_path)

        assert len(restore_scripts) == 0
        # Should still create the directory
        assert tmp_path.exists()


class TestOriginalNameHandling:
    """Test that restore scripts use original_name for renamed servers."""

    def test_claude_desktop_uses_original_name_in_json(self, tmp_path):
        """Claude Desktop restore JSON uses original_name for renamed servers."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="context7-Codex",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    raw_config={"command": "npx", "args": ["context7"]},
                    original_name="context7",  # Original name in config
                )
            ],
        )

        script_path = _generate_claude_desktop_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        # JSON should use original name, not deduped name
        assert '"context7"' in content
        assert '"context7-Codex"' not in content

    @patch("platform.system", return_value="Darwin")
    def test_claude_code_does_not_remove_servers(self, mock_platform, tmp_path):
        """Claude Code restore does not remove original servers."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path.home() / ".mcp.json",
            servers=[
                DetectedServer(
                    name="context7-Codex",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    scope=ServerScope.PROJECT,
                    original_name="context7-codex",  # Original name in config
                )
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        # Should NOT remove original servers (claude mcp add will replace them automatically)
        assert content.count("claude mcp remove") == 1  # Only "claude mcp remove gatekit"
        assert "claude mcp remove context7" not in content  # Neither original name...
        assert "claude mcp remove context7-Codex" not in content  # ...nor deduped name

    @patch("platform.system", return_value="Darwin")
    def test_claude_code_uses_original_name_for_add(self, mock_platform, tmp_path):
        """Claude Code restore uses original_name in add commands."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path.home() / ".mcp.json",
            servers=[
                DetectedServer(
                    name="context7-Codex",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    scope=ServerScope.PROJECT,
                    original_name="context7-codex",  # Original name in config
                )
            ],
        )

        script_path = _generate_claude_code_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        # Add command should use original name
        assert "claude mcp add --transport stdio --scope project context7-codex" in content
        # Deduped name should NOT appear in add command
        assert "context7-Codex" not in content

    @patch("platform.system", return_value="Darwin")
    def test_codex_does_not_remove_servers(self, mock_platform, tmp_path):
        """Codex restore does not remove original servers."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path.home() / ".codex" / "config.toml",
            servers=[
                DetectedServer(
                    name="context7-Claude-Code",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    original_name="context7",  # Original name in config
                )
            ],
        )

        script_path = _generate_codex_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        # Should NOT remove original servers (codex mcp add will replace them automatically)
        assert content.count("codex mcp remove") == 1  # Only "codex mcp remove gatekit"
        assert "codex mcp remove context7" not in content  # Neither original name...
        assert "codex mcp remove context7-Claude-Code" not in content  # ...nor deduped name

    @patch("platform.system", return_value="Darwin")
    def test_codex_uses_original_name_for_add(self, mock_platform, tmp_path):
        """Codex restore uses original_name in add commands."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path.home() / ".codex" / "config.toml",
            servers=[
                DetectedServer(
                    name="context7-Claude-Code",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    original_name="context7",  # Original name in config
                )
            ],
        )

        script_path = _generate_codex_restore(client, tmp_path, TEST_TIMESTAMP)
        content = script_path.read_text()

        # Add command should use original name
        assert "codex mcp add context7" in content
        # Deduped name should NOT appear
        assert "context7-Claude-Code" not in content
