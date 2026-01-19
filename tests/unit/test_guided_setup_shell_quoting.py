"""Unit tests for shell quoting in guided setup commands."""

import platform
from pathlib import Path

from gatekit.tui.guided_setup.migration_instructions import (
    generate_migration_instructions,
    _quote_powershell,
)
from gatekit.tui.guided_setup.restore_scripts import (
    _build_claude_code_add_command_posix,
    _build_claude_code_add_command_windows,
    _build_codex_add_command_posix,
    _build_codex_add_command_windows,
)
from gatekit.tui.guided_setup.models import (
    DetectedServer,
    DetectedClient,
    ClientType,
    TransportType,
    ServerScope,
)


class TestPowerShellQuoting:
    """Test PowerShell quoting helper function."""

    def test_simple_string(self):
        """Simple strings get wrapped in double quotes."""
        assert _quote_powershell("hello") == '"hello"'

    def test_string_with_spaces(self):
        """Strings with spaces get wrapped in double quotes."""
        assert _quote_powershell("hello world") == '"hello world"'

    def test_path_with_spaces(self):
        """Paths with spaces get properly quoted."""
        path = "C:\\Program Files\\Gatekit\\gatekit-gateway.exe"
        result = _quote_powershell(path)
        assert result == '"C:\\Program Files\\Gatekit\\gatekit-gateway.exe"'

    def test_string_with_double_quotes(self):
        """Double quotes get escaped with backtick."""
        assert _quote_powershell('say "hello"') == '"say `"hello`""'

    def test_env_var_value_with_spaces(self):
        """Env var values with spaces get properly quoted."""
        value = "my secret token with spaces"
        result = _quote_powershell(value)
        assert result == '"my secret token with spaces"'


