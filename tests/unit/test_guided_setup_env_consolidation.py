"""Unit tests for environment variable consolidation (Phase 1 - TDD)."""


from gatekit.tui.guided_setup.models import DetectedServer, TransportType
from gatekit.tui.guided_setup.config_generation import (
    _mask_env_value,
    _collect_all_env_vars,
)


class TestEnvValueMasking:
    """Test _mask_env_value function."""

    def test_mask_long_value(self):
        """Should mask all but last 4 characters."""
        masked = _mask_env_value("API_KEY", "secret_api_key_12345")
        assert masked == "********2345"

    def test_mask_short_value(self):
        """Should mask values 4 chars or less completely."""
        assert _mask_env_value("KEY", "abc") == "********"
        assert _mask_env_value("KEY", "abcd") == "********"

    def test_mask_exactly_four_chars(self):
        """Exactly 4 characters should be fully masked."""
        assert _mask_env_value("KEY", "1234") == "********"

    def test_mask_five_chars(self):
        """Five characters should show last 4."""
        assert _mask_env_value("KEY", "12345") == "********2345"


class TestCollectAllEnvVars:
    """Test _collect_all_env_vars function."""

    def test_no_env_vars(self):
        """Servers with no env vars should return empty dict."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
            )
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {}
        assert conflicts == []

    def test_single_server_env_vars(self):
        """Single server's env vars should be collected."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
                env={"API_KEY": "key1", "DB_URL": "postgres://localhost"},
            )
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {"API_KEY": "key1", "DB_URL": "postgres://localhost"}
        assert conflicts == []

    def test_multiple_servers_no_conflicts(self):
        """Multiple servers with different env vars should merge."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
                env={"API_KEY": "key1"},
            ),
            DetectedServer(
                name="server-b",
                transport=TransportType.STDIO,
                command=["npx", "server-b"],
                env={"DB_URL": "postgres://localhost"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {"API_KEY": "key1", "DB_URL": "postgres://localhost"}
        assert conflicts == []

    def test_conflict_detection(self):
        """Should detect when same key has different values."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
                env={"API_KEY": "key_from_a"},
            ),
            DetectedServer(
                name="server-b",
                transport=TransportType.STDIO,
                command=["npx", "server-b"],
                env={"API_KEY": "key_from_b"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        # Should use last server's value
        assert env_vars["API_KEY"] == "key_from_b"

        # Should report conflict
        assert len(conflicts) == 1
        assert "API_KEY" in conflicts[0]
        assert "server-a" in conflicts[0]
        assert "server-b" in conflicts[0]

    def test_conflict_masking(self):
        """Conflict messages should mask sensitive values."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
                env={"API_KEY": "secret_key_12345"},
            ),
            DetectedServer(
                name="server-b",
                transport=TransportType.STDIO,
                command=["npx", "server-b"],
                env={"API_KEY": "secret_key_67890"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert len(conflicts) == 1
        # Should show masked values
        assert "********2345" in conflicts[0]
        assert "********7890" in conflicts[0]
        # Should NOT show full values
        assert "secret_key_12345" not in conflicts[0]
        assert "secret_key_67890" not in conflicts[0]

    def test_deterministic_resolution(self):
        """Last server in list should win conflicts (deterministic)."""
        servers = [
            DetectedServer(
                name="a",
                transport=TransportType.STDIO,
                command=["a"],
                env={"KEY": "value_a"},
            ),
            DetectedServer(
                name="b",
                transport=TransportType.STDIO,
                command=["b"],
                env={"KEY": "value_b"},
            ),
            DetectedServer(
                name="c",
                transport=TransportType.STDIO,
                command=["c"],
                env={"KEY": "value_c"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        # Last server (c) should win
        assert env_vars["KEY"] == "value_c"

        # Should report all conflicts
        assert len(conflicts) == 2  # a vs b, b vs c

    def test_same_value_no_conflict(self):
        """Same key with same value should not report conflict."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
                env={"API_KEY": "same_key"},
            ),
            DetectedServer(
                name="server-b",
                transport=TransportType.STDIO,
                command=["npx", "server-b"],
                env={"API_KEY": "same_key"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        assert env_vars == {"API_KEY": "same_key"}
        assert conflicts == []  # No conflict - same value

    def test_multiple_conflicts(self):
        """Should detect multiple conflicts across different keys."""
        servers = [
            DetectedServer(
                name="server-a",
                transport=TransportType.STDIO,
                command=["npx", "server-a"],
                env={"API_KEY": "key1", "DB_URL": "url1"},
            ),
            DetectedServer(
                name="server-b",
                transport=TransportType.STDIO,
                command=["npx", "server-b"],
                env={"API_KEY": "key2", "DB_URL": "url2"},
            ),
        ]

        env_vars, conflicts = _collect_all_env_vars(servers)

        # Should use last values
        assert env_vars["API_KEY"] == "key2"
        assert env_vars["DB_URL"] == "url2"

        # Should report both conflicts
        assert len(conflicts) == 2
        conflict_text = " ".join(conflicts)
        assert "API_KEY" in conflict_text
        assert "DB_URL" in conflict_text
