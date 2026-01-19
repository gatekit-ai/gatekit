"""Guided Setup for Gatekit TUI - MCP client detection and configuration generation."""

from .models import (
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
    ServerScope,
)
from .gateway import locate_gatekit_gateway
from .detection import detect_all_clients
from .config_generation import (
    ConfigGenerationResult,
    generate_gatekit_config,
    generate_yaml_config,
)
from .restore_scripts import generate_restore_scripts
from .migration_instructions import (
    MigrationInstructions,
    generate_migration_instructions,
)
from .error_handling import (
    DetectionResult,
    EditorOpener,
    get_no_clients_message,
    format_parse_error_message,
)
from .client_registry import get_supported_client_names

__all__ = [
    "DetectedServer",
    "DetectedClient",
    "ClientType",
    "TransportType",
    "ServerScope",
    "locate_gatekit_gateway",
    "detect_all_clients",
    "ConfigGenerationResult",
    "generate_gatekit_config",
    "generate_yaml_config",
    "generate_restore_scripts",
    "MigrationInstructions",
    "generate_migration_instructions",
    "DetectionResult",
    "EditorOpener",
    "get_no_clients_message",
    "get_supported_client_names",
    "format_parse_error_message",
]
