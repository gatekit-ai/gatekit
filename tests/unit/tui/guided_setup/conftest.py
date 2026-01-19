"""Pytest configuration for guided setup tests."""

import platform
import sys


def pytest_collection_modifyitems(config, items):
    """
    Automatically skip platform-specific tests on wrong platforms.

    This prevents platform-specific tests from showing as "skipped" in the output
    by not collecting them at all when they're not for the current platform.
    """
    current_platform = platform.system()  # "Darwin", "Linux", "Windows"
    is_windows = sys.platform == "win32"

    filtered_items = []

    for item in items:
        # Check for platform_specific marker
        marker = item.get_closest_marker("platform_specific")
        if marker:
            required_platforms = marker.args[0] if marker.args else []

            # Check if test should run on current platform
            should_run = False
            if current_platform in required_platforms:
                should_run = True
            elif "Windows" in required_platforms and is_windows:
                should_run = True

            if should_run:
                filtered_items.append(item)
            # else: don't collect this test (won't show as skipped)
        else:
            # Not platform-specific, always collect
            filtered_items.append(item)

    # Update the items list
    items[:] = filtered_items
