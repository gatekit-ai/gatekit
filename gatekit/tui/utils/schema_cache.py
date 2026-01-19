"""Cached schema validator singleton.

Re-exports from the shared json_schema module for backward compatibility.
"""

from gatekit.config.json_schema import get_schema_validator, clear_validator_cache

__all__ = ["get_schema_validator", "clear_validator_cache"]
