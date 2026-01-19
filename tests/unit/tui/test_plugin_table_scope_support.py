"""Tests for plugin table scope parameter support.

Tests verify that PluginToggle and PluginActionClick messages include scope,
and that PluginRowWidget and PluginTableWidget properly support global vs server modes.
"""

import pytest
from textual.app import App

from gatekit.tui.widgets.plugin_table import (
    PluginToggle,
    PluginActionClick,
    PluginRowWidget,
    PluginTableWidget,
)
from gatekit.tui.constants import GLOBAL_SCOPE


class TestPluginToggleMessageScope:
    """Test PluginToggle message with scope parameter."""

    def test_plugin_toggle_includes_scope(self):
        """Test that PluginToggle message stores scope parameter."""
        msg = PluginToggle(
            handler="test_handler",
            plugin_type="security",
            enabled=True,
            scope="test_server"
        )

        assert msg.handler == "test_handler"
        assert msg.plugin_type == "security"
        assert msg.enabled is True
        assert msg.scope == "test_server"

    def test_plugin_toggle_global_scope(self):
        """Test PluginToggle with GLOBAL_SCOPE constant."""
        msg = PluginToggle(
            handler="pii_filter",
            plugin_type="security",
            enabled=False,
            scope=GLOBAL_SCOPE
        )

        assert msg.scope == GLOBAL_SCOPE
        assert msg.scope == "_global"


class TestPluginActionClickMessageScope:
    """Test PluginActionClick message with scope parameter."""

    def test_plugin_action_click_includes_scope(self):
        """Test that PluginActionClick message stores scope parameter."""
        msg = PluginActionClick(
            handler="test_handler",
            plugin_type="auditing",
            action="Configure",
            scope="my_server"
        )

        assert msg.handler == "test_handler"
        assert msg.plugin_type == "auditing"
        assert msg.action == "Configure"
        assert msg.scope == "my_server"

    def test_plugin_action_click_use_global_action(self):
        """Test PluginActionClick with Use Global action and server scope."""
        msg = PluginActionClick(
            handler="tool_manager",
            plugin_type="middleware",
            action="Use Global",
            scope="server1"
        )

        assert msg.action == "Use Global"
        assert msg.scope == "server1"

    def test_plugin_action_click_global_scope(self):
        """Test PluginActionClick with GLOBAL_SCOPE for Configure action."""
        msg = PluginActionClick(
            handler="json_logger",
            plugin_type="auditing",
            action="Configure",
            scope=GLOBAL_SCOPE
        )

        assert msg.scope == GLOBAL_SCOPE
        assert msg.action == "Configure"


