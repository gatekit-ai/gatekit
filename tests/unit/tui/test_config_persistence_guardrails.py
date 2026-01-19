"""Tests for config persistence guardrails added for draft upstreams."""

import pytest

from gatekit.config.models import ProxyConfig, TimeoutConfig, UpstreamConfig
from gatekit.tui.screens.config_editor.config_persistence import (
    ConfigPersistenceMixin,
)


class DummyPersistence(ConfigPersistenceMixin):
    """Minimal concrete helper for testing mixin behaviour."""

    def __init__(self):
        # Attributes used by mixin methods but not relevant for _config_to_dict
        self.config_file_path = None  # pragma: no cover - not used


def test_config_to_dict_rejects_draft_upstream():
    """Serialisation should fail while a draft upstream is pending."""
    persistence = DummyPersistence()
    draft = UpstreamConfig.create_draft("draft-server")
    config = ProxyConfig(
        transport="stdio",
        upstreams=[draft],
        timeouts=TimeoutConfig(),
    )

    with pytest.raises(ValueError, match="draft"):
        persistence._config_to_dict(config)
