"""Unit tests for guided setup error handling (Phase 6)."""

import json
from unittest.mock import patch

from gatekit.tui.guided_setup.detection import (
    detect_all_clients,
    detect_claude_desktop,
    detect_claude_code,
    detect_codex,
)
from gatekit.tui.guided_setup.parsers import JSONConfigParser, TOMLConfigParser


class TestNoClientsDetected:
    """Test handling when no MCP clients are detected."""

    def test_detect_all_clients_returns_empty_list_when_no_configs_exist(self, isolated_home):
        """When no config files exist, should return empty list."""
        # isolated_home fixture sets HOME, APPDATA, etc. to temp path
        # Also need to mock cwd to prevent detecting project-level configs
        with patch("pathlib.Path.cwd", return_value=isolated_home):
            clients = detect_all_clients()

        assert clients == []

    def test_detect_claude_desktop_returns_none_when_config_missing(self, isolated_home):
        """Claude Desktop detection should return None when config missing."""
        # isolated_home fixture handles HOME, APPDATA, and get_home_dir
        client = detect_claude_desktop()

        assert client is None

    def test_detect_claude_code_returns_none_when_config_missing(self, isolated_home):
        """Claude Code detection should return None when config missing."""
        # isolated_home fixture handles HOME, APPDATA, and get_home_dir
        with patch("pathlib.Path.cwd", return_value=isolated_home):
            client = detect_claude_code()

        assert client is None

    def test_detect_codex_returns_none_when_config_missing(self, isolated_home):
        """Codex detection should return None when config missing."""
        # isolated_home fixture handles HOME, APPDATA, and get_home_dir
        client = detect_codex()

        assert client is None


