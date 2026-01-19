"""Configuration serialization utilities.

Provides shared logic for converting ProxyConfig to dictionaries suitable
for YAML serialization. Used by config editor, guided setup, and identity
persistence workflows.
"""

from typing import Dict, Any

from .models import ProxyConfig


def config_to_dict(
    config: ProxyConfig,
    validate_drafts: bool = True,
) -> Dict[str, Any]:
    """Convert ProxyConfig to dictionary suitable for YAML serialization.

    Note: Omitted fields rely on implicit defaults defined in ConfigLoader
    (e.g., timeouts default to 60s, restart_on_failure defaults to True, etc.)

    Args:
        config: The ProxyConfig to convert
        validate_drafts: If True, raise ValueError for incomplete servers (default: True)
                        Set to False when serializing configs that may have drafts

    Returns:
        Dictionary representation suitable for YAML

    Raises:
        ValueError: If validate_drafts=True and config contains draft servers
                   or servers missing required fields
    """
    result = {"proxy": {"transport": config.transport}}

    # Add upstreams
    if config.upstreams:
        result["proxy"]["upstreams"] = []
        for upstream in config.upstreams:
            if validate_drafts:
                if getattr(upstream, "is_draft", False):
                    raise ValueError(
                        f"Upstream '{upstream.name}' is incomplete. Fill in the required fields before saving."
                    )

                if upstream.transport == "stdio" and not upstream.command:
                    raise ValueError(
                        f"Upstream '{upstream.name}' is missing a command for stdio transport."
                    )

                if upstream.transport == "http" and not upstream.url:
                    raise ValueError(
                        f"Upstream '{upstream.name}' is missing a URL for http transport."
                    )

            upstream_dict = {"name": upstream.name, "transport": upstream.transport}
            if upstream.command:
                # Write command as full list (ConfigLoader expects this format)
                upstream_dict["command"] = upstream.command
            if upstream.url:
                upstream_dict["url"] = upstream.url
            if not upstream.restart_on_failure:
                upstream_dict["restart_on_failure"] = upstream.restart_on_failure
            if upstream.max_restart_attempts != 3:
                upstream_dict["max_restart_attempts"] = (
                    upstream.max_restart_attempts
                )
            if upstream.server_identity:
                upstream_dict["server_identity"] = upstream.server_identity
            result["proxy"]["upstreams"].append(upstream_dict)

    # Add timeouts if non-default
    if config.timeouts:
        timeouts = {}
        if config.timeouts.connection_timeout != 60:
            timeouts["connection_timeout"] = config.timeouts.connection_timeout
        if config.timeouts.request_timeout != 60:
            timeouts["request_timeout"] = config.timeouts.request_timeout
        if timeouts:
            result["proxy"]["timeouts"] = timeouts

    # Add HTTP config if present
    if config.http:
        result["proxy"]["http"] = {
            "host": config.http.host,
            "port": config.http.port,
        }

    # Add plugins if present (canonical format: top-level)
    if config.plugins:
        plugins_dict = config.plugins.to_dict()
        # Only add non-empty plugin sections
        if (
            plugins_dict.get("security")
            or plugins_dict.get("middleware")
            or plugins_dict.get("auditing")
        ):
            result["plugins"] = {}
            if plugins_dict.get("security"):
                result["plugins"]["security"] = plugins_dict["security"]
            if plugins_dict.get("middleware"):
                result["plugins"]["middleware"] = plugins_dict["middleware"]
            if plugins_dict.get("auditing"):
                result["plugins"]["auditing"] = plugins_dict["auditing"]

    # Add logging if present (canonical format: top-level)
    if config.logging:
        logging_dict = {
            "level": config.logging.level,
            "handlers": config.logging.handlers,
            "max_file_size_mb": config.logging.max_file_size_mb,
            "backup_count": config.logging.backup_count,
            "format": config.logging.format,
            "date_format": config.logging.date_format,
        }
        if config.logging.file_path:
            logging_dict["file_path"] = str(config.logging.file_path)
        result["logging"] = logging_dict

    return result