class TestMigrationInstructionsQuoting:
    """Test migration instructions properly quote paths and values."""

    def test_claude_code_paths_with_spaces(self):
        """Claude Code migration should quote paths with spaces."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-github"],
                    env={"GITHUB_TOKEN": "ghp_xxx"},
                ),
            ],
        )

        # Paths with spaces - note both have spaces
        gateway_path = Path("/Applications/Gatekit App/Contents/MacOS/gatekit-gateway")
        config_path = Path("/Users/First Last/Documents/gatekit.yaml")

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            gateway_path,
            config_path,
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # On POSIX, should use shlex.quote (single quotes when spaces present)
        if platform.system() != "Windows":
            # Path with spaces should be quoted
            assert "'/Applications/Gatekit App/Contents/MacOS/gatekit-gateway'" in snippet
            assert "'/Users/First Last/Documents/gatekit.yaml'" in snippet
        else:
            # On Windows, should use double quotes (path separators may vary)
            # Check that the paths are quoted and contain expected components
            assert 'Gatekit App' in snippet  # Has spaces, should be quoted
            assert 'First Last' in snippet  # Has spaces, should be quoted
            assert '"' in snippet  # Should use double quotes on Windows

    def test_claude_code_env_vars_with_spaces(self):
        """Claude Code migration should quote env var values with spaces."""
        client = DetectedClient(
            client_type=ClientType.CLAUDE_CODE,
            config_path=Path("/home/user/.claude.json"),
            servers=[
                DetectedServer(
                    name="github",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-github"],
                    env={"API_KEY": "my secret key with spaces"},
                ),
            ],
        )

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            Path("/usr/local/bin/gatekit-gateway"),
            Path("/home/user/gatekit.yaml"),
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # Env var value should be quoted
        if platform.system() != "Windows":
            # POSIX: shlex.quote wraps the whole KEY=VALUE
            assert "'API_KEY=my secret key with spaces'" in snippet
        else:
            # Windows: double quotes
            assert '"API_KEY=my secret key with spaces"' in snippet

    def test_codex_paths_with_spaces(self):
        """Codex migration should quote paths with spaces."""
        client = DetectedClient(
            client_type=ClientType.CODEX,
            config_path=Path("/home/user/.codex/config.toml"),
            servers=[
                DetectedServer(
                    name="filesystem",
                    transport=TransportType.STDIO,
                    command=["npx", "@modelcontextprotocol/server-filesystem"],
                ),
            ],
        )

        # Paths with spaces
        gateway_path = Path("C:/Program Files/Gatekit/gatekit-gateway.exe")
        config_path = Path("C:/Users/First Last/gatekit.yaml")

        instructions = generate_migration_instructions(
            [client],
            {s.name for c in [client] for s in c.get_stdio_servers()},
            gateway_path,
            config_path,
        )

        assert len(instructions) == 1
        snippet = instructions[0].migration_snippet

        # Paths should be quoted
        if platform.system() != "Windows":
            assert "'C:/Program Files/Gatekit/gatekit-gateway.exe'" in snippet
            assert "'C:/Users/First Last/gatekit.yaml'" in snippet
        else:
            # On Windows, should use double quotes (path separators may vary)
            # Check that the paths are quoted and contain expected components
            assert 'Program Files' in snippet  # Has spaces, should be quoted
            assert 'First Last' in snippet  # Has spaces, should be quoted
            assert '"' in snippet  # Should use double quotes on Windows


class TestRestoreScriptQuoting:
    """Test restore scripts properly quote paths and values."""

    def test_posix_command_with_spaces_in_args(self):
        """POSIX restore commands should quote args with spaces."""
        server = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-filesystem", "/path/with spaces"],
            scope=ServerScope.USER,
        )

        cmd = _build_claude_code_add_command_posix(server)

        # Command argument with spaces should be quoted
        assert "'/path/with spaces'" in cmd

    def test_posix_command_with_env_vars_with_spaces(self):
        """POSIX restore commands should quote env var values with spaces."""
        server = DetectedServer(
            name="github",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-github"],
            env={"TOKEN": "my secret token"},
            scope=ServerScope.USER,
        )

        cmd = _build_claude_code_add_command_posix(server)

        # Env var value should be quoted
        assert "'TOKEN=my secret token'" in cmd

    def test_windows_command_with_spaces_in_args(self):
        """Windows restore commands should quote args with spaces."""
        server = DetectedServer(
            name="filesystem",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-filesystem", "C:\\path\\with spaces"],
            scope=ServerScope.USER,
        )

        cmd = _build_claude_code_add_command_windows(server)

        # Command argument with spaces should be quoted
        assert '"C:\\path\\with spaces"' in cmd

    def test_windows_command_with_env_vars_with_spaces(self):
        """Windows restore commands should quote env var values with spaces."""
        server = DetectedServer(
            name="github",
            transport=TransportType.STDIO,
            command=["npx", "@modelcontextprotocol/server-github"],
            env={"TOKEN": "my secret token"},
            scope=ServerScope.USER,
        )

        cmd = _build_claude_code_add_command_windows(server)

        # Env var value should be quoted
        assert '"TOKEN=my secret token"' in cmd

    def test_codex_posix_with_special_chars(self):
        """Codex POSIX commands should handle special shell characters."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["cmd", "arg with $pecial"],
            env={"KEY": "value with $pecial"},
        )

        cmd = _build_codex_add_command_posix(server)

        # Special characters should be properly escaped by shlex.quote
        assert "'arg with $pecial'" in cmd
        assert "'KEY=value with $pecial'" in cmd

    def test_codex_windows_with_quotes(self):
        """Codex Windows commands should escape inner double quotes."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["cmd", 'arg with "quotes"'],
            env={"KEY": 'value with "quotes"'},
        )

        cmd = _build_codex_add_command_windows(server)

        # Inner double quotes should be escaped with backtick
        assert '"arg with `"quotes`""' in cmd
        assert '"KEY=value with `"quotes`""' in cmd


class TestEdgeCases:
    """Test edge cases for shell quoting."""

    def test_empty_env_var_value(self):
        """Empty env var values are handled (no quotes needed for EMPTY=)."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["cmd"],
            env={"EMPTY": ""},
            scope=ServerScope.USER,
        )

        cmd_posix = _build_claude_code_add_command_posix(server)
        cmd_windows = _build_claude_code_add_command_windows(server)

        # For POSIX: shlex.quote("EMPTY=") returns EMPTY= (no special chars)
        # For Windows: _quote_powershell("EMPTY=") returns "EMPTY="
        assert "--env" in cmd_posix and "EMPTY=" in cmd_posix
        assert "--env" in cmd_windows and "EMPTY=" in cmd_windows

    def test_path_with_only_spaces(self):
        """Path that is only spaces should be quoted."""
        result = _quote_powershell("   ")
        assert result == '"   "'

    def test_command_arg_with_newline(self):
        """Command args with newlines should be quoted/escaped."""
        server = DetectedServer(
            name="test",
            transport=TransportType.STDIO,
            command=["cmd", "arg\nwith\nnewlines"],
        )

        cmd_posix = _build_claude_code_add_command_posix(server)
        # shlex.quote should handle this safely
        assert "arg" in cmd_posix

    def test_multiple_consecutive_spaces(self):
        """Multiple consecutive spaces should be preserved."""
        value = "token    with    spaces"
        result = _quote_powershell(value)
        assert result == '"token    with    spaces"'
