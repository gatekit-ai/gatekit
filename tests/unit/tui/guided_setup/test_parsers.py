"""Unit tests for MCP client config parsers (JSON and TOML)."""

import json
from pathlib import Path

from gatekit.tui.guided_setup.parsers import (
    JSONConfigParser,
    TOMLConfigParser,
    detect_scope_from_path,
)
from gatekit.tui.guided_setup.models import TransportType, ServerScope


class TestJSONConfigParser:
    """Test suite for JSON config parser (Claude Desktop, Claude Code)."""

    def test_parse_simple_stdio_server(self, tmp_path):
        """Parse a simple stdio server configuration."""
        config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                }
            }
        }

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0

        server = servers[0]
        assert server.name == "filesystem"
        assert server.transport == TransportType.STDIO
        assert server.command == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        assert server.env == {}

    def test_parse_server_with_env_vars(self, tmp_path):
        """Parse server with environment variables (actual values included)."""
        config = {
            "mcpServers": {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "ghp_1234567890abcdef"},
                }
            }
        }

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0

        server = servers[0]
        assert server.name == "github"
        assert server.has_env_vars()
        assert server.env["GITHUB_TOKEN"] == "ghp_1234567890abcdef"

    def test_parse_multiple_servers(self, tmp_path):
        """Parse config with multiple servers."""
        config = {
            "mcpServers": {
                "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
                "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
                "sqlite": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-sqlite"]},
            }
        }

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 3
        assert len(errors) == 0

        names = {s.name for s in servers}
        assert names == {"filesystem", "github", "sqlite"}

    def test_parse_http_server(self, tmp_path):
        """Parse HTTP/SSE server configuration (future support)."""
        config = {"mcpServers": {"linear": {"url": "https://mcp.linear.app/mcp"}}}

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0

        server = servers[0]
        assert server.name == "linear"
        assert server.transport == TransportType.HTTP
        assert server.url == "https://mcp.linear.app/mcp"
        assert server.is_http_based()
        # HTTP servers should not have env populated (avoids false "plaintext secrets" warnings)
        assert server.env == {}
        assert not server.has_env_vars()

    def test_parse_empty_mcpservers(self, tmp_path):
        """Parse config with empty mcpServers section."""
        config = {"mcpServers": {}}

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 0

    def test_parse_missing_mcpservers(self, tmp_path):
        """Parse config without mcpServers section."""
        config = {"otherSettings": {"foo": "bar"}}

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 0

    def test_parse_invalid_json(self, tmp_path):
        """Handle malformed JSON gracefully."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{ invalid json }")

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "invalid json" in errors[0].lower()

    def test_parse_nonexistent_file(self, tmp_path):
        """Handle missing config file."""
        config_file = tmp_path / "nonexistent.json"

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "not found" in errors[0].lower()

    def test_parse_server_with_invalid_command_type(self, tmp_path):
        """Handle server with invalid command type."""
        config = {"mcpServers": {"bad": {"command": 123, "args": []}}}  # command should be string

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "bad" in errors[0]

    def test_parse_server_with_invalid_args_type(self, tmp_path):
        """Handle server with invalid args type."""
        config = {"mcpServers": {"bad": {"command": "npx", "args": "should-be-list"}}}

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "bad" in errors[0]

    def test_parse_server_without_command_or_url(self, tmp_path):
        """Handle server missing both command and url."""
        config = {"mcpServers": {"bad": {"something": "else"}}}

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "bad" in errors[0]

    def test_parse_mixed_valid_and_invalid(self, tmp_path):
        """Parse config with mix of valid and invalid servers."""
        config = {
            "mcpServers": {
                "good": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
                "bad": {"command": 123},  # Invalid
                "also_good": {"url": "https://example.com"},
            }
        }

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        # Should get 2 valid servers
        assert len(servers) == 2
        assert len(errors) == 1  # One error for "bad"

        names = {s.name for s in servers}
        assert names == {"good", "also_good"}

    def test_parse_complex_args_with_spaces(self, tmp_path):
        """Parse server with complex args containing spaces."""
        config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/with spaces/folder"],
                }
            }
        }

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config))

        servers, errors = JSONConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0
        assert servers[0].command[-1] == "/path/with spaces/folder"


class TestTOMLConfigParser:
    """Test suite for TOML config parser (Codex)."""

    def test_parse_simple_stdio_server(self, tmp_path):
        """Parse a simple stdio server from TOML."""
        toml_content = """
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0

        server = servers[0]
        assert server.name == "filesystem"
        assert server.transport == TransportType.STDIO
        assert server.command == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    def test_parse_server_with_env_inline_table(self, tmp_path):
        """Parse server with env vars using TOML inline table syntax."""
        toml_content = """
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { "GITHUB_TOKEN" = "ghp_1234567890abcdef" }
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0

        server = servers[0]
        assert server.has_env_vars()
        assert server.env["GITHUB_TOKEN"] == "ghp_1234567890abcdef"

    def test_parse_multiple_servers(self, tmp_path):
        """Parse TOML config with multiple servers."""
        toml_content = """
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]

[mcp_servers.sqlite]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-sqlite"]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 3
        assert len(errors) == 0

        names = {s.name for s in servers}
        assert names == {"filesystem", "github", "sqlite"}

    def test_parse_http_server(self, tmp_path):
        """Parse HTTP server from TOML (future support)."""
        toml_content = """
[mcp_servers.linear]
url = "https://mcp.linear.app/mcp"
bearer_token_env_var = "LINEAR_TOKEN"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 1
        assert len(errors) == 0

        server = servers[0]
        assert server.name == "linear"
        assert server.transport == TransportType.HTTP
        assert server.url == "https://mcp.linear.app/mcp"
        # HTTP servers should not have env populated (avoids false "plaintext secrets" warnings)
        # The bearer_token_env_var name is preserved in raw_config if needed later
        assert server.env == {}
        assert not server.has_env_vars()
        assert server.raw_config.get("bearer_token_env_var") == "LINEAR_TOKEN"

    def test_parse_empty_mcp_servers(self, tmp_path):
        """Parse TOML with empty mcp_servers section."""
        toml_content = """
[mcp_servers]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 0

    def test_parse_missing_mcp_servers(self, tmp_path):
        """Parse TOML without mcp_servers section."""
        toml_content = """
experimental_use_rmcp_client = true
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 0

    def test_parse_invalid_toml(self, tmp_path):
        """Handle malformed TOML gracefully."""
        toml_content = """
[invalid toml syntax
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1

    def test_parse_nonexistent_file(self, tmp_path):
        """Handle missing TOML config file."""
        config_file = tmp_path / "nonexistent.toml"

        servers, errors = TOMLConfigParser.parse_file(config_file)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "not found" in errors[0].lower()


class TestScopeDetection:
    """Test suite for Claude Code scope detection."""

    def test_detect_user_scope(self):
        """Detect user scope from .claude.json."""
        path = Path.home() / ".claude.json"
        scope = detect_scope_from_path(path)
        assert scope == ServerScope.USER

    def test_detect_project_scope(self):
        """Detect project scope from .mcp.json."""
        path = Path.cwd() / ".mcp.json"
        scope = detect_scope_from_path(path)
        assert scope == ServerScope.PROJECT

    def test_detect_none_for_other_files(self):
        """Return None for non-Claude Code config files."""
        path = Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
        scope = detect_scope_from_path(path)
        assert scope is None
