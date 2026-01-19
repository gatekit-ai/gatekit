"""Integration tests for plugin rendering with in-memory config.

These tests verify Phase 1 fixes:
- _populate_global_plugins() uses in-memory config (not disk reload)
- Global plugin toggles refresh UI using current in-memory state
- Config modal changes sync immediately to UI
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from typing import List

import pytest

from gatekit.config.models import ProxyConfig, PluginsConfig, PluginConfig, UpstreamConfig, TimeoutConfig
from gatekit.tui.screens.config_editor.base import ConfigEditorScreen
from gatekit.tui.constants import GLOBAL_SCOPE


def build_minimal_config(
    global_security_plugins: List[PluginConfig] = None,
    global_auditing_plugins: List[PluginConfig] = None,
) -> ProxyConfig:
    """Build a minimal ProxyConfig for testing.

    Args:
        global_security_plugins: List of security plugins
        global_auditing_plugins: List of auditing plugins

    Returns:
        ProxyConfig instance
    """
    config = ProxyConfig(
        transport="stdio",
        upstreams=[
            UpstreamConfig(
                name="test_server",
                transport="stdio",
                command=["test"],
                is_draft=True
            )
        ],
        timeouts=TimeoutConfig()
    )

    config.plugins = PluginsConfig()

    if global_security_plugins:
        config.plugins.security = {GLOBAL_SCOPE: global_security_plugins}

    if global_auditing_plugins:
        config.plugins.auditing = {GLOBAL_SCOPE: global_auditing_plugins}

    return config


class TestPopulateGlobalPluginsUsesInMemoryConfig:
    """Test that _populate_global_plugins uses in-memory config, not disk reload."""

    @pytest.mark.asyncio
    async def test_in_memory_config_changes_used_not_disk(self):
        """Verify _populate_global_plugins uses in-memory config instead of reloading from disk.

        This is the Phase 1 regression test: config changes in-memory (e.g., from modal)
        must be reflected immediately without reloading from disk.
        """
        # Build config in-memory with a disabled plugin
        loaded_config = build_minimal_config(
            global_security_plugins=[
                PluginConfig(handler="pii_filter", config={"enabled": False, "priority": 50})
            ]
        )

        # Use temporary file path (but we won't actually write to it)
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            config_path = Path(tmp.name)

        try:
            with patch('gatekit.tui.screens.config_editor.base.PluginManager'):
                screen = ConfigEditorScreen(config_path, loaded_config)

                # Mock the widget query system
                mock_security_widget = Mock()
                mock_security_widget.update_plugins = Mock()
                mock_security_widget.plugins_data = []

                mock_auditing_widget = Mock()
                mock_auditing_widget.update_plugins = Mock()
                mock_auditing_widget.plugins_data = []

                with patch.object(screen, 'query_one') as mock_query_one, \
                     patch.object(screen, 'query') as mock_query, \
                     patch.object(screen, '_setup_navigation_containers'):

                    def query_one_side_effect(selector, widget_type=None):
                        if 'security' in selector:
                            return mock_security_widget
                        elif 'auditing' in selector:
                            return mock_auditing_widget
                        raise ValueError(f"Unexpected query: {selector}")

                    mock_query_one.side_effect = query_one_side_effect

                    # Mock query for height adjustment
                    mock_container = Mock()
                    mock_container.styles = Mock()
                    mock_query.return_value.first.return_value = mock_container

                    # CRITICAL: Modify in-memory config (simulating modal change)
                    # This should be picked up WITHOUT reloading from disk
                    screen.config.plugins.security[GLOBAL_SCOPE][0].enabled = True

                    # Call _populate_global_plugins
                    await screen._populate_global_plugins()

                    # Verify update_plugins was called with enabled=True data
                    assert mock_security_widget.update_plugins.call_count == 1
                    call_args = mock_security_widget.update_plugins.call_args[0][0]

                    # Find pii_filter in the data
                    pii_filter_data = next(
                        (p for p in call_args if p["handler"] == "pii_filter"),
                        None
                    )

                    assert pii_filter_data is not None, "pii_filter should appear in display data"
                    assert pii_filter_data["enabled"] is True, \
                        "In-memory change to enabled=True should be reflected"

        finally:
            # Cleanup temp file
            config_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_modal_config_changes_reflect_immediately(self):
        """Test that modal configuration changes are reflected immediately.

        Simulates workflow:
        1. User opens config with plugin disabled
        2. User modifies config through modal (changes in-memory config)
        3. UI refreshes via _populate_global_plugins()
        4. UI shows updated state (not stale disk state)
        """
        # Build config in-memory with disabled plugin
        loaded_config = build_minimal_config(
            global_security_plugins=[
                PluginConfig(
                    handler="pii_filter",
                    config={"enabled": False, "priority": 50, "patterns": []}
                )
            ]
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            config_path = Path(tmp.name)

        try:
            with patch('gatekit.tui.screens.config_editor.base.PluginManager'):
                screen = ConfigEditorScreen(config_path, loaded_config)

                # Track what data the widgets receive
                received_security_data = []
                received_auditing_data = []

                def capture_security_data(plugin_data):
                    received_security_data.append(plugin_data)

                def capture_auditing_data(plugin_data):
                    received_auditing_data.append(plugin_data)

                mock_security_widget = Mock()
                mock_security_widget.update_plugins = Mock(side_effect=capture_security_data)
                mock_security_widget.plugins_data = []

                mock_auditing_widget = Mock()
                mock_auditing_widget.update_plugins = Mock(side_effect=capture_auditing_data)
                mock_auditing_widget.plugins_data = []

                with patch.object(screen, 'query_one') as mock_query_one, \
                     patch.object(screen, 'query') as mock_query, \
                     patch.object(screen, '_setup_navigation_containers'):

                    def query_one_side_effect(selector, widget_type=None):
                        if 'security' in selector:
                            return mock_security_widget
                        elif 'auditing' in selector:
                            return mock_auditing_widget
                        raise ValueError(f"Unexpected query: {selector}")

                    mock_query_one.side_effect = query_one_side_effect

                    mock_container = Mock()
                    mock_container.styles = Mock()
                    mock_query.return_value.first.return_value = mock_container

                    # Initial population with disabled plugin
                    await screen._populate_global_plugins()

                    initial_data = received_security_data[0]
                    pii_filter = next(p for p in initial_data if p["handler"] == "pii_filter")
                    assert pii_filter["enabled"] is False, "Initially disabled"

                    # SIMULATE MODAL CHANGE: User enables plugin and adds patterns
                    screen.config.plugins.security[GLOBAL_SCOPE][0].enabled = True
                    screen.config.plugins.security[GLOBAL_SCOPE][0].config["enabled"] = True
                    screen.config.plugins.security[GLOBAL_SCOPE][0].config["patterns"] = ["ssn", "email"]

                    # Re-populate (this is what happens after modal closes)
                    await screen._populate_global_plugins()

                    # Verify updated data reflects in-memory changes
                    updated_data = received_security_data[1]
                    pii_filter_updated = next(
                        p for p in updated_data if p["handler"] == "pii_filter"
                    )

                    assert pii_filter_updated["enabled"] is True, \
                        "Modal change to enabled=True should be reflected"
                    # Status should reflect the new patterns (via describe_status)
                    # The actual status text depends on the plugin implementation

        finally:
            config_path.unlink(missing_ok=True)


class TestGlobalPluginToggleRefresh:
    """Test that global plugin toggles refresh both panes correctly."""

    @pytest.mark.asyncio
    async def test_global_toggle_refreshes_both_security_and_auditing(self):
        """Verify toggling a global plugin refreshes both security and auditing widgets.

        Phase 1 fix: handle_global_plugin_toggled() must call _populate_global_plugins()
        which refreshes BOTH security and auditing panes.
        """
        loaded_config = build_minimal_config(
            global_security_plugins=[
                PluginConfig(handler="pii_filter", config={"enabled": True, "priority": 50})
            ],
            global_auditing_plugins=[
                PluginConfig(handler="json_logger", config={"enabled": True, "priority": 50})
            ]
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            config_path = Path(tmp.name)

        try:
            with patch('gatekit.tui.screens.config_editor.base.PluginManager'):
                screen = ConfigEditorScreen(config_path, loaded_config)

                mock_security_widget = Mock()
                mock_security_widget.update_plugins = Mock()
                mock_security_widget.plugins_data = []

                mock_auditing_widget = Mock()
                mock_auditing_widget.update_plugins = Mock()
                mock_auditing_widget.plugins_data = []

                with patch.object(screen, 'query_one') as mock_query_one, \
                     patch.object(screen, 'query') as mock_query, \
                     patch.object(screen, '_setup_navigation_containers'):

                    def query_one_side_effect(selector, widget_type=None):
                        if 'security' in selector:
                            return mock_security_widget
                        elif 'auditing' in selector:
                            return mock_auditing_widget
                        raise ValueError(f"Unexpected query: {selector}")

                    mock_query_one.side_effect = query_one_side_effect

                    mock_container = Mock()
                    mock_container.styles = Mock()
                    mock_query.return_value.first.return_value = mock_container

                    # Reset call counts
                    mock_security_widget.update_plugins.reset_mock()
                    mock_auditing_widget.update_plugins.reset_mock()

                    # Call _populate_global_plugins (simulates refresh after toggle)
                    await screen._populate_global_plugins()

                    # CRITICAL: Both widgets should be updated
                    assert mock_security_widget.update_plugins.call_count == 1, \
                        "Security widget should be refreshed"
                    assert mock_auditing_widget.update_plugins.call_count == 1, \
                        "Auditing widget should also be refreshed"

        finally:
            config_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_refresh_uses_current_in_memory_state(self):
        """Verify _populate_global_plugins always uses current in-memory state.

        Multiple refreshes should always reflect the latest in-memory config,
        not cached or stale data.
        """
        loaded_config = build_minimal_config(
            global_security_plugins=[
                PluginConfig(handler="pii_filter", config={"enabled": False, "priority": 50})
            ]
        )

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            config_path = Path(tmp.name)

        try:
            with patch('gatekit.tui.screens.config_editor.base.PluginManager'):
                screen = ConfigEditorScreen(config_path, loaded_config)

                received_data = []

                def capture_data(plugin_data):
                    received_data.append([p.copy() for p in plugin_data])

                mock_security_widget = Mock()
                mock_security_widget.update_plugins = Mock(side_effect=capture_data)
                mock_security_widget.plugins_data = []

                mock_auditing_widget = Mock()
                mock_auditing_widget.update_plugins = Mock()
                mock_auditing_widget.plugins_data = []

                with patch.object(screen, 'query_one') as mock_query_one, \
                     patch.object(screen, 'query') as mock_query, \
                     patch.object(screen, '_setup_navigation_containers'):

                    def query_one_side_effect(selector, widget_type=None):
                        if 'security' in selector:
                            return mock_security_widget
                        elif 'auditing' in selector:
                            return mock_auditing_widget
                        raise ValueError(f"Unexpected query: {selector}")

                    mock_query_one.side_effect = query_one_side_effect

                    mock_container = Mock()
                    mock_container.styles = Mock()
                    mock_query.return_value.first.return_value = mock_container

                    # First refresh: disabled
                    await screen._populate_global_plugins()
                    first_data = received_data[0]
                    pii_filter_1 = next(p for p in first_data if p["handler"] == "pii_filter")
                    assert pii_filter_1["enabled"] is False

                    # Change in-memory config
                    screen.config.plugins.security[GLOBAL_SCOPE][0].enabled = True

                    # Second refresh: enabled
                    await screen._populate_global_plugins()
                    second_data = received_data[1]
                    pii_filter_2 = next(p for p in second_data if p["handler"] == "pii_filter")
                    assert pii_filter_2["enabled"] is True

                    # Change in-memory config again
                    screen.config.plugins.security[GLOBAL_SCOPE][0].enabled = False
                    screen.config.plugins.security[GLOBAL_SCOPE][0].priority = 25

                    # Third refresh: disabled with new priority
                    await screen._populate_global_plugins()
                    third_data = received_data[2]
                    pii_filter_3 = next(p for p in third_data if p["handler"] == "pii_filter")
                    assert pii_filter_3["enabled"] is False
                    assert pii_filter_3["priority"] == 25

        finally:
            config_path.unlink(missing_ok=True)
