"""Invalid config scenarios to ensure loader surfaces clear errors."""

from __future__ import annotations

import pytest

from gatekit.config.loader import ConfigLoader


@pytest.fixture
def loader():
    return ConfigLoader()


def _base_config():
    return {
        "proxy": {
            "transport": "stdio",
            "upstreams": [
                {"name": "test", "transport": "stdio", "command": ["echo", "ok"]}
            ],
        }
    }


def test_invalid_server_aware_plugin_in_global(loader):
    config_dict = _base_config()
    config_dict["plugins"] = {
        "middleware": {"_global": [{"handler": "tool_manager", "config": {"tools": []}}]}
    }

    with pytest.raises(Exception):
        loader.load_from_dict(config_dict)


def test_unknown_upstream_reference(loader):
    config_dict = _base_config()
    config_dict["plugins"] = {
        "security": {"unknown": [{"handler": "basic_pii_filter", "config": {}}]}
    }

    with pytest.raises(Exception):
        loader.load_from_dict(config_dict)
