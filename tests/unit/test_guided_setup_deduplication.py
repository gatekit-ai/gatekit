"""Unit tests for server deduplication logic (Phase 1 - TDD)."""

from pathlib import Path

from gatekit.tui.guided_setup.models import (
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
    ServerScope,
)
from gatekit.tui.guided_setup.deduplication import deduplicate_servers


class TestServerDeduplication:
    """Test deduplicate_servers function."""

    def test_identical_servers_merge(self):
        """Identical servers across clients should merge into one."""
        # Two clients with identical "filesystem" server
        client1 = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                )
            ],
        )

        client2 = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/home/user/.codex/config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                )
            ],
        )

        result = deduplicate_servers([client1, client2])

        assert len(result) == 1
        assert result[0].server.name == "filesystem"
        assert result[0].is_shared is True
        assert set(result[0].client_names) == {"Claude Desktop", "Codex"}
        assert result[0].was_renamed is False

    def test_name_conflict_resolution(self):
        """Servers with same name but different config should get unique names."""
        # Two clients with different "filesystem" servers
        client1 = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem", "/path1"],
                )
            ],
        )

        client2 = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/home/user/.codex/config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem", "/path2"],
                )
            ],
        )

        result = deduplicate_servers([client1, client2])

        assert len(result) == 2

        # Both should have unique names
        names = {r.server.name for r in result}
        assert len(names) == 2  # Both unique
        assert all(r.was_renamed for r in result)
        assert all(r.original_name == "filesystem" for r in result)

        # Names should be different from each other
        assert names != {"filesystem"}

    def test_client_name_deduplication(self):
        """Multiple servers from same client should not duplicate client name."""
        # Desktop client with two different servers
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                ),
                DetectedServer(
                    name="git",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-git"],
                ),
            ],
        )

        result = deduplicate_servers([client])

        assert len(result) == 2
        for r in result:
            assert r.client_names == ["Claude Desktop"]
            assert r.is_shared is False

    def test_complete_deduplication_key(self):
        """Deduplication should use complete key (name, transport, command, url, env, scope)."""
        # Same name, same command, different env vars -> should NOT merge
        client1 = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            servers=[
                DetectedServer(
                    name="api-server",
                    transport=TransportType.STDIO,
                    command=["node", "server.js"],
                    env={"API_KEY": "key1"},
                )
            ],
        )

        client2 = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/home/user/.codex/config.json"),
            servers=[
                DetectedServer(
                    name="api-server",
                    transport=TransportType.STDIO,
                    command=["node", "server.js"],
                    env={"API_KEY": "key2"},
                )
            ],
        )

        result = deduplicate_servers([client1, client2])

        # Different env vars -> different servers -> should be 2
        assert len(result) == 2
        assert all(r.was_renamed for r in result)

    def test_scope_in_deduplication_key(self):
        """Scope should be part of deduplication key (for Claude Code)."""
        # Same server, different scopes -> should NOT merge
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                    scope=ServerScope.USER,
                ),
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                    scope=ServerScope.PROJECT,
                ),
            ],
        )

        result = deduplicate_servers([client])

        # Different scopes -> different servers
        assert len(result) == 2
        assert all(r.was_renamed for r in result)

        # With symmetric progressive naming, both get client name, then scope added for differentiation
        names = {r.server.name for r in result}
        assert "filesystem-Claude-Code" in names
        assert "filesystem-Claude-Code-project" in names

    def test_empty_input(self):
        """Empty client list should return empty result."""
        result = deduplicate_servers([])
        assert result == []

    def test_no_servers(self):
        """Clients with no servers should return empty result."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            servers=[],
        )

        result = deduplicate_servers([client])
        assert result == []

    def test_unique_name_generation_deterministic(self):
        """Unique names should be deterministic based on config path."""
        # Same conflict scenario run twice should produce same names
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.claude/config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "filesystem", "/path1"],
                    )
                ],
            ),
            DetectedClient(
                client_type=ClientType.CODEX,
                config_path=Path("/home/user/.codex/config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "filesystem", "/path2"],
                    )
                ],
            ),
        ]

        result1 = deduplicate_servers(clients)
        result2 = deduplicate_servers(clients)

        # Should produce same names
        names1 = {r.server.name for r in result1}
        names2 = {r.server.name for r in result2}
        assert names1 == names2

    def test_multi_way_conflict(self):
        """Three servers with same name should all get unique names."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.claude/config.json"),
                servers=[
                    DetectedServer(
                        name="server",
                        transport=TransportType.STDIO,
                        command=["a"],
                    )
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="server",
                        transport=TransportType.STDIO,
                        command=["b"],
                    )
                ],
            ),
            DetectedClient(
                client_type=ClientType.CODEX,
                config_path=Path("/home/user/.codex/config.json"),
                servers=[
                    DetectedServer(
                        name="server",
                        transport=TransportType.STDIO,
                        command=["c"],
                    )
                ],
            ),
        ]

        result = deduplicate_servers(clients)

        assert len(result) == 3
        names = {r.server.name for r in result}
        assert len(names) == 3  # All unique
        assert all(r.was_renamed for r in result)