class TestPluginRowWidgetScope:
    """Test PluginRowWidget scope parameter and message emissions."""

    @pytest.fixture
    def plugin_data(self):
        """Sample plugin data for testing."""
        return {
            "handler": "test_plugin",
            "display_name": "Test Plugin",
            "status": "Active",
            "enabled": True,
            "priority": 50,
        }

    def test_plugin_row_widget_accepts_scope(self, plugin_data):
        """Test that PluginRowWidget accepts and stores scope parameter."""
        widget = PluginRowWidget(
            plugin_data=plugin_data,
            plugin_type="security",
            scope="test_server",
            show_priority=True,
            show_actions=True,
        )

        assert widget.scope == "test_server"
        assert widget.plugin_type == "security"

    def test_plugin_row_widget_global_scope(self, plugin_data):
        """Test PluginRowWidget with GLOBAL_SCOPE."""
        widget = PluginRowWidget(
            plugin_data=plugin_data,
            plugin_type="auditing",
            scope=GLOBAL_SCOPE,
        )

        assert widget.scope == GLOBAL_SCOPE

    @pytest.mark.asyncio
    async def test_checkbox_toggle_emits_scope(self, plugin_data):
        """Test that checkbox toggle emits PluginToggle with scope."""
        class TestApp(App):
            def __init__(self):
                super().__init__()
                self.messages_received = []

            def compose(self):
                widget = PluginRowWidget(
                    plugin_data=plugin_data,
                    plugin_type="security",
                    scope="my_server",
                )
                return [widget]

            def on_plugin_toggle(self, msg: PluginToggle) -> None:
                """Capture PluginToggle messages."""
                self.messages_received.append(msg)

        app = TestApp()
        async with app.run_test() as pilot:
            # Use actual user action to toggle checkbox
            await pilot.click("#checkbox_test_plugin")
            await pilot.pause()

            # Verify message was sent with scope
            assert len(app.messages_received) >= 1
            msg = app.messages_received[0]
            assert isinstance(msg, PluginToggle)
            assert msg.handler == "test_plugin"
            assert msg.plugin_type == "security"
            assert msg.enabled is False  # Was True, now False
            assert msg.scope == "my_server"

    @pytest.mark.asyncio
    async def test_configure_button_click_emits_scope(self, plugin_data):
        """Test that Configure button click emits PluginActionClick with scope."""
        class TestApp(App):
            def __init__(self):
                super().__init__()
                self.messages_received = []

            def compose(self):
                widget = PluginRowWidget(
                    plugin_data=plugin_data,
                    plugin_type="middleware",
                    scope=GLOBAL_SCOPE,
                    show_actions=True,
                )
                return [widget]

            def on_plugin_action_click(self, msg: PluginActionClick) -> None:
                """Capture PluginActionClick messages."""
                self.messages_received.append(msg)

        app = TestApp()
        async with app.run_test() as pilot:
            # Focus configure button and activate with keyboard (more reliable than clicking in tests)
            configure_btn = app.query_one("#action_configure_test_plugin")
            configure_btn.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Verify message was sent with scope
            assert len(app.messages_received) >= 1
            msg = app.messages_received[0]
            assert isinstance(msg, PluginActionClick)
            assert msg.handler == "test_plugin"
            assert msg.plugin_type == "middleware"
            assert msg.action == "Configure"
            assert msg.scope == GLOBAL_SCOPE

    @pytest.mark.asyncio
    async def test_use_global_button_click_emits_scope(self):
        """Test that Use Global button click emits PluginActionClick with scope."""
        # Plugin data with global enabled and override state
        plugin_data = {
            "handler": "test_plugin",
            "display_name": "Test Plugin",
            "status": "Overrides global",
            "enabled": False,
            "priority": 50,
            "global_enabled": True,
            "inheritance": "overrides (disables)",
        }

        class TestApp(App):
            def __init__(self):
                super().__init__()
                self.messages_received = []

            def compose(self):
                widget = PluginRowWidget(
                    plugin_data=plugin_data,
                    plugin_type="security",
                    scope="server1",
                    show_actions=True,
                )
                return [widget]

            def on_plugin_action_click(self, msg: PluginActionClick) -> None:
                """Capture PluginActionClick messages."""
                self.messages_received.append(msg)

        app = TestApp()
        async with app.run_test() as pilot:
            # Focus Use Global button and activate with keyboard (more reliable than clicking in tests)
            useglobal_btn = app.query_one("#action_useglobal_test_plugin")
            useglobal_btn.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Verify message was sent with scope
            assert len(app.messages_received) >= 1
            msg = app.messages_received[0]
            assert isinstance(msg, PluginActionClick)
            assert msg.handler == "test_plugin"
            assert msg.action == "Use Global"
            assert msg.scope == "server1"

    @pytest.mark.asyncio
    async def test_configure_keyboard_activation_emits_scope(self, plugin_data):
        """Test that Enter/Space on Configure button emits PluginActionClick with scope."""
        class TestApp(App):
            def __init__(self):
                super().__init__()
                self.messages_received = []

            def compose(self):
                widget = PluginRowWidget(
                    plugin_data=plugin_data,
                    plugin_type="auditing",
                    scope="log_server",
                    show_actions=True,
                )
                return [widget]

            def on_plugin_action_click(self, msg: PluginActionClick) -> None:
                """Capture PluginActionClick messages."""
                self.messages_received.append(msg)

        app = TestApp()
        async with app.run_test() as pilot:
            # Focus configure button and press Enter
            configure_btn = app.query_one("#action_configure_test_plugin")
            configure_btn.focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            # Verify message was sent with scope
            assert len(app.messages_received) >= 1
            msg = app.messages_received[0]
            assert isinstance(msg, PluginActionClick)
            assert msg.scope == "log_server"


