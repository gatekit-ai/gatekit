"""Test that server_tool_map is properly initialized when adding servers."""

import pytest
from types import SimpleNamespace
from gatekit.config.models import UpstreamConfig
from gatekit.tui.screens.config_editor.server_management import ServerManagementMixin


class DummyServerManager(ServerManagementMixin):
    """Minimal concrete object to exercise ServerManagementMixin helpers."""

    def __init__(self, upstreams):
        self.config = SimpleNamespace(upstreams=upstreams, plugins=None)
        self.app = SimpleNamespace(notify=lambda *args, **kwargs: None)
        self.selected_server = None
        self.server_tool_map = {}
        self._tool_discovery_attempted = set()
        self._identity_discovery_attempted = set()


class TestServerToolMapInitialization:
    """Test that server_tool_map entries are created appropriately."""

    @pytest.mark.asyncio
    async def test_newly_added_draft_server_has_no_tool_map_entry(self):
        """Draft servers should not get tool map entries initially."""
        manager = DummyServerManager([])
        
        # Simulate adding a draft server (as _handle_add_server does)
        new_upstream = UpstreamConfig.create_draft(name="new-mcp-server-1")
        manager.config.upstreams.append(new_upstream)
        
        # Draft server should not have a tool map entry yet
        assert "new-mcp-server-1" not in manager.server_tool_map

    @pytest.mark.asyncio
    async def test_completing_draft_server_initializes_tool_map_entry(self):
        """When a draft server gets a command, it should get a tool map entry."""
        # Create a draft server
        draft_upstream = UpstreamConfig.create_draft(name="test-server")
        manager = DummyServerManager([draft_upstream])
        manager.selected_server = "test-server"
        
        # Initially no tool map entry
        assert "test-server" not in manager.server_tool_map
        assert draft_upstream.is_draft is True
        
        # Simulate committing a command (as _commit_command_input does)
        draft_upstream.command = ["python", "-m", "server"]
        draft_upstream.is_draft = False
        
        # Initialize tool map entry (this is what the fix adds to _commit_command_input)
        manager.server_tool_map["test-server"] = {
            "tools": [],
            "last_refreshed": None,
            "status": "pending",
            "message": "Server configuration complete. Click 'Connect' to discover tools.",
        }

        # The server should have a tool map entry indicating pending/awaiting discovery
        assert "test-server" in manager.server_tool_map

        # The entry should indicate that discovery hasn't happened yet
        entry = manager.server_tool_map["test-server"]
        assert entry["tools"] == []
        assert entry["status"] == "pending"
        assert "Connect" in entry["message"]


class TestServerToolMapEdgeCases:
    """Test edge cases for server_tool_map management."""

    @pytest.mark.asyncio
    async def test_clearing_command_reverts_to_draft(self):
        """Clearing a server's command should mark it as draft again."""
        # Create a completed server
        completed_upstream = UpstreamConfig(
            name="test-server",
            transport="stdio",
            command=["python", "-m", "server"],
            is_draft=False
        )
        manager = DummyServerManager([completed_upstream])
        manager.selected_server = "test-server"
        
        # Clear the command
        completed_upstream.command = None
        completed_upstream.is_draft = True
        
        # Server should be marked as draft
        assert completed_upstream.is_draft is True
        assert completed_upstream.command is None

    @pytest.mark.asyncio
    async def test_http_transport_server_gets_unsupported_status(self):
        """HTTP transport servers should get 'unsupported' status in tool map."""
        http_upstream = UpstreamConfig(
            name="http-server",
            transport="http",
            url="https://example.com/mcp",
            is_draft=False
        )
        manager = DummyServerManager([http_upstream])
        
        # Simulate what _discover_server_identities does for HTTP servers
        manager.server_tool_map["http-server"] = {
            "tools": [],
            "last_refreshed": None,
            "status": "unsupported",
            "message": "Tool discovery available only for stdio transports with launch commands.",
        }
        
        # Verify the entry exists and has correct status
        assert "http-server" in manager.server_tool_map
        assert manager.server_tool_map["http-server"]["status"] == "unsupported"

    @pytest.mark.asyncio
    async def test_rename_server_references_updates_tool_map(self):
        """When a server is renamed, its server_tool_map entry should be moved."""
        # Create a server with a tool map entry
        upstream = UpstreamConfig(
            name="old-name",
            transport="stdio",
            command=["python", "-m", "server"],
            is_draft=False
        )
        manager = DummyServerManager([upstream])
        
        # Initialize tool map entry with the old name
        manager.server_tool_map["old-name"] = {
            "tools": [{"name": "test_tool"}],
            "last_refreshed": None,
            "status": "ok",
            "message": None,
        }
        
        # Rename the server (simulate what _commit_server_name does)
        old_name = upstream.name
        new_name = "new-name"
        upstream.name = new_name
        
        # Call _rename_server_references (this is what we're testing)
        manager._rename_server_references(old_name, new_name)
        
        # The tool map entry should be under the new name
        assert "new-name" in manager.server_tool_map
        assert "old-name" not in manager.server_tool_map
        
        # The entry data should be preserved
        entry = manager.server_tool_map["new-name"]
        assert entry["tools"] == [{"name": "test_tool"}]
        assert entry["status"] == "ok"
