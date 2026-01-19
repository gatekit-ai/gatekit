"""Tests for migration instructions preservation in state."""

from pathlib import Path

from gatekit.tui.guided_setup.models import (
    GuidedSetupState,
    DetectedClient,
    DetectedServer,
    ClientType,
    TransportType,
)
from gatekit.tui.guided_setup.migration_instructions import (
    MigrationInstructions,
    generate_migration_instructions,
)


def test_state_has_migration_instructions_field():
    """GuidedSetupState should have migration_instructions field."""
    state = GuidedSetupState()
    assert hasattr(state, "migration_instructions")
    assert state.migration_instructions == []


def test_state_can_store_migration_instructions():
    """GuidedSetupState should be able to store MigrationInstructions objects."""
    state = GuidedSetupState()

    # Create a test instruction
    test_instruction = MigrationInstructions(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=Path("/test/config.json"),
        servers_to_migrate=["server1"],
        migration_snippet="test snippet",
        instruction_text="test instructions",
    )

    # Store in state
    state.migration_instructions = [test_instruction]

    # Verify it's stored
    assert len(state.migration_instructions) == 1
    assert state.migration_instructions[0].client_type == ClientType.CLAUDE_DESKTOP
    assert state.migration_instructions[0].servers_to_migrate == ["server1"]


def test_generate_migration_instructions_returns_list():
    """generate_migration_instructions should return a list that can be stored in state."""
    # Create test client with a server
    client = DetectedClient(
        client_type=ClientType.CLAUDE_DESKTOP,
        config_path=Path("/test/config.json"),
        servers=[
            DetectedServer(
                name="test-server",
                transport=TransportType.STDIO,
                command=["test", "command"],
            )
        ],
    )

    # Generate instructions
    instructions = generate_migration_instructions(
        detected_clients=[client],
        selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
        gatekit_gateway_path=Path("/usr/local/bin/gatekit-gateway"),
        gatekit_config_path=Path("/test/gatekit.yaml"),
    )

    # Verify it's a list that can be stored
    assert isinstance(instructions, list)
    assert len(instructions) == 1
    assert isinstance(instructions[0], MigrationInstructions)

    # Verify it can be stored in state
    state = GuidedSetupState()
    state.migration_instructions = instructions
    assert state.migration_instructions == instructions


def test_state_migration_instructions_flows_through_screens():
    """Migration instructions set in state should be accessible to subsequent screens."""
    # Simulate the flow:
    # 1. SetupActionsScreen generates and stores instructions
    state = GuidedSetupState()
    state.config_path = Path("/test/gatekit.yaml")

    # Generate test instructions
    client = DetectedClient(
        client_type=ClientType.CLAUDE_CODE,
        config_path=Path("/test/config.json"),
        servers=[
            DetectedServer(
                name="test-server",
                transport=TransportType.STDIO,
                command=["test", "command"],
            )
        ],
    )

    instructions = generate_migration_instructions(
        detected_clients=[client],
        selected_server_names={s.name for c in [client] for s in c.get_stdio_servers()},
        gatekit_gateway_path=Path("/usr/local/bin/gatekit-gateway"),
        gatekit_config_path=state.config_path,
    )

    # Store in state (simulating SetupActionsScreen)
    state.migration_instructions = instructions

    # 2. SetupCompleteScreen should receive the same instructions via state
    assert len(state.migration_instructions) == 1
    assert state.migration_instructions[0].client_type == ClientType.CLAUDE_CODE

    # 3. Verify the instructions are complete and usable
    instr = state.migration_instructions[0]
    assert instr.migration_snippet  # Should have content
    assert instr.instruction_text  # Should have content
    assert instr.servers_to_migrate == ["test-server"]