class TestPluginTableWidgetGlobalMode:
    """Test PluginTableWidget configuration for global vs server modes."""

    @pytest.fixture
    def sample_plugins(self):
        """Sample plugin data."""
        return [
            {
                "handler": "plugin1",
                "display_name": "Plugin One",
                "status": "Active",
                "enabled": True,
                "priority": 10,
            },
            {
                "handler": "plugin2",
                "display_name": "Plugin Two",
                "status": "Inactive",
                "enabled": False,
                "priority": 50,
            },
        ]

    def test_plugin_table_server_mode_constructor(self, sample_plugins):
        """Test PluginTableWidget constructor for server mode."""
        widget = PluginTableWidget(
            plugin_type="security",
            server_name="my_server",
            plugins_data=sample_plugins,
            show_priority=True,
            show_header=True,
        )

        assert widget.plugin_type == "security"
        assert widget.server_name == "my_server"
        assert widget.show_priority is True
        assert widget.show_header is True

    def test_plugin_table_global_mode_constructor(self, sample_plugins):
        """Test PluginTableWidget constructor for global mode."""
        widget = PluginTableWidget(
            plugin_type="auditing",
            server_name=GLOBAL_SCOPE,
            plugins_data=sample_plugins,
            show_priority=False,
            show_header=False,
        )

        assert widget.server_name == GLOBAL_SCOPE
        assert widget.show_priority is False
        assert widget.show_header is False

    @pytest.mark.asyncio
    async def test_plugin_table_global_mode_no_header(self, sample_plugins):
        """Test that global mode doesn't render header when show_header=False."""
        class TestApp(App):
            def compose(self):
                return [
                    PluginTableWidget(
                        plugin_type="security",
                        server_name=GLOBAL_SCOPE,
                        plugins_data=sample_plugins,
                        show_priority=False,
                        show_header=False,
                        id="test_table",
                    )
                ]

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify no header is present
            from gatekit.tui.widgets.plugin_table import PluginTableHeader
            headers = app.query(PluginTableHeader)
            assert len(headers) == 0

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_plugin_table_server_mode_has_header(self, sample_plugins):
        """Test that server mode renders header when show_header=True."""
        class TestApp(App):
            def compose(self):
                return [
                    PluginTableWidget(
                        plugin_type="middleware",
                        server_name="server1",
                        plugins_data=sample_plugins,
                        show_priority=True,
                        show_header=True,
                        id="test_table",
                    )
                ]

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify header is present
            from gatekit.tui.widgets.plugin_table import PluginTableHeader
            headers = app.query(PluginTableHeader)
            assert len(headers) == 1

    @pytest.mark.asyncio
    async def test_plugin_table_global_mode_has_css_class(self, sample_plugins):
        """Test that global mode adds 'global-mode' CSS class."""
        class TestApp(App):
            def compose(self):
                return [
                    PluginTableWidget(
                        plugin_type="security",
                        server_name=GLOBAL_SCOPE,
                        plugins_data=sample_plugins,
                        show_header=False,
                        id="test_table",
                    )
                ]

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify global-mode class is present
            table = app.query_one("#test_table")
            assert "global-mode" in table.classes

    @pytest.mark.asyncio
    async def test_plugin_table_server_mode_no_global_css_class(self, sample_plugins):
        """Test that server mode doesn't add 'global-mode' CSS class."""
        class TestApp(App):
            def compose(self):
                return [
                    PluginTableWidget(
                        plugin_type="security",
                        server_name="server1",
                        plugins_data=sample_plugins,
                        show_header=True,
                        id="test_table",
                    )
                ]

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify global-mode class is NOT present
            table = app.query_one("#test_table")
            assert "global-mode" not in table.classes

    @pytest.mark.asyncio
    async def test_plugin_row_passes_scope_to_children(self, sample_plugins):
        """Test that PluginTableWidget passes scope to PluginRowWidget children."""
        class TestApp(App):
            def compose(self):
                return [
                    PluginTableWidget(
                        plugin_type="auditing",
                        server_name="audit_server",
                        plugins_data=sample_plugins,
                        show_header=True,
                        id="test_table",
                    )
                ]

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify all rows have the correct scope
            rows = app.query(PluginRowWidget)
            assert len(rows) == 2
            for row in rows:
                assert row.scope == "audit_server"
                assert row.plugin_type == "auditing"

    @pytest.mark.asyncio
    async def test_update_plugins_preserves_scope(self, sample_plugins):
        """Test that update_plugins() (via refresh_table) maintains correct scope for new rows."""
        class TestApp(App):
            def compose(self):
                return [
                    PluginTableWidget(
                        plugin_type="security",
                        server_name="production_server",
                        plugins_data=sample_plugins,
                        show_header=True,
                        id="test_table",
                    )
                ]

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()

            # Verify initial rows have correct scope
            initial_rows = app.query(PluginRowWidget)
            assert len(initial_rows) == 2
            for row in initial_rows:
                assert row.scope == "production_server"

            # Update plugins with new data
            new_plugins = [
                {
                    "handler": "plugin3",
                    "display_name": "Plugin Three",
                    "status": "New",
                    "enabled": True,
                    "priority": 20,
                },
                {
                    "handler": "plugin4",
                    "display_name": "Plugin Four",
                    "status": "Disabled",
                    "enabled": False,
                    "priority": 60,
                },
            ]

            table = app.query_one("#test_table", PluginTableWidget)
            table.update_plugins(new_plugins)
            await pilot.pause()

            # Verify new rows also have correct scope
            updated_rows = app.query(PluginRowWidget)
            assert len(updated_rows) == 2
            for row in updated_rows:
                assert row.scope == "production_server"
                assert row.plugin_type == "security"

            # Verify the handlers are correct
            handlers = [row.plugin_data["handler"] for row in updated_rows]
            assert "plugin3" in handlers
            assert "plugin4" in handlers
