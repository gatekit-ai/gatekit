"""Integration tests for guided setup error handling with detection."""

import json
from pathlib import Path
from unittest.mock import patch

from gatekit.tui.guided_setup.detection import detect_all_clients
from gatekit.tui.guided_setup.error_handling import (
    DetectionResult,
    get_no_clients_message,
    format_parse_error_message,
)


class TestDetectionWithErrorHandling:
    """Test detection system with error handling integration."""

    def test_no_clients_detected_provides_helpful_message(self, isolated_home):
        """When no clients detected, should have clear message for user."""
        # isolated_home fixture handles HOME, APPDATA, get_home_dir
        # Also need to mock cwd to prevent detecting project-level configs
        with patch("pathlib.Path.cwd", return_value=isolated_home):
            clients = detect_all_clients()

        result = DetectionResult(clients=clients)

        assert result.is_empty()
        assert not result.has_clients()

        # Should have helpful message
        message = get_no_clients_message()
        assert "No MCP clients detected" in message
        assert "Claude Desktop" in message
        assert "Claude Code" in message
        assert "Codex" in message

    def test_clients_with_parse_errors_tracked(self, tmp_path):
        """Clients with parse errors should be detected but errors tracked."""
        # Create Claude Desktop config with some invalid servers
        config_data = {
            "mcpServers": {
                "good-server": {
                    "command": "npx",
                    "args": ["-y", "server"],
                },
                "bad-server1": {
                    "invalid": "config1",
                },
                "bad-server2": {
                    "command": 123,  # Invalid type
                    "args": [],
                },
            }
        }

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                with patch("platform.system", return_value="Linux"):
                    # Create the expected path structure
                    config_dir = tmp_path / ".config" / "Claude"
                    config_dir.mkdir(parents=True)
                    config_file = config_dir / "claude_desktop_config.json"
                    config_file.write_text(json.dumps(config_data), encoding="utf-8")

                    clients = detect_all_clients()

        result = DetectionResult(clients=clients)

        # Should have detected the client
        assert result.has_clients()
        assert result.client_count == 1

        # Client should have parse errors
        client = clients[0]
        assert client.has_errors()
        assert len(client.parse_errors) >= 2

        # Should be able to format error message
        error_msg = format_parse_error_message(client)
        assert "Claude Desktop" in error_msg
        assert "error" in error_msg.lower()

    def test_clients_with_servers_vs_empty_clients(self, tmp_path):
        """Should differentiate between clients with servers and empty configs."""
        # Create one client with servers and one without
        claude_desktop_config = {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "server"],
                }
            }
        }

        claude_code_config = {"mcpServers": {}}  # Empty

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("pathlib.Path.cwd", return_value=tmp_path):
                with patch("platform.system", return_value="Linux"):
                    # Create Claude Desktop config (with servers)
                    cd_dir = tmp_path / ".config" / "Claude"
                    cd_dir.mkdir(parents=True)
                    cd_file = cd_dir / "claude_desktop_config.json"
                    cd_file.write_text(json.dumps(claude_desktop_config), encoding="utf-8")

                    # Create Claude Code config (empty)
                    cc_file = tmp_path / ".claude.json"
                    cc_file.write_text(json.dumps(claude_code_config), encoding="utf-8")

                    clients = detect_all_clients()

        result = DetectionResult(clients=clients)

        # Should have detected 2 clients
        assert result.client_count == 2

        # Only 1 should have servers
        clients_with_servers = result.get_clients_with_servers()
        assert len(clients_with_servers) == 1
        assert clients_with_servers[0].has_servers()

    def test_partial_success_scenario(self, tmp_path):
        """Test scenario where some configs parse successfully and others fail."""
        # Create multiple client configs with varying quality
        claude_desktop_good = {
            "mcpServers": {
                "server1": {"command": "npx", "args": ["-y", "server1"]},
                "server2": {"command": "npx", "args": ["-y", "server2"]},
            }
        }

        claude_code_with_errors = {
            "mcpServers": {
                "good": {"command": "npx", "args": ["-y", "good"]},
                "bad": {"invalid": "config"},
            }
        }

        with patch("gatekit.tui.guided_setup.detection.get_home_dir", return_value=tmp_path):
            with patch("platform.system", return_value="Linux"):
                # Create Claude Desktop config (all good)
                cd_dir = tmp_path / ".config" / "Claude"
                cd_dir.mkdir(parents=True)
                cd_file = cd_dir / "claude_desktop_config.json"
                cd_file.write_text(json.dumps(claude_desktop_good), encoding="utf-8")

                # Create Claude Code config (partial errors)
                cc_file = tmp_path / ".claude.json"
                cc_file.write_text(json.dumps(claude_code_with_errors), encoding="utf-8")

                clients = detect_all_clients()

        result = DetectionResult(clients=clients)

        # Should have detected both clients
        assert result.client_count == 2

        # Both should have servers
        clients_with_servers = result.get_clients_with_servers()
        assert len(clients_with_servers) == 2

        # One should have errors, one should not
        clients_with_errors = [c for c in clients if c.has_errors()]
        clients_without_errors = [c for c in clients if not c.has_errors()]

        assert len(clients_with_errors) == 1
        assert len(clients_without_errors) == 1

        # Verify we can format error message for the one with errors
        error_client = clients_with_errors[0]
        error_msg = format_parse_error_message(error_client)
        assert len(error_msg) > 0
        assert "bad" in error_msg


class TestErrorMessageQuality:
    """Test that error messages are clear and actionable."""

    def test_no_clients_message_suggests_next_steps(self):
        """No clients message should suggest what user can do."""
        message = get_no_clients_message()

        # Should mention what can be done
        assert "create a blank configuration" in message.lower()

    def test_parse_error_message_identifies_problem_servers(self):
        """Parse error messages should identify which servers had problems."""
        from gatekit.tui.guided_setup.models import DetectedClient, ClientType

        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/fake/path.json"),
            servers=[],
            parse_errors=[
                "Failed to parse server 'broken-server': Server must have either 'command' or 'url'",
                "Failed to parse server 'another-broken': args must be a list, got <class 'str'>",
            ],
        )

        message = format_parse_error_message(client)

        # Should identify both problem servers
        assert "broken-server" in message
        assert "another-broken" in message
        assert "2 errors" in message
