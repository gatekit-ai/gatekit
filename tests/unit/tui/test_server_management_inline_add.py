"""Tests for inline server creation helpers in ServerManagementMixin."""

from types import SimpleNamespace

import pytest

from gatekit.config.models import UpstreamConfig
from gatekit.tui.screens.config_editor.server_management import ServerManagementMixin


class DummyServerManager(ServerManagementMixin):
    """Minimal concrete object to exercise ServerManagementMixin helpers."""

    def __init__(self, upstreams, plugins=None):
        self.config = SimpleNamespace(upstreams=upstreams, plugins=plugins)
        self.app = SimpleNamespace(notify=lambda *args, **kwargs: None)
        self.selected_server = None
        self._override_stash = {}

    # The mixin expects query_one but the helpers tested here do not invoke it.


def make_upstream(name: str) -> UpstreamConfig:
    """Create a simple upstream with a placeholder command."""
    return UpstreamConfig(name=name, command=["python", "-m", "server"])


class TestGenerateNewServerName:
    """Tests for automatic placeholder name generation."""

    def test_increments_suffix_until_name_is_unique(self):
        upstreams = [
            make_upstream("new-mcp-server-1"),
            make_upstream("filesystem"),
            make_upstream("new-mcp-server-2"),
        ]
        manager = DummyServerManager(upstreams)

        assert manager._generate_new_server_name() == "new-mcp-server-3"


class TestValidateServerName:
    """Tests for inline server alias validation mirrors legacy modal rules."""

    @pytest.fixture
    def manager(self):
        upstreams = [
            make_upstream("filesystem"),
            make_upstream("github"),
            make_upstream("sqlite"),
        ]
        return DummyServerManager(upstreams)

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("", "Server alias is required."),
            ("_global", "Server alias '_global' is reserved."),
            ("_leading", "Server aliases cannot start with an underscore."),
            ("my server", "Server alias must start"),
            ("my@server", "Server alias must start"),
            ("-server", "Server alias must start"),
            (".server", "Server alias must start"),
            ("a" * 49, "max 48"),
            ("filesystem", "already exists"),
            ("FileSystem", "already exists"),
        ],
    )
    def test_rejects_invalid_names(self, manager, name, expected):
        error = manager._validate_server_name(name)
        assert error is not None
        assert expected in error

    @pytest.mark.parametrize(
        "name",
        [
            "newserver",
            "server123",
            "my-server",
            "my_server",
            "123server",
            "a" * 48,
        ],
    )
    def test_accepts_valid_names(self, manager, name):
        assert manager._validate_server_name(name) is None

    def test_allows_retaining_existing_name(self, manager):
        assert (
            manager._validate_server_name("filesystem", current_name="filesystem")
            is None
        )


class TestRenameServerReferences:
    """Tests for cascading updates when a server is renamed."""

    def test_updates_plugin_mappings_and_override_stash(self):
        upstream = make_upstream("old-name")
        plugins = SimpleNamespace(
            security={"old-name": ["sec"]},
            middleware={"old-name": ["mid"]},
            auditing={},
        )
        manager = DummyServerManager([upstream], plugins=plugins)
        manager._override_stash = {("old-name", "security", "handler"): {"config": {}}}

        manager._rename_server_references("old-name", "new-name")

        assert "new-name" in manager.config.plugins.security
        assert "old-name" not in manager.config.plugins.security
        assert ("new-name", "security", "handler") in manager._override_stash
        assert ("old-name", "security", "handler") not in manager._override_stash

        # Ensure unrelated mappings remain untouched
        assert manager.config.plugins.middleware["new-name"] == ["mid"]


class TestSanitizeIdentityForAlias:
    """Tests for converting server identity into valid alias."""

    @pytest.fixture
    def manager(self):
        return DummyServerManager([])

    @pytest.mark.parametrize(
        "identity,expected",
        [
            # Path-like identities - extract last component
            ("@modelcontextprotocol/server-filesystem", "filesystem"),
            ("@scope/package-name", "package-name"),
            ("org/repo/server", "server"),
            # Common prefixes removed
            ("server-filesystem", "filesystem"),
            ("mcp-github", "github"),
            ("@standalone", "standalone"),
            # Invalid characters replaced with dash
            ("my@server#name", "my-server-name"),
            ("server.with.dots", "server-with-dots"),
            ("server:name", "server-name"),
            # Leading invalid chars stripped
            ("@#$filesystem", "filesystem"),
            ("___server", "server"),
            # Length truncation
            ("a" * 60, "a" * 48),
            # Already valid names pass through
            ("filesystem", "filesystem"),
            ("my-server", "my-server"),
            ("server_123", "server_123"),
            # Edge cases
            ("", "mcp-server"),
            ("@@@", "mcp-server"),
            ("---", "mcp-server"),
        ],
    )
    def test_sanitizes_various_identities(self, manager, identity, expected):
        result = manager._sanitize_identity_for_alias(identity)
        assert result == expected
        # Ensure result is valid
        assert manager._validate_server_name(result) is None


class TestIsPlaceholderName:
    """Tests for detecting if a server name is a placeholder."""

    @pytest.fixture
    def manager(self):
        return DummyServerManager([])

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("new-mcp-server-1", True),
            ("new-mcp-server-2", True),
            ("new-mcp-server-999", True),
            ("new-mcp-server-0", True),
            # Not placeholders
            ("new-mcp-server", False),
            ("new-mcp-server-", False),
            ("new-mcp-server-1a", False),
            ("new-mcp-server-a1", False),
            ("filesystem", False),
            ("my-server-1", False),
            ("new-mcp-server-1-modified", False),
            ("", False),
        ],
    )
    def test_detects_placeholder_pattern(self, manager, name, expected):
        assert manager._is_placeholder_name(name) == expected


# TestEnsureUniqueName removed - uniqueness validation is tested via
# _validate_server_name() and _commit_server_name() integration tests
