"""Unit tests for migration instructions generation."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from gatekit.tui.guided_setup.migration_instructions import (
    generate_migration_instructions,
    _generate_claude_desktop_instructions,
    _generate_claude_code_instructions,
    _generate_codex_instructions,
    _is_gatekit_server,
    _quote_powershell,
    _format_bullet_list,
    _collect_all_env_vars,
    MigrationInstructions,
)
from gatekit.tui.guided_setup.models import (
    DetectedClient,
    DetectedServer,
    ClientType,
    TransportType,
    ServerScope,
)


class TestIsGatekitServer:
    """Test Gatekit server detection helper."""

    def test_detects_gatekit_gateway_command(self):
        """Detect server with gatekit-gateway command."""
        server = DetectedServer(
            "my-server",
            TransportType.STDIO,
            ["/usr/local/bin/gatekit-gateway", "--config", "/config.yaml"],
        )
        assert _is_gatekit_server(server) is True

    def test_detects_gatekit_via_uv_run(self):
        """Detect server with gatekit-gateway via uv run."""
        server = DetectedServer(
            "gateway",
            TransportType.STDIO,
            ["uv", "run", "gatekit-gateway", "--config", "/config.yaml"],
        )
        assert _is_gatekit_server(server) is True

    def test_detects_gatekit_module_invocation(self):
        """Detect server running gatekit.main module."""
        server = DetectedServer(
            "wg",
            TransportType.STDIO,
            ["python", "-m", "gatekit.main", "--config", "/config.yaml"],
        )
        assert _is_gatekit_server(server) is True

    def test_detects_command_ending_with_gatekit(self):
        """Detect server with command ending in 'gatekit'."""
        server = DetectedServer(
            "custom",
            TransportType.STDIO,
            ["/usr/local/bin/my-gatekit", "--config", "/config.yaml"],
        )
        assert _is_gatekit_server(server) is True

    def test_does_not_detect_non_gatekit_server(self):
        """Don't detect non-Gatekit servers."""
        server = DetectedServer(
            "filesystem",
            TransportType.STDIO,
            ["npx", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        assert _is_gatekit_server(server) is False

    def test_does_not_detect_gatekit_directory_as_argument(self):
        """Don't falsely detect when 'gatekit' is just a directory path argument.

        Regression test for false positive when filesystem server points to
        a directory named 'gatekit'.
        """
        # This was causing a false positive because the path ends with "gatekit"
        server = DetectedServer(
            "filesystem",
            TransportType.STDIO,
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects/gatekit"],
        )
        assert _is_gatekit_server(server) is False

    def test_handles_server_without_command(self):
        """Handle server without command gracefully."""
        server = DetectedServer(
            "http-server",
            TransportType.HTTP,
            command=None,
            url="http://localhost:8000",
        )
        assert _is_gatekit_server(server) is False


class TestQuotePowerShell:
    """Test PowerShell quoting utility."""

    def test_quote_simple_string(self):
        """Quote a simple string for PowerShell."""
        assert _quote_powershell("simple") == '"simple"'

    def test_quote_with_double_quotes(self):
        """Quote string containing double quotes."""
        assert _quote_powershell('path/to/"file"') == '"path/to/`"file`""'

    def test_quote_path_with_spaces(self):
        """Quote path containing spaces."""
        result = _quote_powershell("C:\\Program Files\\gatekit\\gateway.exe")
        assert result.startswith('"')
        assert result.endswith('"')
        assert "Program Files" in result


class TestFormatBulletList:
    """Test bullet list formatting."""

    def test_format_single_item(self):
        """Format single item as bullet point."""
        result = _format_bullet_list(["item1"])
        assert result == "• item1"

    def test_format_multiple_items(self):
        """Format multiple items as bullet points."""
        result = _format_bullet_list(["item1", "item2", "item3"])
        assert result == "• item1\n• item2\n• item3"

    def test_format_empty_list(self):
        """Format empty list."""
        result = _format_bullet_list([])
        assert result == ""


class TestCollectAllEnvVars:
    """Test environment variable collection."""

    def test_collect_from_single_server(self):
        """Collect env vars from single server."""
        servers = [
            DetectedServer(
                "github",
                TransportType.STDIO,
                ["npx", "github"],
                env={"GITHUB_TOKEN": "secret123"},
            )
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {"GITHUB_TOKEN": "secret123"}
        assert conflicts == []

    def test_collect_from_multiple_servers(self):
        """Collect and merge env vars from multiple servers."""
        servers = [
            DetectedServer(
                "github",
                TransportType.STDIO,
                ["npx", "github"],
                env={"GITHUB_TOKEN": "secret123"},
            ),
            DetectedServer(
                "linear",
                TransportType.STDIO,
                ["npx", "linear"],
                env={"LINEAR_TOKEN": "linear456"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {"GITHUB_TOKEN": "secret123", "LINEAR_TOKEN": "linear456"}
        assert conflicts == []

    def test_collect_with_conflicts_last_wins(self):
        """Conflicting env vars - last server wins and conflicts are reported."""
        servers = [
            DetectedServer(
                "server1",
                TransportType.STDIO,
                ["npx", "s1"],
                env={"TOKEN": "value1"},
            ),
            DetectedServer(
                "server2",
                TransportType.STDIO,
                ["npx", "s2"],
                env={"TOKEN": "value2"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        # Last server's value should win
        assert env_vars["TOKEN"] == "value2"
        # Conflict should be reported
        assert len(conflicts) == 1
        assert "TOKEN" in conflicts[0]

    def test_collect_from_servers_without_env(self):
        """Collect from servers without env vars."""
        servers = [
            DetectedServer("server1", TransportType.STDIO, ["npx", "s1"]),
            DetectedServer("server2", TransportType.STDIO, ["npx", "s2"]),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {}
        assert conflicts == []

    def test_collect_empty_server_list(self):
        """Collect from empty server list."""
        env_vars, conflicts = _collect_all_env_vars([])
        assert env_vars == {}
        assert conflicts == []


class TestClaudeDesktopInstructions:
    """Test Claude Desktop migration instructions."""

    def test_generate_simple_instructions(self):
        """Generate instructions for simple server."""
        # Create a temporary config file with existing content
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                    }
                },
                "version": "1.0"
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            client = DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=config_file,
                servers=[
                    DetectedServer(
                        "filesystem",
                        TransportType.STDIO,
                        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    )
                ],
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            gatekit_config_path = Path("/home/user/gatekit/configs/gatekit.yaml")

            stdio_servers = client.get_stdio_servers()
            instr = _generate_claude_desktop_instructions(client, stdio_servers, stdio_servers, gateway_path, gatekit_config_path)

            assert isinstance(instr, MigrationInstructions)
            assert instr.client_type == ClientType.CLAUDE_DESKTOP
            assert "filesystem" in instr.servers_to_migrate

            # Verify the snippet contains the complete config with gatekit
            snippet_data = json.loads(instr.migration_snippet)
            assert "gatekit" in snippet_data["mcpServers"]
            assert snippet_data["mcpServers"]["gatekit"]["command"] == str(gateway_path)
            assert snippet_data["mcpServers"]["gatekit"]["args"] == ["--config", str(gatekit_config_path)]

            # Verify other config settings are preserved
            assert snippet_data["version"] == "1.0"

            # Verify filesystem server is replaced (not in the new config)
            assert "filesystem" not in snippet_data["mcpServers"]
        finally:
            config_file.unlink()

    def test_instructions_include_json_snippet(self):
        """Instructions include JSON snippet for complete config file."""
        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "test": {
                        "command": "npx",
                        "args": ["test"]
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            client = DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                config_file,
                [DetectedServer("test", TransportType.STDIO, ["npx", "test"])],
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            gatekit_config_path = Path("/home/user/config.yaml")

            stdio_servers = client.get_stdio_servers()
            instr = _generate_claude_desktop_instructions(client, stdio_servers, stdio_servers, gateway_path, gatekit_config_path)

            # Should be valid JSON structure with complete config
            snippet_data = json.loads(instr.migration_snippet)
            assert "mcpServers" in snippet_data
            assert "gatekit" in snippet_data["mcpServers"]
            assert "command" in snippet_data["mcpServers"]["gatekit"]
            assert "args" in snippet_data["mcpServers"]["gatekit"]
        finally:
            config_file.unlink()

    def test_instructions_include_env_vars(self):
        """Instructions include environment variables when present."""
        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "args": ["github"],
                        "env": {"GITHUB_TOKEN": "secret123"}
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            client = DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                config_file,
                [
                    DetectedServer(
                        "github",
                        TransportType.STDIO,
                        ["npx", "github"],
                        env={"GITHUB_TOKEN": "secret123"},
                    )
                ],
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            gatekit_config_path = Path("/home/user/config.yaml")

            stdio_servers = client.get_stdio_servers()
            instr = _generate_claude_desktop_instructions(client, stdio_servers, stdio_servers, gateway_path, gatekit_config_path)

            # Should include env section in JSON
            snippet_data = json.loads(instr.migration_snippet)
            assert "env" in snippet_data["mcpServers"]["gatekit"]
            assert snippet_data["mcpServers"]["gatekit"]["env"]["GITHUB_TOKEN"] == "secret123"
        finally:
            config_file.unlink()

    def test_instructions_collect_env_from_all_servers(self):
        """Instructions collect env vars from all servers."""
        # Create a temporary config file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "args": ["github"],
                        "env": {"GITHUB_TOKEN": "gh_secret"}
                    },
                    "linear": {
                        "command": "npx",
                        "args": ["linear"],
                        "env": {"LINEAR_TOKEN": "linear_secret"}
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            client = DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                config_file,
                [
                    DetectedServer(
                        "github",
                        TransportType.STDIO,
                        ["npx", "github"],
                        env={"GITHUB_TOKEN": "gh_secret"},
                    ),
                    DetectedServer(
                        "linear",
                        TransportType.STDIO,
                        ["npx", "linear"],
                        env={"LINEAR_TOKEN": "linear_secret"},
                    ),
                ],
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            gatekit_config_path = Path("/home/user/config.yaml")

            stdio_servers = client.get_stdio_servers()
            instr = _generate_claude_desktop_instructions(client, stdio_servers, stdio_servers, gateway_path, gatekit_config_path)

            # Should include both env vars in the gatekit server config
            snippet_data = json.loads(instr.migration_snippet)
            assert "GITHUB_TOKEN" in snippet_data["mcpServers"]["gatekit"]["env"]
            assert "LINEAR_TOKEN" in snippet_data["mcpServers"]["gatekit"]["env"]
            assert snippet_data["mcpServers"]["gatekit"]["env"]["GITHUB_TOKEN"] == "gh_secret"
            assert snippet_data["mcpServers"]["gatekit"]["env"]["LINEAR_TOKEN"] == "linear_secret"
        finally:
            config_file.unlink()

    def test_instructions_preserve_other_config_settings(self):
        """Instructions preserve non-mcpServers config settings."""
        # Create a temporary config file with additional settings
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                    }
                },
                "version": "1.0",
                "customSetting": "value123",
                "nestedSetting": {
                    "key1": "value1",
                    "key2": "value2"
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            client = DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                config_file,
                [
                    DetectedServer(
                        "filesystem",
                        TransportType.STDIO,
                        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    )
                ],
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            gatekit_config_path = Path("/home/user/config.yaml")

            stdio_servers = client.get_stdio_servers()
            instr = _generate_claude_desktop_instructions(client, stdio_servers, stdio_servers, gateway_path, gatekit_config_path)

            # Parse the snippet and verify all non-mcpServers settings are preserved
            snippet_data = json.loads(instr.migration_snippet)

            # mcpServers should only contain gatekit now
            assert "gatekit" in snippet_data["mcpServers"]
            assert "filesystem" not in snippet_data["mcpServers"]
            assert len(snippet_data["mcpServers"]) == 1

            # Other settings should be preserved exactly
            assert snippet_data["version"] == "1.0"
            assert snippet_data["customSetting"] == "value123"
            assert snippet_data["nestedSetting"]["key1"] == "value1"
            assert snippet_data["nestedSetting"]["key2"] == "value2"
        finally:
            config_file.unlink()

    def test_instructions_handle_nonexistent_config_file(self):
        """Instructions handle non-existent config file gracefully."""
        # Use a path that definitely doesn't exist
        config_file = Path("/nonexistent/path/to/config.json")

        client = DetectedClient(
            ClientType.CLAUDE_DESKTOP,
            config_file,
            [DetectedServer("test", TransportType.STDIO, ["npx", "test"])],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        gatekit_config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_desktop_instructions(client, stdio_servers, stdio_servers, gateway_path, gatekit_config_path)

        # Should create minimal config with just mcpServers
        snippet_data = json.loads(instr.migration_snippet)
        assert "mcpServers" in snippet_data
        assert "gatekit" in snippet_data["mcpServers"]
        # Should have no other keys since file didn't exist
        assert len(snippet_data) == 1

    def test_updates_gatekit_config_path_when_already_configured(self):
        """When client already has gatekit, update config path to new one."""
        # Create a config file with existing gatekit entry pointing to OLD config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "gatekit": {
                        "command": "/usr/local/bin/gatekit-gateway",
                        "args": ["--config", "/old/path/to/gatekit.yaml"]
                    },
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            # Client has gatekit configured
            client = DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=config_file,
                servers=[
                    DetectedServer(
                        "gatekit",
                        TransportType.STDIO,
                        ["/usr/local/bin/gatekit-gateway", "--config", "/old/path/to/gatekit.yaml"],
                    ),
                    DetectedServer(
                        "filesystem",
                        TransportType.STDIO,
                        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    )
                ],
                gatekit_config_path="/old/path/to/gatekit.yaml"  # Client already has gatekit
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            new_gatekit_config_path = Path("/new/path/to/gatekit.yaml")  # NEW config path

            # Select filesystem server to migrate
            stdio_servers = [s for s in client.get_stdio_servers() if s.name == "filesystem"]
            all_stdio_servers = client.get_stdio_servers()

            instr = _generate_claude_desktop_instructions(
                client, stdio_servers, all_stdio_servers, gateway_path, new_gatekit_config_path
            )

            # Parse the snippet
            snippet_data = json.loads(instr.migration_snippet)

            # Verify gatekit entry exists and points to NEW config
            assert "gatekit" in snippet_data["mcpServers"]
            assert snippet_data["mcpServers"]["gatekit"]["command"] == str(gateway_path)
            assert snippet_data["mcpServers"]["gatekit"]["args"] == ["--config", str(new_gatekit_config_path)]

            # Verify filesystem server was removed (migrated to gatekit)
            assert "filesystem" not in snippet_data["mcpServers"]

            # Verify only gatekit is in the config
            assert len(snippet_data["mcpServers"]) == 1
        finally:
            config_file.unlink()

    def test_updates_gatekit_when_no_servers_selected(self):
        """When client already has gatekit but no new servers selected, still update config path."""
        # Create a config file with ONLY gatekit entry
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "gatekit": {
                        "command": "/usr/local/bin/gatekit-gateway",
                        "args": ["--config", "/old/path/to/gatekit.yaml"]
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            # Client has ONLY gatekit configured (all servers already in gatekit config)
            client = DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=config_file,
                servers=[
                    DetectedServer(
                        "gatekit",
                        TransportType.STDIO,
                        ["/usr/local/bin/gatekit-gateway", "--config", "/old/path/to/gatekit.yaml"],
                    ),
                ],
                gatekit_config_path="/old/path/to/gatekit.yaml"  # Client already has gatekit
            )

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            new_gatekit_config_path = Path("/new/path/to/gatekit.yaml")  # NEW config path

            # No servers selected (empty list) - simulates case where all servers already in gatekit
            selected_servers = []
            all_stdio_servers = client.get_stdio_servers()

            instr = _generate_claude_desktop_instructions(
                client, selected_servers, all_stdio_servers, gateway_path, new_gatekit_config_path
            )

            # Parse the snippet
            snippet_data = json.loads(instr.migration_snippet)

            # Verify gatekit entry was STILL updated to point to NEW config
            assert "gatekit" in snippet_data["mcpServers"]
            assert snippet_data["mcpServers"]["gatekit"]["command"] == str(gateway_path)
            assert snippet_data["mcpServers"]["gatekit"]["args"] == ["--config", str(new_gatekit_config_path)]

            # Verify only gatekit is in the config
            assert len(snippet_data["mcpServers"]) == 1
        finally:
            config_file.unlink()


class TestClaudeCodeInstructions:
    """Test Claude Code migration instructions."""

    @patch("platform.system", return_value="Darwin")
    def test_generate_posix_instructions(self, mock_platform):
        """Generate instructions for POSIX (bash)."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    scope=ServerScope.USER,
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        assert isinstance(instr, MigrationInstructions)
        assert instr.client_type == ClientType.CLAUDE_CODE
        assert "filesystem" in instr.servers_to_migrate
        assert "claude mcp remove" in instr.migration_snippet
        assert "claude mcp add" in instr.migration_snippet
        assert "\\" in instr.migration_snippet  # Bash line continuation
        assert "--scope user" in instr.migration_snippet

    @patch("platform.system", return_value="Windows")
    def test_generate_windows_instructions(self, mock_platform):
        """Generate instructions for Windows (PowerShell)."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path("C:/Users/user/.claude.json"),
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\tmp"],
                    scope=ServerScope.USER,
                )
            ],
        )

        gateway_path = Path("C:/Users/user/AppData/Roaming/Python/gatekit-gateway.exe")
        config_path = Path("C:/Users/user/gatekit/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        assert "claude mcp remove" in instr.migration_snippet
        assert "claude mcp add" in instr.migration_snippet
        # Windows uses cmd /c wrapper with doubled quotes for cross-shell compatibility
        assert 'cmd /c "' in instr.migration_snippet
        assert '""' in instr.migration_snippet  # Doubled quotes for paths
        assert "PowerShell or Command Prompt" in instr.instruction_text

    @patch("platform.system", return_value="Darwin")
    def test_instructions_respect_server_scopes(self, mock_platform):
        """Instructions respect individual server scopes."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer("user_server", TransportType.STDIO, ["npx", "test1"], scope=ServerScope.USER),
                DetectedServer("project_server", TransportType.STDIO, ["npx", "test2"], scope=ServerScope.PROJECT),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        # Each remove command should have correct scope
        assert "claude mcp remove user_server --scope user" in instr.migration_snippet
        assert "claude mcp remove project_server --scope project" in instr.migration_snippet

    @patch("platform.system", return_value="Darwin")
    def test_instructions_include_env_vars(self, mock_platform):
        """Instructions include environment variables."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "github",
                    TransportType.STDIO,
                    ["npx", "github"],
                    env={"GITHUB_TOKEN": "secret123"},
                    scope=ServerScope.USER,
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        assert "--env" in instr.migration_snippet
        assert "GITHUB_TOKEN=secret123" in instr.migration_snippet

    @patch("platform.system", return_value="Darwin")
    def test_generate_with_zero_selected_servers(self, mock_platform):
        """Generate instructions to add Gatekit even when no servers are selected.

        Client configuration is independent of server selection - if user selected
        this client, they want to connect it to Gatekit regardless of which servers
        (if any) from that client are migrated.
        """
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        # Pass empty list of servers to migrate
        instr = _generate_claude_code_instructions(client, [], gateway_path, config_path)

        assert isinstance(instr, MigrationInstructions)
        assert instr.client_type == ClientType.CLAUDE_CODE
        assert instr.servers_to_migrate == []
        # Should still add Gatekit (no server removal, just adding Gatekit)
        assert "claude mcp add" in instr.migration_snippet
        assert "gatekit" in instr.migration_snippet
        # Should NOT have removal commands
        assert "claude mcp remove" not in instr.migration_snippet

    @patch("platform.system", return_value="Darwin")
    def test_uses_original_name_for_renamed_servers(self, mock_platform):
        """Use original_name (not deduped name) for removal commands."""
        # Simulate a server that was renamed during deduplication
        # Original name: "context7-codex" (what's in the actual config file)
        # Deduped name: "context7-Codex" (what we use for internal tracking)
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".mcp.json",
            [
                DetectedServer(
                    name="context7-Codex",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    scope=ServerScope.PROJECT,
                    original_name="context7-codex",  # Original name in config
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        # Verify removal command uses ORIGINAL name, not deduped name
        assert "claude mcp remove context7-codex --scope project" in instr.migration_snippet
        assert "context7-Codex" not in instr.migration_snippet  # Deduped name should NOT appear

    @patch("platform.system", return_value="Darwin")
    def test_uses_echo_not_comments(self, mock_platform):
        """Use echo statements instead of comments to avoid copy-paste errors."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        # Should use echo statements, not comments
        assert "echo 'Removing original servers...'" in instr.migration_snippet
        assert "echo 'Adding Gatekit...'" in instr.migration_snippet

        # Should NOT have standalone comment lines (which cause errors on copy-paste)
        assert "# Remove original servers" not in instr.migration_snippet
        assert "# Add Gatekit" not in instr.migration_snippet

    @patch("platform.system", return_value="Darwin")
    def test_removes_existing_gatekit_before_adding(self, mock_platform):
        """Remove existing Gatekit configuration before adding new one (user scope)."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "gatekit",
                    TransportType.STDIO,
                    ["/old/path/gatekit-gateway", "--config", "/old/config.yaml"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                ),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = [client.servers[1]]  # Only migrate filesystem, not gatekit
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        snippet = instr.migration_snippet

        # Should remove existing gatekit first
        assert "echo 'Removing existing Gatekit configuration...'" in snippet
        assert "claude mcp remove gatekit --scope user" in snippet

        # Should appear BEFORE other removal commands
        gatekit_remove_idx = snippet.index("claude mcp remove gatekit --scope user")
        filesystem_remove_idx = snippet.index("claude mcp remove filesystem --scope user")
        assert gatekit_remove_idx < filesystem_remove_idx

        # Should still add new Gatekit
        assert "claude mcp add" in snippet
        assert "gatekit" in snippet

    @patch("platform.system", return_value="Darwin")
    def test_removes_existing_gatekit_project_scope(self, mock_platform):
        """Remove existing Gatekit from project scope before adding new one."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / "project" / ".mcp.json",
            [
                DetectedServer(
                    "gatekit",
                    TransportType.STDIO,
                    ["/old/path/gatekit-gateway", "--config", "/old/config.yaml"],
                    scope=ServerScope.PROJECT,
                ),
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.PROJECT,
                ),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = [client.servers[1]]  # Only migrate filesystem
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        snippet = instr.migration_snippet

        # Should remove existing gatekit with PROJECT scope
        assert "claude mcp remove gatekit --scope project" in snippet
        assert "echo 'Removing existing Gatekit configuration...'" in snippet

    @patch("platform.system", return_value="Darwin")
    def test_no_gatekit_removal_when_not_present(self, mock_platform):
        """Don't add removal command when Gatekit doesn't exist."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                ),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        snippet = instr.migration_snippet

        # Should NOT have gatekit removal command
        assert "Removing existing Gatekit configuration" not in snippet
        # Should only have removal for filesystem, not gatekit
        assert snippet.count("claude mcp remove") == 1
        assert "claude mcp remove filesystem" in snippet

    @patch("platform.system", return_value="Darwin")
    def test_removes_multiple_gatekit_entries_from_different_scopes(self, mock_platform):
        """Remove ALL Gatekit entries when they exist in multiple scopes."""
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "gatekit",
                    TransportType.STDIO,
                    ["/usr/local/bin/gatekit-gateway", "--config", "/user/config.yaml"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    "gatekit-project",
                    TransportType.STDIO,
                    ["uv", "run", "gatekit-gateway", "--config", "/project/config.yaml"],
                    scope=ServerScope.PROJECT,
                ),
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                ),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = [client.servers[2]]  # Only migrate filesystem
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        snippet = instr.migration_snippet

        # Should remove BOTH Gatekit entries
        assert "claude mcp remove gatekit --scope user" in snippet
        assert "claude mcp remove gatekit-project --scope project" in snippet
        assert "echo 'Removing existing Gatekit configuration...'" in snippet

        # Both should appear before filesystem removal
        gatekit_user_idx = snippet.index("claude mcp remove gatekit --scope user")
        gatekit_proj_idx = snippet.index("claude mcp remove gatekit-project --scope project")
        filesystem_idx = snippet.index("claude mcp remove filesystem --scope user")
        assert gatekit_user_idx < filesystem_idx
        assert gatekit_proj_idx < filesystem_idx

    @patch("platform.system", return_value="Darwin")
    def test_uses_original_name_for_renamed_gatekit(self, mock_platform):
        """Use original_name for Gatekit removal when server was renamed."""
        # Simulate Gatekit server that was renamed during deduplication
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    name="gatekit (2)",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["/usr/local/bin/gatekit-gateway", "--config", "/old/config.yaml"],
                    scope=ServerScope.USER,
                    original_name="gatekit",  # Original name in config
                ),
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                ),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = [client.servers[1]]  # Only migrate filesystem
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        snippet = instr.migration_snippet

        # Should use ORIGINAL name, not deduped name
        assert "claude mcp remove gatekit --scope user" in snippet
        assert "gatekit (2)" not in snippet  # Deduped name should NOT appear

    @patch("platform.system", return_value="Darwin")
    def test_detects_gatekit_by_command_not_name(self, mock_platform):
        """Detect Gatekit by command pattern, not server name."""
        # User named their Gatekit server something else
        client = DetectedClient(
            ClientType.CLAUDE_CODE,
            Path.home() / ".claude.json",
            [
                DetectedServer(
                    "my-custom-gateway",  # NOT named "gatekit"
                    TransportType.STDIO,
                    ["/usr/local/bin/gatekit-gateway", "--config", "/config.yaml"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                    scope=ServerScope.USER,
                ),
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = [client.servers[1]]  # Only migrate filesystem
        instr = _generate_claude_code_instructions(client, stdio_servers, gateway_path, config_path)

        snippet = instr.migration_snippet

        # Should detect and remove the custom-named Gatekit server
        assert "claude mcp remove my-custom-gateway --scope user" in snippet
        assert "echo 'Removing existing Gatekit configuration...'" in snippet


class TestCodexInstructions:
    """Test Codex migration instructions."""

    @patch("platform.system", return_value="Darwin")
    def test_generate_posix_instructions(self, mock_platform):
        """Generate instructions for POSIX (bash)."""
        client = DetectedClient(
            ClientType.CODEX,
            Path.home() / ".codex" / "config.toml",
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_codex_instructions(client, stdio_servers, gateway_path, config_path)

        assert isinstance(instr, MigrationInstructions)
        assert instr.client_type == ClientType.CODEX
        assert "filesystem" in instr.servers_to_migrate
        assert "codex mcp remove" in instr.migration_snippet
        assert "codex mcp add" in instr.migration_snippet
        assert "\\" in instr.migration_snippet  # Bash line continuation

    @patch("platform.system", return_value="Windows")
    def test_generate_windows_instructions(self, mock_platform):
        """Generate instructions for Windows (PowerShell)."""
        client = DetectedClient(
            ClientType.CODEX,
            Path("C:/Users/user/.codex/config.toml"),
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\tmp"],
                )
            ],
        )

        gateway_path = Path("C:/Users/user/AppData/Roaming/Python/gatekit-gateway.exe")
        config_path = Path("C:/Users/user/gatekit/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_codex_instructions(client, stdio_servers, gateway_path, config_path)

        assert "codex mcp remove" in instr.migration_snippet
        assert "codex mcp add" in instr.migration_snippet
        # Windows uses cmd /c wrapper with doubled quotes for cross-shell compatibility
        assert 'cmd /c "' in instr.migration_snippet
        assert '""' in instr.migration_snippet  # Doubled quotes for paths
        assert "PowerShell or Command Prompt" in instr.instruction_text

    @patch("platform.system", return_value="Darwin")
    def test_instructions_include_env_vars(self, mock_platform):
        """Instructions include environment variables."""
        client = DetectedClient(
            ClientType.CODEX,
            Path.home() / ".codex" / "config.toml",
            [
                DetectedServer(
                    "github",
                    TransportType.STDIO,
                    ["npx", "github"],
                    env={"GITHUB_TOKEN": "secret123"},
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_codex_instructions(client, stdio_servers, gateway_path, config_path)

        assert "--env" in instr.migration_snippet
        assert "GITHUB_TOKEN=secret123" in instr.migration_snippet

    @patch("platform.system", return_value="Darwin")
    def test_uses_original_name_for_renamed_servers(self, mock_platform):
        """Use original_name (not deduped name) for removal commands."""
        # Simulate a server that was renamed during deduplication
        client = DetectedClient(
            ClientType.CODEX,
            Path.home() / ".codex" / "config.toml",
            [
                DetectedServer(
                    name="context7-Claude-Code",  # Deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    original_name="context7",  # Original name in config
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_codex_instructions(client, stdio_servers, gateway_path, config_path)

        # Verify removal command uses ORIGINAL name, not deduped name
        assert "codex mcp remove context7" in instr.migration_snippet
        assert "context7-Claude-Code" not in instr.migration_snippet  # Deduped name should NOT appear

    @patch("platform.system", return_value="Darwin")
    def test_uses_echo_not_comments(self, mock_platform):
        """Use echo statements instead of comments to avoid copy-paste errors."""
        client = DetectedClient(
            ClientType.CODEX,
            Path.home() / ".codex" / "config.toml",
            [
                DetectedServer(
                    "filesystem",
                    TransportType.STDIO,
                    ["npx", "filesystem"],
                )
            ],
        )

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        stdio_servers = client.get_stdio_servers()
        instr = _generate_codex_instructions(client, stdio_servers, gateway_path, config_path)

        # Should use echo statements, not comments
        assert "echo 'Removing original servers...'" in instr.migration_snippet
        assert "echo 'Adding Gatekit...'" in instr.migration_snippet

        # Should NOT have standalone comment lines (which cause errors on copy-paste)
        assert "# Remove original servers" not in instr.migration_snippet
        assert "# Add Gatekit" not in instr.migration_snippet


class TestGenerateMigrationInstructions:
    """Test main migration instructions generation function."""

    @patch("platform.system", return_value="Darwin")
    def test_generate_for_all_clients(self, mock_platform):
        """Generate instructions for all detected clients."""
        clients = [
            DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                Path("/home/user/.config/claude_desktop_config.json"),
                [DetectedServer("fs1", TransportType.STDIO, ["npx", "fs"])],
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

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        instructions = generate_migration_instructions(clients, {s.name for c in clients for s in c.get_stdio_servers()}, gateway_path, config_path)

        # Should have 3 instruction sets
        assert len(instructions) == 3

        client_types = [i.client_type for i in instructions]
        assert ClientType.CLAUDE_DESKTOP in client_types
        assert ClientType.CLAUDE_CODE in client_types
        assert ClientType.CODEX in client_types

    @patch("platform.system", return_value="Darwin")
    def test_generate_for_single_client(self, mock_platform):
        """Generate instructions for single client."""
        clients = [
            DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                Path("/test/config.json"),
                [DetectedServer("test", TransportType.STDIO, ["npx", "test"])],
            )
        ]

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        instructions = generate_migration_instructions(clients, {s.name for c in clients for s in c.get_stdio_servers()}, gateway_path, config_path)

        assert len(instructions) == 1
        assert instructions[0].client_type == ClientType.CLAUDE_DESKTOP

    def test_generate_handles_empty_client_list(self):
        """Generate handles empty client list gracefully."""
        clients = []

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/config.yaml")

        instructions = generate_migration_instructions(clients, {s.name for c in clients for s in c.get_stdio_servers()}, gateway_path, config_path)

        assert len(instructions) == 0

    @patch("platform.system", return_value="Darwin")
    def test_generate_includes_clients_without_stdio_servers(self, mock_platform):
        """Generate includes clients even with no stdio servers (e.g., HTTP-only).

        User explicitly selected this client, so we generate instructions
        showing how to set up Gatekit even though no servers will be migrated.
        """
        # Create a temporary config file with HTTP server
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "http-server": {
                        "url": "https://example.com"
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            clients = [
                DetectedClient(
                    ClientType.CLAUDE_DESKTOP,
                    config_file,
                    [DetectedServer("http-server", TransportType.HTTP, url="https://example.com")],
                )
            ]

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            config_path = Path("/home/user/config.yaml")

            instructions = generate_migration_instructions(clients, {s.name for c in clients for s in c.get_stdio_servers()}, gateway_path, config_path)

            # Should generate instructions even though no stdio servers
            assert len(instructions) == 1
            assert instructions[0].client_type == ClientType.CLAUDE_DESKTOP

            # Should show "No servers selected" message (because no stdio servers to select)
            assert "No servers selected" in instructions[0].instruction_text

            # Config should preserve the HTTP server AND add Gatekit
            # (User selected this client, so they want to connect to Gatekit)
            config_data = json.loads(instructions[0].migration_snippet)
            assert "http-server" in config_data["mcpServers"]
            assert "gatekit" in config_data["mcpServers"]
        finally:
            config_file.unlink()

    @patch("platform.system", return_value="Darwin")
    def test_generate_uses_absolute_paths(self, mock_platform):
        """Generate uses absolute paths (no tilde expansion)."""
        clients = [
            DetectedClient(
                ClientType.CLAUDE_DESKTOP,
                Path("/home/user/.config/claude_desktop_config.json"),
                [DetectedServer("test", TransportType.STDIO, ["npx", "test"])],
            )
        ]

        gateway_path = Path("/usr/local/bin/gatekit-gateway")
        config_path = Path("/home/user/gatekit/config.yaml")

        instructions = generate_migration_instructions(clients, {s.name for c in clients for s in c.get_stdio_servers()}, gateway_path, config_path)

        # Paths should be absolute (full paths, not ~)
        # Accept both Unix and Windows path formats (Windows escapes backslashes in JSON)
        snippet = instructions[0].migration_snippet
        assert "gatekit-gateway" in snippet
        assert "config.yaml" in snippet
        assert "~" not in snippet

    @patch("platform.system", return_value="Darwin")
    def test_generate_includes_clients_with_zero_selected_servers(self, mock_platform):
        """Generate includes clients even when no servers are selected for migration.

        This tests the bug fix where clients were being skipped if the user
        deselected all their servers. Now we generate instructions showing
        how to preserve existing servers.
        """
        # Create a temporary config file with existing servers
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            existing_config = {
                "mcpServers": {
                    "domain-names": {
                        "command": "npx",
                        "args": ["domain-names"]
                    },
                    "github": {
                        "command": "npx",
                        "args": ["github"]
                    }
                }
            }
            json.dump(existing_config, f)
            config_file = Path(f.name)

        try:
            # Create a client with servers, but select none of them
            clients = [
                DetectedClient(
                    ClientType.CLAUDE_DESKTOP,
                    config_file,
                    [
                        DetectedServer("domain-names", TransportType.STDIO, ["npx", "domain-names"]),
                        DetectedServer("github", TransportType.STDIO, ["npx", "github"]),
                    ],
                )
            ]

            gateway_path = Path("/usr/local/bin/gatekit-gateway")
            config_path = Path("/home/user/config.yaml")

            # Select NO servers (empty set)
            selected_servers = set()

            instructions = generate_migration_instructions(clients, selected_servers, gateway_path, config_path)

            # Should still generate instructions for the client
            assert len(instructions) == 1
            assert instructions[0].client_type == ClientType.CLAUDE_DESKTOP

            # Should show "No servers selected" message
            assert "No servers selected" in instructions[0].instruction_text

            # Should have empty servers_to_migrate list
            assert instructions[0].servers_to_migrate == []

            # Config snippet should preserve existing servers AND add Gatekit
            # (User selected this client, so they want to connect to Gatekit)
            config_data = json.loads(instructions[0].migration_snippet)
            assert "domain-names" in config_data["mcpServers"]
            assert "github" in config_data["mcpServers"]
            assert "gatekit" in config_data["mcpServers"]
        finally:
            config_file.unlink()
