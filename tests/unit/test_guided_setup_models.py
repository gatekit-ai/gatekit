"""Unit tests for guided setup data models (Phase 0 - TDD)."""

from dataclasses import replace
from pathlib import Path

from gatekit.tui.guided_setup.models import (
    NavigationAction,
    ScreenResult,
    DeduplicatedServer,
    GuidedSetupState,
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
    ServerScope,
)


class TestNavigationAction:
    """Test NavigationAction enum."""

    def test_navigation_action_values(self):
        """NavigationAction should have CONTINUE, BACK, and CANCEL."""
        assert NavigationAction.CONTINUE.value == "continue"
        assert NavigationAction.BACK.value == "back"
        assert NavigationAction.CANCEL.value == "cancel"


class TestScreenResult:
    """Test ScreenResult dataclass."""

    def test_screen_result_with_state(self):
        """ScreenResult should hold action and optional state."""
        state = GuidedSetupState()
        result = ScreenResult(action=NavigationAction.CONTINUE, state=state)

        assert result.action == NavigationAction.CONTINUE
        assert result.state is state

    def test_screen_result_without_state(self):
        """ScreenResult should allow None state (for CANCEL)."""
        result = ScreenResult(action=NavigationAction.CANCEL, state=None)

        assert result.action == NavigationAction.CANCEL
        assert result.state is None


class TestDeduplicatedServer:
    """Test DeduplicatedServer dataclass."""

    def test_deduplicated_server_shared(self):
        """DeduplicatedServer should track shared servers."""
        server = DetectedServer(
            name="test-server",
            transport=TransportType.STDIO,
            command=["npx", "test-server"]
        )

        dedupe = DeduplicatedServer(
            server=server,
            client_names=["Claude Desktop", "Codex"],
            is_shared=True,
            was_renamed=False
        )

        assert dedupe.server == server
        assert dedupe.client_names == ["Claude Desktop", "Codex"]
        assert dedupe.is_shared is True
        assert dedupe.was_renamed is False
        assert dedupe.original_name is None

    def test_deduplicated_server_renamed(self):
        """DeduplicatedServer should track renamed servers."""
        server = DetectedServer(
            name="filesystem-desktop",
            transport=TransportType.STDIO,
            command=["npx", "filesystem"]
        )

        dedupe = DeduplicatedServer(
            server=server,
            client_names=["Claude Desktop"],
            is_shared=False,
            was_renamed=True,
            original_name="filesystem"
        )

        assert dedupe.was_renamed is True
        assert dedupe.original_name == "filesystem"


