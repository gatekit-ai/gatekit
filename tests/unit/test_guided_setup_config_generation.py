"""Unit tests for guided setup configuration generation."""

import pytest
from pathlib import Path

from gatekit.tui.guided_setup.config_generation import (
    convert_detected_servers_to_upstreams,
    create_default_plugins_config,
    generate_gatekit_config,
    generate_yaml_config,
)
from gatekit.tui.guided_setup.models import (
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
)


class TestConvertDetectedServersToUpstreams:
    """Test conversion of detected servers to UpstreamConfig format."""

    def test_converts_stdio_server(self):
        """Convert simple stdio server to UpstreamConfig."""
        server = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )

        upstreams = convert_detected_servers_to_upstreams([server])

        assert len(upstreams) == 1
        assert upstreams[0].name == "filesystem"
        assert upstreams[0].transport == "stdio"
        assert upstreams[0].command == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    def test_filters_http_servers(self):
        """HTTP servers should be filtered out (not supported in MVP)."""
        stdio_server = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )

        http_server = DetectedServer(
            name="figma",
            transport=TransportType.HTTP,
            url="https://mcp.figma.com",
        )

        upstreams = convert_detected_servers_to_upstreams([stdio_server, http_server])

        # Only stdio server should be included
        assert len(upstreams) == 1
        assert upstreams[0].name == "filesystem"

    def test_multiple_stdio_servers(self):
        """Convert multiple stdio servers."""
        servers = [
            DetectedServer(
                name="filesystem",
                transport=TransportType.STDIO,
                command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            ),
            DetectedServer(
                name="github",
                transport=TransportType.STDIO,
                command=["npx", "-y", "@modelcontextprotocol/server-github"],
                env={"GITHUB_TOKEN": "secret123"},
            ),
        ]

        upstreams = convert_detected_servers_to_upstreams(servers)

        assert len(upstreams) == 2
        assert upstreams[0].name == "filesystem"
        assert upstreams[1].name == "github"


class TestCreateDefaultPluginsConfig:
    """Test default plugin configuration creation."""

    def test_creates_jsonl_auditing_plugin(self):
        """Default config should include JSON lines auditing plugin."""
        plugins = create_default_plugins_config()

        # Should have auditing configuration
        assert "_global" in plugins.auditing
        assert len(plugins.auditing["_global"]) == 1

        # Check auditing plugin details
        # Note: auditing plugins don't have priority (unlike security/middleware)
        audit_plugin = plugins.auditing["_global"][0]
        assert audit_plugin.handler == "audit_jsonl"
        assert audit_plugin.enabled is True
        assert audit_plugin.config["output_file"] == "logs/gatekit_audit.jsonl"

    def test_no_default_security_plugins(self):
        """Default config should have no security plugins (explicit opt-in)."""
        plugins = create_default_plugins_config()

        assert len(plugins.security) == 0

    def test_default_middleware_plugins(self):
        """Default config should have call_trace middleware plugin."""
        plugins = create_default_plugins_config()

        assert len(plugins.middleware) == 1
        assert "_global" in plugins.middleware
        global_middleware = plugins.middleware["_global"]
        assert len(global_middleware) == 1
        assert global_middleware[0].handler == "call_trace"
        assert global_middleware[0].enabled is True
        assert global_middleware[0].priority == 100


