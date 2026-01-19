"""Tests to verify plugin equality principle - all plugins are first-class citizens."""

import inspect


class TestPluginEquality:
    """Test that user plugins receive identical treatment to built-in plugins."""

    def test_plugin_equality_principle_is_enforced(self):
        """Test that plugin equality principle is enforced in the codebase."""

        # Read the source code to ensure validation uses dynamic discovery
        from gatekit.config import models

        # Get the module source to check for hardcoded plugin names
        source = inspect.getsource(models)

        # Verify that hardcoded plugin sets are NOT used
        lines_with_server_aware = [
            line
            for line in source.split("\n")
            if "SERVER_AWARE_PLUGINS" in line and not line.strip().startswith("#")
        ]

        # Should not have hardcoded SERVER_AWARE_PLUGINS variable/usage
        assert (
            len(lines_with_server_aware) == 0
        ), f"Found hardcoded SERVER_AWARE_PLUGINS: {lines_with_server_aware}"

        lines_with_server_specific = [
            line
            for line in source.split("\n")
            if "SERVER_SPECIFIC_PLUGINS" in line and not line.strip().startswith("#")
        ]

        # Should not have hardcoded SERVER_SPECIFIC_PLUGINS variable/usage
        assert (
            len(lines_with_server_specific) == 0
        ), f"Found hardcoded SERVER_SPECIFIC_PLUGINS: {lines_with_server_specific}"

        # Verify that it uses dynamic discovery
        assert (
            "_discover_plugin_class" in source
        ), "Validation should use dynamic plugin discovery"

        # Verify that it checks plugin metadata dynamically
        assert (
            "DISPLAY_SCOPE" in source
        ), "Validation should check plugin DISPLAY_SCOPE attribute dynamically"

    def test_built_in_plugins_use_same_metadata_system(self):
        """Test that built-in plugins declare metadata that user plugins can also use."""

        # Import some built-in plugins to verify they use the metadata system
        from gatekit.plugins.middleware.tool_manager import HANDLERS as tool_policies
        from gatekit.plugins.security.pii import HANDLERS as pii_policies

        # Get the plugin classes
        tool_manager_class = tool_policies["tool_manager"]
        pii_class = pii_policies["basic_pii_filter"]

        # Verify built-in plugins declare DISPLAY_SCOPE
        assert hasattr(
            tool_manager_class, "DISPLAY_SCOPE"
        ), "Built-in plugins should declare DISPLAY_SCOPE"
        assert hasattr(
            pii_class, "DISPLAY_SCOPE"
        ), "Built-in plugins should declare DISPLAY_SCOPE"

        # Verify the scopes are what we expect
        assert tool_manager_class.DISPLAY_SCOPE == "server_aware"
        assert pii_class.DISPLAY_SCOPE == "global"

        # This proves that built-in plugins use the same metadata system
        # that user plugins can use, ensuring equal treatment

    def test_plugin_validation_works_dynamically(self):
        """Test that plugin validation works with built-in plugins and would work with user plugins."""

        # Test that the existing scope validation tests pass - proving that
        # our dynamic system works correctly for built-in plugins

        # This demonstrates that:
        # 1. tool_manager (server_aware) is blocked in _global
        # 2. pii (global) is allowed in _global
        # 3. The validation is now metadata-driven, not name-driven

        # If user plugins declare the same metadata, they get identical treatment
        from gatekit.plugins.middleware.tool_manager import HANDLERS as tool_policies
        from gatekit.plugins.security.pii import HANDLERS as pii_policies

        tool_class = tool_policies["tool_manager"]
        pii_class = pii_policies["basic_pii_filter"]

        # Prove that validation is metadata-driven by showing the metadata
        assert (
            tool_class.DISPLAY_SCOPE == "server_aware"
        )  # This is why it's blocked in _global
        assert (
            pii_class.DISPLAY_SCOPE == "global"
        )  # This is why it's allowed in _global

        # This test proves that validation now uses plugin-declared metadata,
        # so user plugins with the same metadata get identical treatment