class TestGuidedSetupState:
    """Test GuidedSetupState dataclass."""

    def test_initial_state(self):
        """GuidedSetupState should initialize with empty collections."""
        state = GuidedSetupState()

        assert state.detected_clients == []
        assert state.deduplicated_servers == []
        assert state.selected_server_names == set()
        assert state.selected_client_types == set()
        assert state.config_path is None
        assert state.restore_dir is None
        assert state.generate_restore is False
        assert state.created_files == []
        assert state.generation_errors == []
        assert state.already_configured_clients == []  # New field for Phase 0

    def test_already_configured_clients_field(self):
        """GuidedSetupState should have already_configured_clients field with default empty list."""
        state = GuidedSetupState()

        # Field exists with default value
        assert hasattr(state, "already_configured_clients")
        assert state.already_configured_clients == []
        assert isinstance(state.already_configured_clients, list)

    def test_already_configured_clients_can_be_set(self):
        """already_configured_clients should accept list of DetectedClient objects."""
        client1 = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            gatekit_config_path="/home/user/gatekit/gatekit.yaml"
        )
        client2 = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            gatekit_config_path="/home/user/gatekit/gatekit.yaml"
        )

        state = GuidedSetupState()
        state.already_configured_clients = [client1, client2]

        assert len(state.already_configured_clients) == 2
        assert state.already_configured_clients[0].client_type == ClientType.CLAUDE_DESKTOP
        assert state.already_configured_clients[1].client_type == ClientType.CLAUDE_CODE

    def test_already_configured_clients_persists_through_state_updates(self):
        """already_configured_clients should persist through state updates."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            gatekit_config_path="/home/user/gatekit/gatekit.yaml"
        )

        state = GuidedSetupState()
        state.already_configured_clients = [client]

        # Simulate state update (like BACK navigation)
        state.config_path = Path("/new/path/gatekit.yaml")

        # Field should still be populated
        assert len(state.already_configured_clients) == 1
        assert state.already_configured_clients[0].client_type == ClientType.CLAUDE_DESKTOP

    def test_already_configured_clients_survives_dataclass_replace(self):
        """already_configured_clients should survive dataclasses.replace() operations."""
        client1 = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            gatekit_config_path="/home/user/gatekit/gatekit.yaml"
        )
        client2 = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            gatekit_config_path="/home/user/gatekit/gatekit.yaml"
        )

        # Create state with already_configured_clients
        original_state = GuidedSetupState()
        original_state.already_configured_clients = [client1, client2]

        # Use dataclasses.replace to create a new state (functional update pattern)
        new_state = replace(original_state, config_path=Path("/new/path/gatekit.yaml"))

        # Verify the list survived the copy
        assert len(new_state.already_configured_clients) == 2
        assert new_state.already_configured_clients[0].client_type == ClientType.CLAUDE_DESKTOP
        assert new_state.already_configured_clients[1].client_type == ClientType.CLAUDE_CODE

        # Verify the list is the same reference (shallow copy behavior)
        assert new_state.already_configured_clients is original_state.already_configured_clients

    def test_already_configured_clients_not_shared_between_instances(self):
        """already_configured_clients should not be shared between different GuidedSetupState instances."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json"),
            gatekit_config_path="/home/user/gatekit/gatekit.yaml"
        )

        # Create two separate state instances
        state1 = GuidedSetupState()
        state2 = GuidedSetupState()

        # Modify one instance's list
        state1.already_configured_clients.append(client)

        # Verify the other instance's list is unaffected (not shared)
        assert len(state1.already_configured_clients) == 1
        assert len(state2.already_configured_clients) == 0
        assert state1.already_configured_clients is not state2.already_configured_clients

    def test_get_selected_servers(self):
        """get_selected_servers should filter by selection."""
        state = GuidedSetupState()

        server_a = DetectedServer(name="server-a", transport=TransportType.STDIO, command=["a"])
        server_b = DetectedServer(name="server-b", transport=TransportType.STDIO, command=["b"])
        server_c = DetectedServer(name="server-c", transport=TransportType.STDIO, command=["c"])

        state.deduplicated_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_b, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_c, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]

        state.selected_server_names = {"server-a", "server-c"}

        selected = state.get_selected_servers()
        assert len(selected) == 2
        assert selected[0].server.name == "server-a"
        assert selected[1].server.name == "server-c"

    def test_get_selected_clients(self):
        """get_selected_clients should filter by selection."""
        state = GuidedSetupState()

        client_desktop = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json")
        )
        client_code = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json")
        )

        state.detected_clients = [client_desktop, client_code]
        state.selected_client_types = {ClientType.CLAUDE_DESKTOP}

        selected = state.get_selected_clients()
        assert len(selected) == 1
        assert selected[0].client_type == ClientType.CLAUDE_DESKTOP