class TestGenerateGatekitConfig:
    """Test Gatekit configuration generation."""

    def test_generates_config_from_single_client(self):
        """Generate config from single client with stdio servers."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
            ],
        )

        result = generate_gatekit_config([client])

        assert result.config.transport == "stdio"
        assert len(result.config.upstreams) == 1
        assert result.config.upstreams[0].name == "filesystem"
        assert result.config.plugins is not None

    def test_combines_servers_from_multiple_clients(self):
        """Combine servers from multiple clients into single config."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="github",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        assert len(result.config.upstreams) == 2
        upstream_names = [u.name for u in result.config.upstreams]
        assert "filesystem" in upstream_names
        assert "github" in upstream_names

    def test_tracks_http_servers_separately(self):
        """HTTP servers should be tracked separately (skipped)."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
                DetectedServer(
                    name="figma",
                    transport=TransportType.HTTP,
                    url="https://mcp.figma.com",
                ),
            ],
        )

        result = generate_gatekit_config([client])

        # Only stdio server in config
        assert len(result.config.upstreams) == 1
        assert result.config.upstreams[0].name == "filesystem"

        # HTTP server tracked as skipped
        assert len(result.http_servers) == 1
        assert result.http_servers[0].name == "figma"

        # Should have skip message
        skip_msg = result.get_http_skip_message()
        assert skip_msg is not None
        assert "figma" in skip_msg
        assert "not supported" in skip_msg

    def test_detects_env_vars(self):
        """Detect when servers have environment variables."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "secret123"},
                ),
            ],
        )

        result = generate_gatekit_config([client])

        assert result.has_env_vars is True

        # Should have security warning
        warning = result.get_security_warning()
        assert warning is not None
        assert "environment variables" in warning
        assert "plaintext" in warning

    def test_no_env_vars_no_warning(self):
        """No security warning when no env vars present."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
            ],
        )

        result = generate_gatekit_config([client])

        assert result.has_env_vars is False
        assert result.get_security_warning() is None

    def test_raises_error_when_no_stdio_servers(self):
        """Raise error when no stdio servers found."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="figma",
                    transport=TransportType.HTTP,
                    url="https://mcp.figma.com",
                ),
            ],
        )

        with pytest.raises(ValueError, match="No stdio servers found"):
            generate_gatekit_config([client])

    def test_resolves_server_name_conflicts(self):
        """Resolve conflicts when same server name in multiple clients."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        # Should have 2 upstreams with different names
        assert len(result.config.upstreams) == 2
        upstream_names = [u.name for u in result.config.upstreams]

        # Names should be suffixed
        assert "filesystem-desktop" in upstream_names
        assert "filesystem-code" in upstream_names


class TestGenerateYamlConfig:
    """Test YAML generation."""

    def test_generates_valid_yaml(self):
        """Generate valid YAML from config."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
            ],
        )

        result = generate_gatekit_config([client])
        yaml_str = generate_yaml_config(result.config, result.stdio_servers)

        # Basic structure checks
        assert "proxy:" in yaml_str
        assert "transport: stdio" in yaml_str
        assert "upstreams:" in yaml_str
        assert "name: filesystem" in yaml_str
        assert "plugins:" in yaml_str
        assert "auditing:" in yaml_str

    def test_includes_header_comment(self):
        """YAML should include header comment with generation timestamp."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
            ],
        )

        result = generate_gatekit_config([client])
        yaml_str = generate_yaml_config(result.config, result.stdio_servers)

        assert "# Gatekit Configuration" in yaml_str
        assert "# Generated:" in yaml_str

    def test_includes_security_warning_when_env_vars(self):
        """YAML should include security warning when env vars present."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "secret123"},
                ),
            ],
        )

        result = generate_gatekit_config([client])
        yaml_str = generate_yaml_config(result.config, result.stdio_servers)

        assert "# WARNING:" in yaml_str
        assert "environment variables" in yaml_str

    def test_no_security_warning_when_no_env_vars(self):
        """YAML should not include security warning when no env vars."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
            ],
        )

        result = generate_gatekit_config([client])
        yaml_str = generate_yaml_config(result.config, result.stdio_servers)

        # Should not have WARNING in header (but may have general comments)
        lines = yaml_str.split("\n")
        warning_lines = [line for line in lines if "# WARNING:" in line]
        assert len(warning_lines) == 0


class TestServerNameConflictResolution:
    """Test advanced server name conflict resolution scenarios."""

    def test_three_way_name_collision(self):
        """Three clients all have 'filesystem' server with different configs."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CODEX,
                config_path=Path("/home/user/.codex/config.toml"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/var"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        # Should have 3 upstreams with different suffixed names
        assert len(result.config.upstreams) == 3
        upstream_names = [u.name for u in result.config.upstreams]

        # All three should be renamed with suffixes
        assert "filesystem-desktop" in upstream_names
        assert "filesystem-code" in upstream_names
        assert "filesystem-codex" in upstream_names

    def test_partial_name_collision(self):
        """Some servers collide, others don't."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                    DetectedServer(
                        name="sqlite",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-sqlite"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",  # Conflicts
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home"],
                    ),
                    DetectedServer(
                        name="github",  # Unique
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        # Should have 4 upstreams total
        assert len(result.config.upstreams) == 4
        upstream_names = [u.name for u in result.config.upstreams]

        # Colliding servers get suffixes
        assert "filesystem-desktop" in upstream_names
        assert "filesystem-code" in upstream_names

        # Non-colliding servers keep original names
        assert "sqlite" in upstream_names
        assert "github" in upstream_names

    def test_no_name_collisions(self):
        """Multiple clients with all unique server names."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="github",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CODEX,
                config_path=Path("/home/user/.codex/config.toml"),
                servers=[
                    DetectedServer(
                        name="sqlite",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-sqlite"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        # All original names should be preserved
        assert len(result.config.upstreams) == 3
        upstream_names = [u.name for u in result.config.upstreams]

        assert "filesystem" in upstream_names
        assert "github" in upstream_names
        assert "sqlite" in upstream_names


class TestHTTPServerSkipping:
    """Test HTTP/SSE server skip message generation."""

    def test_multiple_http_servers_skip_message(self):
        """Skip message lists multiple HTTP server names."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
                DetectedServer(
                    name="figma",
                    transport=TransportType.HTTP,
                    url="https://mcp.figma.com",
                ),
                DetectedServer(
                    name="linear",
                    transport=TransportType.HTTP,
                    url="https://mcp.linear.app",
                ),
                DetectedServer(
                    name="notion",
                    transport=TransportType.HTTP,
                    url="https://mcp.notion.so",
                ),
            ],
        )

        result = generate_gatekit_config([client])

        # Only stdio server in config
        assert len(result.config.upstreams) == 1

        # Three HTTP servers tracked
        assert len(result.http_servers) == 3

        # Skip message should list all three
        skip_msg = result.get_http_skip_message()
        assert skip_msg is not None
        assert "Found 3 HTTP/SSE servers" in skip_msg
        assert "figma" in skip_msg
        assert "linear" in skip_msg
        assert "notion" in skip_msg
        assert "not supported" in skip_msg

    def test_no_http_servers_no_skip_message(self):
        """No skip message when all servers are stdio."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-github"],
                ),
            ],
        )

        result = generate_gatekit_config([client])

        assert len(result.http_servers) == 0
        assert result.get_http_skip_message() is None


