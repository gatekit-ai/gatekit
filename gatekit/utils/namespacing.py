"""Utility functions for handling tool namespacing in Gatekit.

This module provides centralized functions for parsing and formatting namespaced
tool names, ensuring consistent handling across the proxy and plugin system.
"""

from typing import Dict, List, Optional, Tuple


def parse_namespaced_name(name: str) -> Tuple[Optional[str], str]:
    """Parse a potentially namespaced name into server and clean name parts.

    Uses exactly two underscores as the delimiter. Names with three or more
    consecutive underscores are NOT treated as namespaced (some servers like
    AWS use triple underscores in their native tool names).

    Args:
        name: The name to parse (e.g., "filesystem__read_file" or "read_file")

    Returns:
        Tuple of (server_name, clean_name):
        - "filesystem__read_file" → ("filesystem", "read_file")
        - "read_file" → (None, "read_file")
        - "server__nested__name" → ("server", "nested__name")
        - "aws___tool" → (None, "aws___tool")  # Triple underscore - not namespaced
    """
    if "__" not in name:
        return None, name

    # Find the first occurrence of exactly two underscores (not three or more)
    # by looking for "__" that's not preceded or followed by another underscore
    i = 0
    while i < len(name) - 1:
        if name[i:i+2] == "__":
            # Check it's not part of "___" (three or more underscores)
            before_ok = i == 0 or name[i-1] != "_"
            after_ok = i + 2 >= len(name) or name[i+2] != "_"
            if before_ok and after_ok:
                return name[:i], name[i+2:]
        i += 1

    return None, name


def namespace_name(server: str, name: str) -> str:
    """Add server namespace prefix to a clean name.

    Args:
        server: The server name to use as prefix
        name: The clean name to namespace

    Returns:
        The namespaced name: "server__name"
    """
    return f"{server}__{name}"


def namespace_tools_response(server: str, tools: List[Dict]) -> List[Dict]:
    """Add server namespace prefix to all tool names in a tools list.

    Args:
        server: The server name to use as prefix
        tools: List of tool definitions with "name" fields

    Returns:
        New list with namespaced tool names
    """
    namespaced_tools = []
    for tool in tools:
        if isinstance(tool, dict) and "name" in tool:
            namespaced_tool = tool.copy()
            namespaced_tool["name"] = namespace_name(server, tool["name"])
            namespaced_tools.append(namespaced_tool)
        else:
            namespaced_tools.append(tool)
    return namespaced_tools


def namespace_resources_response(server: str, resources: List[Dict]) -> List[Dict]:
    """Add server namespace prefix to all resource URIs in a resources list.

    Args:
        server: The server name to use as prefix
        resources: List of resource definitions with "uri" fields

    Returns:
        New list with namespaced resource URIs
    """
    namespaced_resources = []
    for resource in resources:
        if isinstance(resource, dict) and "uri" in resource:
            namespaced_resource = resource.copy()
            namespaced_resource["uri"] = namespace_name(server, resource["uri"])
            namespaced_resources.append(namespaced_resource)
        else:
            namespaced_resources.append(resource)
    return namespaced_resources


def namespace_prompts_response(server: str, prompts: List[Dict]) -> List[Dict]:
    """Add server namespace prefix to all prompt names in a prompts list.

    Args:
        server: The server name to use as prefix
        prompts: List of prompt definitions with "name" fields

    Returns:
        New list with namespaced prompt names
    """
    namespaced_prompts = []
    for prompt in prompts:
        if isinstance(prompt, dict) and "name" in prompt:
            namespaced_prompt = prompt.copy()
            namespaced_prompt["name"] = namespace_name(server, prompt["name"])
            namespaced_prompts.append(namespaced_prompt)
        else:
            namespaced_prompts.append(prompt)
    return namespaced_prompts


def denamespace_tools_response(tools: List[Dict]) -> Dict[str, List[Dict]]:
    """Group tools by server and return with clean names.

    Args:
        tools: List of tool definitions, potentially with namespaced names

    Returns:
        Dictionary mapping server names to lists of tools with clean names:
        {
            "filesystem": [{"name": "read_file", ...}, {"name": "write_file", ...}],
            "calculator": [{"name": "add", ...}, {"name": "multiply", ...}],
            None: [{"name": "clean_tool", ...}]  # Non-namespaced tools
        }
    """
    tools_by_server = {}

    for tool in tools:
        if not isinstance(tool, dict) or "name" not in tool:
            continue

        tool_name = tool["name"]
        if not isinstance(tool_name, str):
            continue

        server_name, clean_name = parse_namespaced_name(tool_name)

        if server_name not in tools_by_server:
            tools_by_server[server_name] = []

        # Create clean tool for this server
        clean_tool = tool.copy()
        clean_tool["name"] = clean_name
        tools_by_server[server_name].append(clean_tool)

    return tools_by_server


def is_namespaced(name: str) -> bool:
    """Check if a name contains server namespace prefix (exactly two underscores).

    Args:
        name: The name to check

    Returns:
        True if the name contains exactly "__" (not "___"), False otherwise
    """
    if not isinstance(name, str) or "__" not in name:
        return False

    # Check for exactly two underscores (not three or more)
    server, _ = parse_namespaced_name(name)
    return server is not None
