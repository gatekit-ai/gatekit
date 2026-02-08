"""Tests for loading sandbox configuration from YAML via ConfigLoader."""

import pytest
from pathlib import Path

from gatekit.config.loader import ConfigLoader


class TestSandboxConfigLoading:
    """Test sandbox config loads correctly through ConfigLoader."""

    def test_load_minimal_sandbox(self):
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test",
                        "command": ["echo", "hello"],
                        "sandbox": {"enabled": True},
                    }
                ],
            }
        }
        loader = ConfigLoader()
        config = loader.load_from_dict(config_dict)
        upstream = config.upstreams[0]
        assert upstream.sandbox is not None
        assert upstream.sandbox.enabled is True
        assert upstream.sandbox.network is True
        assert upstream.sandbox.paths == []

    def test_load_sandbox_with_paths(self):
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "fs",
                        "command": ["npx", "server", "/tmp"],
                        "sandbox": {
                            "enabled": True,
                            "paths": ["~/docs"],
                            "network": False,
                        },
                    }
                ],
            }
        }
        loader = ConfigLoader()
        config = loader.load_from_dict(config_dict)
        upstream = config.upstreams[0]
        assert upstream.sandbox.enabled is True
        assert upstream.sandbox.paths == ["~/docs"]
        assert upstream.sandbox.network is False

    def test_load_no_sandbox_field(self):
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test",
                        "command": ["echo", "hello"],
                    }
                ],
            }
        }
        loader = ConfigLoader()
        config = loader.load_from_dict(config_dict)
        assert config.upstreams[0].sandbox is None

    def test_sandbox_unknown_field_rejected(self):
        config_dict = {
            "proxy": {
                "transport": "stdio",
                "upstreams": [
                    {
                        "name": "test",
                        "command": ["echo", "hello"],
                        "sandbox": {
                            "enabled": True,
                            "unknown_field": "bad",
                        },
                    }
                ],
            }
        }
        loader = ConfigLoader()
        with pytest.raises(Exception):
            loader.load_from_dict(config_dict)