class TestEnvVarDetection:
    """Test environment variable detection across multiple servers."""

    def test_env_vars_in_multiple_servers(self):
        """Detect env vars when spread across multiple servers."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="github",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-github"],
                        env={"GITHUB_TOKEN": "gh_secret"},
                    ),
                    DetectedServer(
                        name="linear",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-linear"],
                        env={"LINEAR_TOKEN": "lin_secret"},
                    ),
                    DetectedServer(
                        name="filesystem",  # No env vars
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        # Should detect env vars from any server
        assert result.has_env_vars is True
        assert result.get_security_warning() is not None

    def test_env_vars_only_in_http_servers_not_counted(self):
        """Env vars in HTTP servers (which are skipped) shouldn't trigger warning."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
                DetectedServer(
                    name="figma",  # Has env vars but is HTTP (skipped)
                    transport=TransportType.HTTP,
                    url="https://mcp.figma.com",
                    env={"FIGMA_TOKEN": "figma_secret"},
                ),
            ],
        )

        result = generate_gatekit_config([client])

        # Only stdio servers count for env var detection
        assert result.has_env_vars is False
        assert result.get_security_warning() is None


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_clients_list(self):
        """Handle empty clients list gracefully."""
        with pytest.raises(ValueError, match="No stdio servers found"):
            generate_gatekit_config([])

    def test_clients_with_no_servers(self):
        """Handle clients that have no servers."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[],  # Empty
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[],  # Empty
            ),
        ]

        with pytest.raises(ValueError, match="No stdio servers found"):
            generate_gatekit_config(clients)

    def test_all_http_servers_error(self):
        """Error when all servers are HTTP (none are stdio)."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="figma",
                        transport=TransportType.HTTP,
                        url="https://mcp.figma.com",
                    ),
                    DetectedServer(
                        name="linear",
                        transport=TransportType.HTTP,
                        url="https://mcp.linear.app",
                    ),
                ],
            ),
        ]

        with pytest.raises(ValueError, match="No stdio servers found"):
            generate_gatekit_config(clients)

    def test_mixed_stdio_and_http_across_clients(self):
        """One client has only HTTP, another has stdio."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="figma",
                        transport=TransportType.HTTP,
                        url="https://mcp.figma.com",
                    ),
                ],
            ),
            DetectedClient(
                client_type=ClientType.CLAUDE_CODE,
                config_path=Path("/home/user/.claude.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)

        # Should succeed with stdio server from second client
        assert len(result.config.upstreams) == 1
        assert result.config.upstreams[0].name == "filesystem"

        # HTTP server tracked
        assert len(result.http_servers) == 1
        assert result.http_servers[0].name == "figma"


class TestYAMLGenerationAdvanced:
    """Test advanced YAML generation scenarios."""

    def test_yaml_with_multiple_upstreams(self):
        """YAML generation with multiple upstreams."""
        clients = [
            DetectedClient(
                client_type=ClientType.CLAUDE_DESKTOP,
                config_path=Path("/home/user/.config/claude_desktop_config.json"),
                servers=[
                    DetectedServer(
                        name="filesystem",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    ),
                    DetectedServer(
                        name="github",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-github"],
                    ),
                    DetectedServer(
                        name="sqlite",
                        transport=TransportType.STDIO,
                        command=["npx", "-y", "@modelcontextprotocol/server-sqlite"],
                    ),
                ],
            ),
        ]

        result = generate_gatekit_config(clients)
        yaml_str = generate_yaml_config(result.config, result.stdio_servers)

        # Should have all three servers in YAML
        assert "name: filesystem" in yaml_str
        assert "name: github" in yaml_str
        assert "name: sqlite" in yaml_str

    def test_yaml_structure_completeness(self):
        """YAML includes all expected configuration sections."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_DESKTOP,
            config_path=Path("/home/user/.config/claude_desktop_config.json"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                ),
            ],
        )

        result = generate_gatekit_config([client])
        yaml_str = generate_yaml_config(result.config, result.stdio_servers)

        # Verify complete structure
        assert "transport: stdio" in yaml_str
        assert "upstreams:" in yaml_str
        assert "command:" in yaml_str
        assert "plugins:" in yaml_str
        assert "auditing:" in yaml_str
        assert "_global:" in yaml_str
        assert "handler: audit_jsonl" in yaml_str
        # Note: timeouts section may be omitted if using defaults
