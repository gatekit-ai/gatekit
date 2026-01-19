"""Configuration persistence utilities for saving ProxyConfig to disk."""

from pathlib import Path
from typing import Optional
import yaml

from .models import ProxyConfig
from .serialization import config_to_dict
from .errors import ConfigWriteError
from ..utils.filesystem import atomic_write_text


def save_config(
    path: Path,
    config: ProxyConfig,
    *,
    allow_incomplete: bool = False,
    header: Optional[str] = None,
    atomic: bool = True,
) -> None:
    """Save ProxyConfig to disk as YAML with optional header.

    This is the single entry point for persisting Gatekit configurations.
    Uses atomic writes by default to prevent corruption on crash/failure.

    Args:
        path: Target file path (absolute path recommended)
        config: ProxyConfig instance to save
        allow_incomplete: If True, allow draft/incomplete configs (default: False)
                         Set to True for guided setup workflows that save partial configs
        header: Optional header text to prepend to YAML (e.g., generation comments)
                None or empty string = no header added
        atomic: If True, use atomic write (temp file + rename, default: True)
               If False, write directly (useful for debugging or special cases)

    Raises:
        ConfigWriteError: If write fails (wraps underlying exception with path/reason)
        ValueError: If allow_incomplete=False and config has draft/incomplete upstreams

    Notes:
        - Comments/formatting in existing files are NOT preserved (YAML regenerated)
        - Defaults may become explicit in output (e.g., restart_on_failure=true)
        - Key order follows serializer's deterministic insertion order
        - Last-write-wins if multiple processes write concurrently (no file locking)
        - Temp files may remain on crash (safe to delete *.tmp files manually)
    """
    try:
        # Convert config to dict, validating drafts if required
        # Note: validate_drafts is INVERTED from allow_incomplete
        config_dict = config_to_dict(config, validate_drafts=not allow_incomplete)

        # Serialize to YAML
        yaml_content = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)

        # Add header if provided and non-empty
        if header:
            final_content = header + yaml_content
        else:
            final_content = yaml_content

        # Write to disk (atomic or direct)
        if atomic:
            atomic_write_text(path, final_content)
        else:
            # Direct write (no atomic safety)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(final_content, encoding="utf-8")

    except ValueError:
        # Re-raise validation errors from config_to_dict (draft validation)
        raise

    except Exception as e:
        # Wrap all other errors in ConfigWriteError for consistent error handling
        reason = str(e) or type(e).__name__
        raise ConfigWriteError(path, reason, cause=e) from e