class TestParsingErrors:
    """Test handling of config parsing errors."""

    def test_json_parser_handles_malformed_json(self, tmp_path):
        """Parser should capture malformed JSON errors."""
        config_path = tmp_path / "bad_config.json"
        config_path.write_text("{ this is not valid json }", encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have no servers but capture the error
        assert len(servers) == 0
        assert len(errors) == 1
        assert "Invalid JSON" in errors[0]

    def test_json_parser_handles_file_not_found(self, tmp_path):
        """Parser should handle missing files gracefully."""
        config_path = tmp_path / "nonexistent.json"

        servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have no servers but capture the error
        assert len(servers) == 0
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_json_parser_captures_invalid_server_config(self, tmp_path):
        """Parser should capture errors from individual server parsing."""
        config_path = tmp_path / "config.json"
        config_data = {
            "mcpServers": {
                "good-server": {
                    "command": "npx",
                    "args": ["-y", "server"],
                },
                "bad-server": {
                    # Missing required fields
                    "invalid": "config",
                },
            }
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have parsed the good server
        assert len(servers) == 1
        assert servers[0].name == "good-server"

        # Should have captured error for bad server
        assert len(errors) == 1
        assert "bad-server" in errors[0]

    def test_toml_parser_handles_malformed_toml(self, tmp_path):
        """TOML parser should capture malformed TOML errors."""
        config_path = tmp_path / "bad_config.toml"
        config_path.write_text("[ this is not valid toml", encoding="utf-8")

        servers, errors = TOMLConfigParser.parse_file(config_path)

        # Should have no servers but capture the error
        assert len(servers) == 0
        assert len(errors) == 1
        assert "Failed to parse TOML" in errors[0]

    def test_detected_client_tracks_parse_errors(self, tmp_path):
        """DetectedClient should track all parse errors."""
        config_path = tmp_path / "config.json"
        config_data = {
            "mcpServers": {
                "server1": {"invalid": "config1"},
                "server2": {"invalid": "config2"},
                "good-server": {"command": "npx", "args": ["-y", "server"]},
            }
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            # Point Claude Desktop config to our test file
            with patch("platform.system", return_value="Linux"):
                # Create the expected path structure
                config_dir = tmp_path / ".config" / "Claude"
                config_dir.mkdir(parents=True)
                config_file = config_dir / "claude_desktop_config.json"
                config_file.write_text(json.dumps(config_data), encoding="utf-8")

                client = detect_claude_desktop()

        assert client is not None
        assert client.has_errors()
        assert len(client.parse_errors) == 2
        assert "server1" in client.parse_errors[0] or "server1" in client.parse_errors[1]
        assert "server2" in client.parse_errors[0] or "server2" in client.parse_errors[1]


class TestFileSystemErrors:
    """Test handling of file system errors."""

    def test_json_parser_handles_permission_denied(self, tmp_path):
        """Parser should handle permission denied errors."""
        config_path = tmp_path / "protected.json"
        config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        # Mock open() to raise PermissionError (cross-platform)
        # os.chmod(path, 0o000) doesn't work on Windows
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have no servers and capture the error
        assert len(servers) == 0
        assert len(errors) == 1
        assert "Failed to read" in errors[0]

    def test_json_parser_handles_directory_instead_of_file(self, tmp_path):
        """Parser should handle when config path is a directory."""
        config_path = tmp_path / "config.json"
        config_path.mkdir()  # Create as directory instead of file

        servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have no servers and capture the error
        assert len(servers) == 0
        assert len(errors) == 1


class TestEmptyConfigurations:
    """Test handling of empty or minimal configurations."""

    def test_json_parser_handles_empty_mcpservers_section(self, tmp_path):
        """Parser should handle empty mcpServers gracefully."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have no servers and no errors
        assert len(servers) == 0
        assert len(errors) == 0

    def test_json_parser_handles_missing_mcpservers_section(self, tmp_path):
        """Parser should handle missing mcpServers section."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"otherConfig": {}}', encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        # Should have no servers and no errors (not an error to have no servers)
        assert len(servers) == 0
        assert len(errors) == 0

    def test_detected_client_has_servers_method_with_empty_servers(self, tmp_path):
        """DetectedClient.has_servers() should return False when no servers."""
        config_path = tmp_path / "config.json"
        config_path.write_text('{"mcpServers": {}}', encoding="utf-8")

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("platform.system", return_value="Linux"):
                # Create the expected path structure
                config_dir = tmp_path / ".config" / "Claude"
                config_dir.mkdir(parents=True)
                config_file = config_dir / "claude_desktop_config.json"
                config_file.write_text('{"mcpServers": {}}', encoding="utf-8")

                client = detect_claude_desktop()

        assert client is not None
        assert not client.has_servers()


class TestInvalidServerConfigs:
    """Test handling of various invalid server configurations."""

    def test_server_with_invalid_command_type(self, tmp_path):
        """Server with non-string command should be rejected."""
        config_path = tmp_path / "config.json"
        config_data = {
            "mcpServers": {
                "bad-command": {
                    "command": 123,  # Should be string
                    "args": [],
                }
            }
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "command must be a string" in errors[0]

    def test_server_with_invalid_args_type(self, tmp_path):
        """Server with non-list args should be rejected."""
        config_path = tmp_path / "config.json"
        config_data = {
            "mcpServers": {
                "bad-args": {
                    "command": "npx",
                    "args": "not-a-list",  # Should be list
                }
            }
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "args must be a list" in errors[0]

    def test_server_with_neither_command_nor_url(self, tmp_path):
        """Server without command or url should be rejected."""
        config_path = tmp_path / "config.json"
        config_data = {
            "mcpServers": {
                "incomplete": {
                    "env": {"TOKEN": "value"}  # Has env but no command or url
                }
            }
        }
        config_path.write_text(json.dumps(config_data), encoding="utf-8")

        servers, errors = JSONConfigParser.parse_file(config_path)

        assert len(servers) == 0
        assert len(errors) == 1
        assert "must have either 'command' or 'url'" in errors[0]
