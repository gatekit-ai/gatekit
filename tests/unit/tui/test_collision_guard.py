"""Tests for collision guard in button ID generation."""

from pathlib import Path
from gatekit.tui.screens.config_editor import ConfigEditorScreen, PluginActionContext
from gatekit.config import ProxyConfig, UpstreamConfig, TimeoutConfig


class TestCollisionGuard:
    """Tests for handler name collision detection and resolution."""

    def test_no_collision_same_names(self):
        """Test that identical handler names don't trigger collision logic."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Same handler name used multiple times should get same sanitized ID
        result1 = screen._sanitize_handler_for_id("my-handler", "security")
        result2 = screen._sanitize_handler_for_id("my-handler", "security")

        assert result1 == result2
        assert result1 == "my-handler"  # Dash is preserved in sanitization

    def test_collision_different_names_same_sanitized(self):
        """Test that different names with same sanitized form get unique IDs."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # handler.name sanitizes to "handler_name", handler-name keeps the dash as "handler-name"
        # So these don't actually collide - let's use two that do collide
        result1 = screen._sanitize_handler_for_id("handler.name", "security")
        result2 = screen._sanitize_handler_for_id(
            "handler name", "security"
        )  # Space becomes underscore

        # First one gets the plain sanitized version
        assert result1 == "handler_name"

        # Second one should get a suffix to avoid collision
        assert result2 != "handler_name"
        assert result2.startswith("handler_name_")
        # Should have a 4-char hex suffix
        suffix = result2.split("_")[-1]
        assert len(suffix) == 4
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_collision_suffix_stable(self):
        """Test that collision suffix is stable/deterministic."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )

        # Create two separate screen instances to test determinism
        screen1 = ConfigEditorScreen(Path("test.yaml"), config)
        screen2 = ConfigEditorScreen(Path("test.yaml"), config)

        # Set up collision in first screen
        screen1._sanitize_handler_for_id("handler.name", "security")
        result1 = screen1._sanitize_handler_for_id("handler name", "security")

        # Set up same collision in second screen
        screen2._sanitize_handler_for_id("handler.name", "security")
        result2 = screen2._sanitize_handler_for_id("handler name", "security")

        # Should get the same suffix both times (deterministic)
        assert result1 == result2

    def test_collision_different_plugin_types(self):
        """Test that plugin type affects collision resolution."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Same original names but different plugin types
        screen._sanitize_handler_for_id("handler.name", "security")
        result1 = screen._sanitize_handler_for_id(
            "handler name", "security"
        )  # Collides
        result2 = screen._sanitize_handler_for_id(
            "handler name", "middleware"
        )  # Same name, different type

        # Should get different suffixes due to different plugin types
        assert result1 != result2
        assert result1.startswith("handler_name_")
        assert result2.startswith("handler_name_")
        suffix1 = result1.split("_")[-1]
        suffix2 = result2.split("_")[-1]
        assert suffix1 != suffix2

    def test_three_way_collision(self):
        """Test handling of three handlers that sanitize to the same value."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        # Three different names that all sanitize to "handler_name"
        result1 = screen._sanitize_handler_for_id("handler.name", "security")
        result2 = screen._sanitize_handler_for_id("handler name", "security")
        result3 = screen._sanitize_handler_for_id("handler@name", "security")

        # First gets plain version
        assert result1 == "handler_name"

        # Others get unique suffixes
        assert result2 != result1
        assert result3 != result1
        assert result3 != result2

        # All should start with the base
        assert result2.startswith("handler_name_")
        assert result3.startswith("handler_name_")


class TestButtonCreation:
    """Tests for centralized button creation."""

    def test_button_creation_with_context(self):
        """Test that button is created with proper ID and context."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        ctx = PluginActionContext(
            handler="my_handler",
            plugin_type="security",
            inheritance="global",
            enabled=True,
            server="_global",
        )

        button = screen._build_plugin_action_button(
            action_name="Configure",
            action_variant="primary",
            handler_name="my_handler",
            plugin_type="security",
            action_context=ctx,
        )

        # Check button properties
        assert button.id == "config_my_handler"
        assert button.label == "Configure"
        assert button.variant == "primary"
        assert hasattr(button, "data_ctx")
        assert button.data_ctx == ctx

    def test_button_creation_with_special_chars(self):
        """Test button creation with handler names containing special characters."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        ctx = PluginActionContext(
            handler="my-handler.name",
            plugin_type="middleware",
            inheritance="overrides",
            enabled=False,
            server="server1",
        )

        button = screen._build_plugin_action_button(
            action_name="Enable",
            action_variant="success",
            handler_name="my-handler.name",
            plugin_type="middleware",
            action_context=ctx,
        )

        # Check sanitization (dash preserved, dot becomes underscore)
        assert button.id == "enable_my-handler_name"
        assert button.label == "Enable"
        assert button.variant == "success"
        assert (
            button.data_ctx.handler == "my-handler.name"
        )  # Original preserved in context

    def test_button_action_prefix_mapping(self):
        """Test that all standard actions get correct ID prefixes."""
        config = ProxyConfig(
            transport="stdio",
            upstreams=[UpstreamConfig(name="test", command=["test"])],
            timeouts=TimeoutConfig(),
        )
        screen = ConfigEditorScreen(Path("test.yaml"), config)

        ctx = PluginActionContext(
            handler="test",
            plugin_type="auditing",
            inheritance="inherited",
            enabled=True,
            server="server1",
        )

        test_cases = [
            ("Configure", "config_test"),
            ("Disable", "disable_test"),
            ("Enable", "enable_test"),
            ("Reset", "reset_test"),
            ("Remove", "remove_test"),
        ]

        for action_name, expected_id in test_cases:
            button = screen._build_plugin_action_button(
                action_name=action_name,
                action_variant="default",
                handler_name="test",
                plugin_type="auditing",
                action_context=ctx,
            )
            assert button.id == expected_id
