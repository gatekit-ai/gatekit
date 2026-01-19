"""Regression tests for schema-driven golden plugin configs."""

from __future__ import annotations

import pytest

from tests.utils.golden import iter_golden_configs, load_golden_config


def _all_scenarios():
    scenarios = list(iter_golden_configs())
    if not scenarios:
        pytest.skip("No golden configs defined")
    return scenarios


@pytest.mark.parametrize(
    "scenario",
    _all_scenarios(),
    ids=lambda scn: f"{scn.handler}:{scn.scenario}",
)
def test_golden_configs_round_up_metadata(scenario):
    """Every golden file must parse and expose the expected metadata."""
    assert scenario.handler
    assert scenario.category in {"security", "middleware", "auditing"}
    assert isinstance(scenario.config, dict)


@pytest.mark.parametrize(
    "scenario",
    _all_scenarios(),
    ids=lambda scn: f"load-{scn.handler}:{scn.scenario}",
)
def test_load_golden_config_is_idempotent(scenario):
    """Calling the loader twice returns equivalent data structures."""
    again = load_golden_config(scenario.handler, scenario.scenario)
    assert again.config == scenario.config
    assert again.category == scenario.category
    assert again.description == scenario.description
