"""Tests for migration instruction generation with complete mcpServers section.

These tests verify that Claude Desktop migration instructions include the
complete mcpServers wrapper instead of just the gatekit entry.
"""

import json
from pathlib import Path

from gatekit.tui.guided_setup.models import (
    DetectedClient,
    DetectedServer,
    ClientType,
    TransportType,
)
from gatekit.tui.guided_setup.migration_instructions import (
    generate_migration_instructions,
)


class TestClaudeDesktopCompleteMcpServersSection:
    """Test that Claude Desktop snippets include complete mcpServers wrapper."""

    def test_snippet_includes_mcp_servers_wrapper(self):
        """Claude Desktop snippet should include mcpServers wrapper."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/Claude/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "mcp-server-filesystem"],
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/usr/local/bin/gatekit-gateway"),
            gatekit_config_path=Path("/home/user/gatekit/gatekit.yaml"),
        )

        assert len(instructions) == 1
        instr = instructions[0]

        # Parse the snippet
        snippet_data = json.loads(instr.migration_snippet)

        # Should have mcpServers at top level
        assert "mcpServers" in snippet_data
        assert isinstance(snippet_data["mcpServers"], dict)

        # Gatekit should be inside mcpServers
        assert "gatekit" in snippet_data["mcpServers"]
        assert "command" in snippet_data["mcpServers"]["gatekit"]
        assert "args" in snippet_data["mcpServers"]["gatekit"]

    def test_snippet_does_not_have_top_level_gatekit(self):
        """Snippet should not have gatekit as a top-level key."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[
                DetectedServer(
                    name="test-server",
                    transport=TransportType.STDIO,
                    command=["test"],
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/bin/gatekit-gateway"),
            gatekit_config_path=Path("/test/gatekit.yaml"),
        )

        snippet_data = json.loads(instructions[0].migration_snippet)

        # gatekit should NOT be at top level
        assert "gatekit" not in snippet_data
        # It should be inside mcpServers
        assert "gatekit" in snippet_data["mcpServers"]

    def test_instruction_text_says_replace_entire_file(self):
        """Instruction text should say 'Replace your entire config file'."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[
                DetectedServer(
                    name="test-server",
                    transport=TransportType.STDIO,
                    command=["test"],
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/bin/gatekit-gateway"),
            gatekit_config_path=Path("/test/gatekit.yaml"),
        )

        instr = instructions[0]

        # Should NOT say "Add this to your mcpServers section"
        assert "Add this to your mcpServers section" not in instr.instruction_text

        # Should say "Replace your entire config file"
        assert "Replace your entire config file" in instr.instruction_text

    def test_snippet_with_env_vars_includes_them_in_gatekit(self):
        """Snippet should include env vars in gatekit entry."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[
                DetectedServer(
                    name="test-server",
                    transport=TransportType.STDIO,
                    command=["test"],
                    env={"API_KEY": "test-key", "DEBUG": "true"},
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/bin/gatekit-gateway"),
            gatekit_config_path=Path("/test/gatekit.yaml"),
        )

        snippet_data = json.loads(instructions[0].migration_snippet)

        # Env vars should be in the gatekit entry
        assert "env" in snippet_data["mcpServers"]["gatekit"]
        assert snippet_data["mcpServers"]["gatekit"]["env"]["API_KEY"] == "test-key"
        assert snippet_data["mcpServers"]["gatekit"]["env"]["DEBUG"] == "true"

    def test_snippet_without_env_vars_has_no_env_field(self):
        """Snippet should not include env field if no env vars."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/test/config.json"),
            servers=[
                DetectedServer(
                    name="test-server",
                    transport=TransportType.STDIO,
                    command=["test"],
                    env=None,  # No env vars
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/bin/gatekit-gateway"),
            gatekit_config_path=Path("/test/gatekit.yaml"),
        )

        snippet_data = json.loads(instructions[0].migration_snippet)

        # Should not have env field
        assert "env" not in snippet_data["mcpServers"]["gatekit"]


class TestCLIClientsDoNotHaveMcpServersWrapper:
    """Test that CLI clients (Claude Code, Codex) do not get mcpServers wrapper."""

    def test_claude_code_snippet_is_bash_commands(self):
        """Claude Code snippet should be bash commands, not JSON."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/test/.claude.json"),
            servers=[
                DetectedServer(
                    name="test-server",
                    transport=TransportType.STDIO,
                    command=["test"],
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/bin/gatekit-gateway"),
            gatekit_config_path=Path("/test/gatekit.yaml"),
        )

        snippet = instructions[0].migration_snippet

        # Should contain CLI commands, not JSON
        assert "claude mcp" in snippet
        assert "{" not in snippet  # No JSON braces
        assert "mcpServers" not in snippet

    def test_codex_snippet_is_bash_commands(self):
        """Codex snippet should be bash commands, not JSON."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/test/.codex.json"),
            servers=[
                DetectedServer(
                    name="test-server",
                    transport=TransportType.STDIO,
                    command=["test"],
                )
            ],
        )

        instructions = generate_migration_instructions(
            detected_clients=[client],
            selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
            gatekit_gateway_path=Path("/bin/gatekit-gateway"),
            gatekit_config_path=Path("/test/gatekit.yaml"),
        )

        snippet = instructions[0].migration_snippet

        # Should contain CLI commands, not JSON
        assert "codex mcp" in snippet
        assert "{" not in snippet  # No JSON braces
        assert "mcpServers" not in snippet
