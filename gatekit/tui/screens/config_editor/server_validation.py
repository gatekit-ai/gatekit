"""Server name validation and sanitization helpers."""

import re
from typing import Optional


class ServerValidationMixin:
    """Mixin providing server name validation and sanitization."""

    def _generate_new_server_name(self) -> str:
        """Generate a unique placeholder name for a new server."""
        base_name = "new-mcp-server"
        existing_names = {u.name for u in self.config.upstreams}
        suffix = 1
        while True:
            candidate = f"{base_name}-{suffix}"
            if candidate not in existing_names:
                return candidate
            suffix += 1

    def _validate_server_name(
        self, name: str, current_name: Optional[str] = None
    ) -> Optional[str]:
        """Validate a prospective server alias and return an error message if invalid."""
        trimmed = name.strip()
        if not trimmed:
            return "Server alias is required."

        if trimmed.lower() == "_global":
            return "Server alias '_global' is reserved."

        if trimmed.startswith("_"):
            return "Server aliases cannot start with an underscore."

        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$", trimmed):
            return (
                "Server alias must start with a letter or number and can only include letters, "
                "numbers, dashes, or underscores (max 48 characters)."
            )

        lower_trimmed = trimmed.lower()
        for upstream in self.config.upstreams:
            if upstream.name == current_name:
                continue
            if upstream.name.lower() == lower_trimmed:
                return f"Server '{trimmed}' already exists."

        return None

    def _rename_server_references(self, old_name: str, new_name: str) -> None:
        """Update plugin mappings and caches when a server is renamed."""
        if self.config.plugins:
            for plugin_type in ("security", "middleware", "auditing"):
                plugin_mapping = getattr(self.config.plugins, plugin_type, None)
                if isinstance(plugin_mapping, dict) and old_name in plugin_mapping:
                    plugin_mapping[new_name] = plugin_mapping.pop(old_name)

        if hasattr(self, "_override_stash"):
            updated: dict[tuple[str, str, str], dict] = {}
            for key, value in self._override_stash.items():
                server_name, plugin_type, handler_name = key
                if server_name == old_name:
                    updated[(new_name, plugin_type, handler_name)] = value
                else:
                    updated[(server_name, plugin_type, handler_name)] = value
            self._override_stash = updated

        if hasattr(self, "server_identity_map"):
            if old_name in self.server_identity_map:
                self.server_identity_map[new_name] = self.server_identity_map.pop(old_name)

        if hasattr(self, "_identity_test_status"):
            if old_name in self._identity_test_status:
                self._identity_test_status[new_name] = self._identity_test_status.pop(
                    old_name
                )

        if hasattr(self, "_pending_connection_cache"):
            if old_name in self._pending_connection_cache:
                self._pending_connection_cache[new_name] = self._pending_connection_cache.pop(
                    old_name
                )

        if hasattr(self, "server_tool_map"):
            if old_name in self.server_tool_map:
                self.server_tool_map[new_name] = self.server_tool_map.pop(old_name)

    def _is_placeholder_name(self, name: str) -> bool:
        """Check if a server name matches the auto-generated placeholder pattern."""
        return bool(re.match(r'^new-mcp-server-\d+$', name))

    def _sanitize_identity_for_alias(self, identity: str) -> str:
        """Convert server identity into a valid server alias.

        Handles path-like identities, removes common prefixes, replaces invalid
        characters, and ensures the result is a valid alias format.
        Note: Does NOT check for uniqueness - that's handled by _validate_server_name().
        """
        # Extract last component if path-like (@scope/package -> package)
        if '/' in identity:
            identity = identity.split('/')[-1]

        # Remove common prefixes
        for prefix in ['server-', 'mcp-', '@']:
            if identity.startswith(prefix):
                identity = identity[len(prefix):]
                break  # Only remove one prefix

        # Replace invalid chars with dash
        sanitized = re.sub(r'[^A-Za-z0-9_-]', '-', identity)

        # Strip leading invalid chars (must start with letter/number)
        sanitized = re.sub(r'^[^A-Za-z0-9]+', '', sanitized)

        # Truncate to 48 chars
        sanitized = sanitized[:48]

        # Ensure not empty
        return sanitized or "mcp-server"
