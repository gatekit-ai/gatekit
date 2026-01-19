"""Unit tests for guided setup per-server scope handling (QC fix verification)."""

from pathlib import Path

from gatekit.tui.guided_setup.migration_instructions import (
    generate_migration_instructions,
    _get_scope_flag,
)
from gatekit.tui.guided_setup.restore_scripts import (
    _generate_claude_code_restore_posix,
    _generate_claude_code_restore_windows,
)
from gatekit.tui.guided_setup.models import (
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
    ServerScope,
)


class TestPerServerScopeHandling:
    """Test that each server uses its own scope flag in commands."""

    def test_get_scope_flag_user(self):
        """Get scope flag for user-scoped server."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["test"],
            scope=ServerScope.USER,
        )

        assert _get_scope_flag(server) == "--scope user"

    def test_get_scope_flag_project(self):
        """Get scope flag for project-scoped server."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["test"],
            scope=ServerScope.PROJECT,
        )

        assert _get_scope_flag(server) == "--scope project"

    def test_get_scope_flag_none_defaults_to_user(self):
        """Get scope flag when scope is None - should default to user."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["test"],
            scope=None,
        )

        assert _get_scope_flag(server) == "--scope user"


class TestMigrationInstructionsScopeHandling:
    """Test migration instructions handle mixed scopes correctly."""

    def test_migration_instructions_mixed_scopes(self):
        """Migration instructions should use correct scope for each server."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="user-server",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    name="project-server",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    scope=ServerScope.PROJECT,
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

        # Each server should have its own scope in the remove command
        assert "claude mcp remove user-server --scope user" in snippet
        assert "claude mcp remove project-server --scope project" in snippet

        # Gatekit always uses user scope
        assert "claude mcp add --transport stdio --scope user gatekit" in snippet


class TestRestoreScriptsScopeHandling:
    """Test restore scripts handle mixed scopes correctly."""

    def test_restore_script_posix_mixed_scopes(self):
        """POSIX restore script should use correct scope for each server."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="user-server",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    name="project-server",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    scope=ServerScope.PROJECT,
                ),
            ],
        )

        script = _generate_claude_code_restore_posix(client)

        # Each server should have its own scope in add commands (no removal needed)
        assert "claude mcp add --transport stdio --scope user user-server" in script
        assert "claude mcp add --transport stdio --scope project project-server" in script

        # Should NOT remove original servers (only Gatekit)
        assert script.count("claude mcp remove") == 1
        assert "claude mcp remove user-server" not in script
        assert "claude mcp remove project-server" not in script

        # Gatekit always uses user scope
        assert "claude mcp remove gatekit --scope user" in script

    def test_restore_script_windows_mixed_scopes(self):
        """Windows restore script should use correct scope for each server."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="user-server",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    name="project-server",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    scope=ServerScope.PROJECT,
                ),
            ],
        )

        script = _generate_claude_code_restore_windows(client)

        # Each server should have its own scope in add commands (no removal needed)
        assert "claude mcp add --transport stdio --scope user user-server" in script
        assert "claude mcp add --transport stdio --scope project project-server" in script

        # Should NOT remove original servers (only Gatekit)
        assert script.count("claude mcp remove") == 1
        assert "claude mcp remove user-server" not in script
        assert "claude mcp remove project-server" not in script

        # Gatekit always uses user scope
        assert "claude mcp remove gatekit --scope user" in script
