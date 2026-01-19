"""Helpers for loading and validating golden plugin configurations."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator

import yaml

from gatekit.plugins.manager import PluginManager
from gatekit.tui.utils.schema_cache import get_schema_validator

GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "golden_configs"
SUPPORTED_CATEGORIES = {"security", "middleware", "auditing"}
FRAMEWORK_FIELDS = {"enabled", "priority", "critical"}


@dataclass(frozen=True)
class GoldenScenario:
    """Represents a single golden configuration scenario."""

    handler: str
    category: str
    scenario: str
    description: str
    config: Dict[str, Any]
    path: Path


def _read_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML helper with nice error messages."""
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:  # pragma: no cover - rare but helpful context
        raise ValueError(f"Failed to parse YAML at {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Golden config {path} must be a mapping, got {type(data)}")
    return data


@lru_cache(maxsize=1)
def _handler_index() -> Dict[str, Dict[str, type]]:
    """Build a cached category -> handler map using PluginManager discovery."""
    manager = PluginManager({})
    return {
        category: manager.get_available_handlers(category)
        for category in SUPPORTED_CATEGORIES
    }


def _ensure_handler(handler: str, category: str) -> None:
    """Ensure the requested handler exists for the category."""
    categories = _handler_index()
    if category not in categories:
        raise ValueError(f"Unknown plugin category '{category}' in golden configs")

    handlers = categories[category]
    if handler not in handlers:
        raise ValueError(
            f"Handler '{handler}' not found in category '{category}'. "
            f"Available: {', '.join(sorted(handlers)) or 'none'}"
        )


def _normalize_for_schema(config: Dict[str, Any]) -> Dict[str, Any]:
    """Strip framework-only keys before schema validation."""

    sanitized: Dict[str, Any] = {}
    for key, value in config.items():
        if key in FRAMEWORK_FIELDS:
            continue
        sanitized[key] = value
    return sanitized


def _validate_schema(handler: str, config: Dict[str, Any], path: Path) -> None:
    """Validate a config against the plugin JSON schema."""
    validator = get_schema_validator()
    sanitized = _normalize_for_schema(config)
    errors = validator.validate(handler, sanitized)
    if errors:
        formatted = "\n".join(errors)
        raise ValueError(
            f"Golden config {path} failed schema validation for '{handler}':\n{formatted}"
        )


def load_golden_config(handler: str, scenario: str) -> GoldenScenario:
    """Load and validate a specific handler/scenario pair."""
    path = GOLDEN_ROOT / handler / f"{scenario}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No golden config at {path}")

    data = _read_yaml(path)

    declared_handler = data.get("handler")
    if declared_handler != handler:
        raise ValueError(
            f"Golden config {path} declares handler '{declared_handler}' but resides under '{handler}'"
        )

    category = data.get("category")
    if category not in SUPPORTED_CATEGORIES:
        raise ValueError(
            f"Golden config {path} must set category to one of {sorted(SUPPORTED_CATEGORIES)}"
        )

    description = data.get("description", "")
    config = data.get("config")
    if not isinstance(config, dict):
        raise ValueError(f"Golden config {path} missing 'config' mapping")

    _ensure_handler(handler, category)
    _validate_schema(handler, config, path)

    return GoldenScenario(
        handler=handler,
        category=category,
        scenario=scenario,
        description=description,
        config=config,
        path=path,
    )


def iter_golden_configs(handlers: Iterable[str] | None = None) -> Iterator[GoldenScenario]:
    """Iterate through all (or filtered) golden configs."""
    handler_filter = set(handlers) if handlers else None

    if not GOLDEN_ROOT.exists():
        return iter(())

    for handler_dir in sorted(GOLDEN_ROOT.iterdir()):
        if not handler_dir.is_dir():
            continue
        handler = handler_dir.name
        if handler_filter and handler not in handler_filter:
            continue

        for yaml_file in sorted(handler_dir.glob("*.yaml")):
            yield load_golden_config(handler, yaml_file.stem)


__all__ = ["GoldenScenario", "GOLDEN_ROOT", "iter_golden_configs", "load_golden_config"]
