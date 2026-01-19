"""Unit tests for guided setup environment variable handling."""

import re
from pathlib import Path

from gatekit.tui.guided_setup.migration_instructions import (
    generate_migration_instructions,
    _collect_all_env_vars,
)
from gatekit.tui.guided_setup.models import (
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
)


class TestCollectAllEnvVars:
    """Test collection of environment variables from servers."""

    def test_collect_from_single_server(self):
        """Collect env vars from a single server."""
        server = DetectedServer(
            name="github",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": "ghp_xxx"},
        )

        env_vars, conflicts = _collect_all_env_vars([server])

        assert env_vars == {"GITHUB_TOKEN": "ghp_xxx"}
        assert conflicts == []

    def test_collect_from_multiple_servers(self):
        """Collect and merge env vars from multiple servers."""
        servers = [
            DetectedServer(
                name="github",
                transport=TransportType.STDIO,
                command=["npx", "@modelcontextprotocol/server-github"],
                env={"GITHUB_TOKEN": "ghp_xxx"},
            ),
            DetectedServer(
                name="linear",
                transport=TransportType.STDIO,
                command=["npx", "@modelcontextprotocol/server-linear"],
                env={"LINEAR_TOKEN": "lin_yyy"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {
            "GITHUB_TOKEN": "ghp_xxx",
            "LINEAR_TOKEN": "lin_yyy",
        }
        assert conflicts == []

    def test_collect_from_servers_with_no_env_vars(self):
        """Collect from servers without env vars returns empty dict."""
        servers = [
            DetectedServer(
                name="filesystem",
                transport=TransportType.STDIO,
                command=["npx", "@modelcontextprotocol/server-filesystem"],
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {}
        assert conflicts == []

    def test_collect_from_mixed_servers(self):
        """Collect from mix of servers with and without env vars."""
        servers = [
            DetectedServer(
                name="filesystem",
                transport=TransportType.STDIO,
                command=["npx", "@modelcontextprotocol/server-filesystem"],
            ),
            DetectedServer(
                name="github",
                transport=TransportType.STDIO,
                command=["npx", "@modelcontextprotocol/server-github"],
                env={"GITHUB_TOKEN": "ghp_xxx"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {"GITHUB_TOKEN": "ghp_xxx"}
        assert conflicts == []

    def test_collect_with_conflicting_keys(self):
        """When servers have same env var key, last server wins and conflicts are reported."""
        servers = [
            DetectedServer(
                name="server1",
                transport=TransportType.STDIO,
                command=["cmd1"],
                env={"API_TOKEN": "token1"},
            ),
            DetectedServer(
                name="server2",
                transport=TransportType.STDIO,
                command=["cmd2"],
                env={"API_TOKEN": "token2"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        # Last server's value wins
        assert env_vars == {"API_TOKEN": "token2"}
        # Conflict should be reported
        assert len(conflicts) == 1
        assert "API_TOKEN" in conflicts[0]
        assert "server1" in conflicts[0]
        assert "server2" in conflicts[0]


class TestClaudeDesktopEnvVarMigration:
    """Test Claude Desktop migration includes env vars."""

    def test_migration_instructions_include_env_vars(self):
        """Claude Desktop JSON snippet should include all env vars."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "ghp_xxx"},
                ),
                DetectedServer(
                    name="linear",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-linear"],
                    env={"LINEAR_TOKEN": "lin_yyy"},
                ),
            ],
        )

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            Path("/usr/local/bin/gatekit-gateway"),
            Path("/home/user/gatekit.yaml"),
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # Snippet should contain both env vars
        assert '"GITHUB_TOKEN": "ghp_xxx"' in snippet
        assert '"LINEAR_TOKEN": "lin_yyy"' in snippet
        assert '"env"' in snippet

    def test_migration_without_env_vars(self):
        """Claude Desktop snippet should work without env vars."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                ),
            ],
        )

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            Path("/usr/local/bin/gatekit-gateway"),
            Path("/home/user/gatekit.yaml"),
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # Snippet should NOT contain env field
        assert '"env"' not in snippet


class TestClaudeCodeEnvVarMigration:
    """Test Claude Code migration includes env vars."""

    def test_migration_cli_includes_env_flags(self):
        """Claude Code CLI commands should include --env flags."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "ghp_xxx"},
                ),
                DetectedServer(
                    name="linear",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-linear"],
                    env={"LINEAR_TOKEN": "lin_yyy"},
                ),
            ],
        )

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            Path("/usr/local/bin/gatekit-gateway"),
            Path("/home/user/gatekit.yaml"),
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # CLI command should contain --env flags (may be quoted differently on Windows)
        # Windows uses doubled quotes ("") inside cmd /c wrapper
        assert re.search(r'--env "?"?GITHUB_TOKEN=ghp_xxx"?"?', snippet)
        assert re.search(r'--env "?"?LINEAR_TOKEN=lin_yyy"?"?', snippet)


class TestCodexEnvVarMigration:
    """Test Codex migration includes env vars."""

    def test_migration_cli_includes_env_flags(self):
        """Codex CLI commands should include --env flags."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/home/user/.codex/config.toml"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "ghp_xxx"},
                ),
            ],
        )

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            Path("/usr/local/bin/gatekit-gateway"),
            Path("/home/user/gatekit.yaml"),
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # CLI command should contain --env flag (may be quoted differently on Windows)
        # Windows uses doubled quotes ("") inside cmd /c wrapper
        assert re.search(r'--env "?"?GITHUB_TOKEN=ghp_xxx"?"?', snippet)