class TestUpdateDeduplicatedServers:
    """Test GuidedSetupState.update_deduplicated_servers() method."""

    def test_preserves_deselections(self):
        """Rescan should preserve user's intentional deselections."""
        state = GuidedSetupState()

        # Initial: A, B, C all auto-selected
        server_a = DetectedServer(name="A", transport=TransportType.STDIO, command=["a"])
        server_b = DetectedServer(name="B", transport=TransportType.STDIO, command=["b"])
        server_c = DetectedServer(name="C", transport=TransportType.STDIO, command=["c"])

        state.deduplicated_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_b, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_c, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]
        state.selected_server_names = {"A", "B", "C"}

        # User deselects B
        state.selected_server_names.remove("B")

        # Rescan finds A, C, D (B is gone, D is new)
        server_d = DetectedServer(name="D", transport=TransportType.STDIO, command=["d"])
        new_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_c, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_d, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]

        state.update_deduplicated_servers(new_servers, [])

        # Result: A, C, D selected (B's deselection preserved as "intentional")
        assert state.selected_server_names == {"A", "C", "D"}

    def test_auto_selects_new_servers(self):
        """Rescan should auto-select newly discovered servers."""
        state = GuidedSetupState()

        server_a = DetectedServer(name="A", transport=TransportType.STDIO, command=["a"])
        state.deduplicated_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]
        state.selected_server_names = {"A"}

        # Rescan finds A and B (B is new)
        server_b = DetectedServer(name="B", transport=TransportType.STDIO, command=["b"])
        new_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_b, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]

        state.update_deduplicated_servers(new_servers, [])

        # Both should be selected
        assert state.selected_server_names == {"A", "B"}

    def test_removes_vanished_servers(self):
        """Rescan should remove selections for servers that no longer exist."""
        state = GuidedSetupState()

        server_a = DetectedServer(name="A", transport=TransportType.STDIO, command=["a"])
        server_b = DetectedServer(name="B", transport=TransportType.STDIO, command=["b"])
        state.deduplicated_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
            DeduplicatedServer(server=server_b, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]
        state.selected_server_names = {"A", "B"}

        # Rescan finds only A
        new_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]

        state.update_deduplicated_servers(new_servers, [])

        # Only A should remain selected
        assert state.selected_server_names == {"A"}

    def test_client_reconciliation(self):
        """Rescan should reconcile client selections similarly to servers."""
        state = GuidedSetupState()

        client_desktop = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.claude/config.json")
        )
        state.detected_clients = [client_desktop]
        state.selected_client_types = {ClientType.CLAUDE_DESKTOP}

        # User deselects desktop
        state.selected_client_types.remove(ClientType.CLAUDE_DESKTOP)

        # Rescan finds desktop + code
        client_code = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json")
        )

        state.update_deduplicated_servers([], [client_desktop, client_code])

        # Code should be auto-selected, desktop stays deselected
        assert state.selected_client_types == {ClientType.CLAUDE_CODE}

    def test_empty_rescan(self):
        """Rescan with no results should clear all selections."""
        state = GuidedSetupState()

        server_a = DetectedServer(name="A", transport=TransportType.STDIO, command=["a"])
        state.deduplicated_servers = [
            DeduplicatedServer(server=server_a, client_names=["Desktop"], is_shared=False, was_renamed=False),
        ]
        state.selected_server_names = {"A"}

        # Rescan finds nothing
        state.update_deduplicated_servers([], [])

        assert state.selected_server_names == set()
        assert state.deduplicated_servers == []

    def test_preserves_original_name_through_rescan(self):
        """Rescan should preserve original_name for renamed servers."""
        state = GuidedSetupState()

        # Initial state: Server was renamed during deduplication
        # Original name: "context7" -> Deduped name: "context7-Codex"
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.mcp.json"),
            servers=[
                DetectedServer(
                    name="context7-Codex",  # Deduped name after mutation
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                    original_name="context7",  # Original name set during first mutation
                )
            ],
        )

        server = client.servers[0]
        state.deduplicated_servers = [
            DeduplicatedServer(
                server=server,
                client_names=["Claude Code"],
                is_shared=False,
                was_renamed=True,
                original_name="context7",
            ),
        ]
        state.detected_clients = [client]
        state.selected_server_names = {"context7-Codex"}

        # Rescan with the same renamed server
        # Simulate what deduplication.py produces on rescan
        new_servers = [
            DeduplicatedServer(
                server=DetectedServer(
                    name="context7-Codex",  # Still the deduped name
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                ),
                client_names=["Claude Code"],
                is_shared=False,
                was_renamed=True,
                original_name="context7",
            ),
        ]

        # New client with original name (simulating fresh detection from config file)
        new_client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.mcp.json"),
            servers=[
                DetectedServer(
                    name="context7",  # Fresh from config, not yet mutated
                    transport=TransportType.STDIO,
                    command=["npx", "context7"],
                )
            ],
        )

        # Update should mutate the server name BUT preserve original_name
        state.update_deduplicated_servers(new_servers, [new_client])

        # Verify the server in detected_clients has been renamed but preserves original_name
        updated_server = state.detected_clients[0].servers[0]
        assert updated_server.name == "context7-Codex"  # Mutated to deduped name
        assert updated_server.original_name == "context7"  # Original name preserved

        # Verify selections still work with deduped name
        assert state.selected_server_names == {"context7-Codex"}

    def test_handles_same_original_name_different_configs(self):
        """When multiple servers have same original name but different configs, map each correctly."""
        state = GuidedSetupState()

        # Two different servers, both originally named "context7"
        # One from Codex (without api-key), one from Claude Code (with api-key)
        clients = [
            DetectedClient(
                client_type=ClientType.CODEX,
                config_path=Path("/Users/test/.codex/config.toml"),
                servers=[
                    DetectedServer(
                        name="context7",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@upstash/context7-mcp"],
                    )
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/Users/test/.mcp.json"),
                servers=[
                    DetectedServer(
                        name="context7",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@upstash/context7-mcp", "--api-key", "secret"],
                        scope=ServerScope.PROJECT,
                    )
                ],
            ),
        ]

        # Deduplication should create two renamed servers
        from gatekit.tui.guided_setup.deduplication import deduplicate_servers
        deduped = deduplicate_servers(clients)

        # Should have 2 deduplicated servers with different names
        assert len(deduped) == 2
        server_names = {ds.server.name for ds in deduped}
        assert "context7-Codex" in server_names
        assert "context7-Claude-Code" in server_names

        # Now update state - this is where the bug was
        state.update_deduplicated_servers(deduped, clients)

        # CRITICAL: Each client's server should have the CORRECT deduped name
        # Bug was: both got renamed to the same name (last one in dict)
        codex_server = state.detected_clients[0].servers[0]
        claude_code_server = state.detected_clients[1].servers[0]

        assert codex_server.name == "context7-Codex"
        assert codex_server.original_name == "context7"

        assert claude_code_server.name == "context7-Claude-Code"
        assert claude_code_server.original_name == "context7"

        # Verify they still have different commands
        assert codex_server.command == ["npx", "-y", "@upstash/context7-mcp"]
        assert claude_code_server.command == ["npx", "-y", "@upstash/context7-mcp", "--api-key", "secret"]
