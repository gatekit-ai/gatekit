"""Server deduplication with conflict resolution."""

import hashlib
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .models import ClientType, DetectedClient, DetectedServer, DeduplicatedServer


def _get_client_display_name(client_type: str) -> str:
    """Get full display name for client type.

    Args:
        client_type: ClientType enum value (e.g., 'claude_desktop')

    Returns:
        Full display name (e.g., 'Claude Desktop')
    """
    try:
        return ClientType(client_type).display_name()
    except ValueError:
        # Fallback for unknown client types
        return client_type.replace("_", " ").title()


def _generate_unique_name(
    server: DetectedServer,
    client_type: str,
    config_path: Path,
    used_names: Set[str],
    base_name: str,
) -> str:
    """Generate unique name for conflicting server.

    Strategy: progressively add qualifiers only as needed:
    1. Try base name alone (only if not already in conflict)
    2. Try base-name + client-display-name
    3. Try base-name + client-display-name + scope
    4. Try base-name + client-display-name + scope + hash
    5. Add numeric suffix if still needed

    Args:
        server: Server being renamed
        client_type: Client type string
        config_path: Path to client config file
        used_names: Already-used names
        base_name: Original server name

    Returns:
        Unique server name
    """
    # Try progressively more specific names
    candidates = []

    # 1. Just the base name (only useful if not in conflict)
    candidates.append(base_name)

    # 2. Add full client display name (with hyphens for valid naming)
    client_display = _get_client_display_name(client_type)
    client_suffix = client_display.replace(" ", "-")
    candidates.append(f"{base_name}-{client_suffix}")

    # 3. Add scope if available
    if server.scope:
        candidates.append(f"{base_name}-{client_suffix}-{server.scope.value}")

    # 4. Add config path hash for ultimate disambiguation
    path_hash = hashlib.sha256(str(config_path).encode()).hexdigest()[:6]
    if server.scope:
        candidates.append(f"{base_name}-{client_suffix}-{server.scope.value}-{path_hash}")
    else:
        candidates.append(f"{base_name}-{client_suffix}-{path_hash}")

    # Find first available name
    for candidate in candidates:
        if candidate not in used_names:
            return candidate

    # If all candidates taken, add numeric suffix to last one
    candidate = candidates[-1]
    counter = 1
    while f"{candidate}-{counter}" in used_names:
        counter += 1

    return f"{candidate}-{counter}"


def deduplicate_servers(
    detected_clients: List[DetectedClient],
) -> List[DeduplicatedServer]:
    """Deduplicate servers across all clients.

    Process:
    1. Collect all servers with (server, client_type, config_path) tuples
    2. Group by complete key: (name, transport, command, url, env, scope)
    3. Deduplicate client names within each group
    4. Identify name conflicts (same name, different config)
    5. Resolve conflicts with unique naming
    6. Return flat list with metadata

    Args:
        detected_clients: All detected clients

    Returns:
        Deduplicated servers with provenance metadata
    """
    # Collect all servers
    all_servers: List[Tuple[DetectedServer, str, Path]] = []
    for client in detected_clients:
        for server in client.servers:
            all_servers.append((server, client.client_type.value, client.config_path))

    # Group identical servers
    server_groups: Dict[Tuple, Dict] = {}
    for server, client_name, config_path in all_servers:
        # COMPLETE deduplication key
        key = (
            server.name,
            server.transport,
            tuple(server.command) if server.command else None,
            server.url,
            frozenset(server.env.items()) if server.env else frozenset(),
            server.scope,
        )

        if key not in server_groups:
            server_groups[key] = {
                "server": server,
                "clients": [],
                "client_types": [],  # Track original client types for renaming
                "config_paths": [],
            }

        # Map client_type value to display name
        client_display_name = _get_client_display_name(client_name)

        server_groups[key]["clients"].append(client_display_name)
        server_groups[key]["client_types"].append(client_name)  # Store original type
        server_groups[key]["config_paths"].append(config_path)

    # Deduplicate client lists (both display names and types)
    for group in server_groups.values():
        # Preserve order while deduplicating display names
        seen = set()
        deduplicated_clients = []
        deduplicated_types = []
        for client, client_type in zip(group["clients"], group["client_types"], strict=True):
            if client not in seen:
                seen.add(client)
                deduplicated_clients.append(client)
                deduplicated_types.append(client_type)
        group["clients"] = deduplicated_clients
        group["client_types"] = deduplicated_types

    # Find name conflicts
    name_to_groups: Dict[str, List[Tuple]] = {}
    for key, group in server_groups.items():
        name = key[0]  # First element is server name
        if name not in name_to_groups:
            name_to_groups[name] = []
        name_to_groups[name].append((key, group))

    conflicts = {
        name: groups for name, groups in name_to_groups.items() if len(groups) > 1
    }

    # Build result with unique names
    result: List[DeduplicatedServer] = []
    used_names: Set[str] = set()

    # First, add all non-conflicting names to used_names
    for group in server_groups.values():
        if group["server"].name not in conflicts:
            used_names.add(group["server"].name)

    # Mark all conflicting base names as used to ensure symmetric naming
    # (prevents first server in conflict from claiming the base name)
    for conflict_name in conflicts.keys():
        used_names.add(conflict_name)

    # Process each conflict group and rename progressively
    for conflict_name, conflict_groups in conflicts.items():
        for _key, group in conflict_groups:
            server = group["server"]
            client_types = group["client_types"]
            config_paths = group["config_paths"]

            new_name = _generate_unique_name(
                server, client_types[0], config_paths[0], used_names, conflict_name
            )

            # Store renamed server back in group
            group["renamed_server"] = DetectedServer(
                name=new_name,
                transport=server.transport,
                command=server.command,
                url=server.url,
                env=server.env,
                scope=server.scope,
                project_path=server.project_path,
                raw_config=server.raw_config,
            )
            group["was_renamed"] = True
            group["original_name"] = conflict_name

            used_names.add(new_name)

    # Build final result list
    for group in server_groups.values():
        server = group.get("renamed_server", group["server"])
        was_renamed = group.get("was_renamed", False)
        original_name = group.get("original_name")

        result.append(
            DeduplicatedServer(
                server=server,
                client_names=group["clients"],
                is_shared=len(group["clients"]) > 1,
                was_renamed=was_renamed,
                original_name=original_name,
            )
        )

    return result
