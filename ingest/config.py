"""Load config.yaml. Secrets come from environment variables, never from the file."""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")

DEFAULTS = {
    "label": "Preservica",
    "auth": "token",
    "metadata_prefix": "MODS",
    "public_security_tags": ["open"],
    "include_folders": True,
    "resolve_hierarchy": True,
    "skip_top_levels": 0,
    "collection_from": "hierarchy",
    "thumbnails": False,
    "thumbnail_size": "medium",
    "thumbnail_dir": "thumbnails",
    "landing_url_template": "",
    "folder_landing_url_template": "",
    "media_url_template": "",
    "thumbnail_url_template": "",
    "iiif_manifest_url_template": "",
    "georeference_url_template": "",
    "local_metadata": [],
    "max_delete_fraction": 0.2,
    "batch_size": 500,
    "request_delay": 0.0,
}


def _expand(value):
    """Replace ${VAR} or ${VAR:-default} in strings, recursively."""
    if isinstance(value, str):
        def sub(m):
            name, default = m.group(1), m.group(2)
            if name in os.environ:
                return os.environ[name]
            if default is not None:
                return default
            raise KeyError(f"environment variable {name} is not set")
        return _ENV.sub(sub, value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def load_config(path: str | Path) -> dict:
    """The whole configuration with ${VAR} expanded and defaults filled in.

    Returns {"solr_url", "source", "base_dir", "state_dir", "preservica": {...}}.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    pv = raw.get("preservica")
    if not isinstance(pv, dict):
        raise ValueError(f"{path}: a 'preservica' section is required")
    base_dir = path.parent.resolve()
    settings = {**DEFAULTS, **_expand(pv)}
    if settings["collection_from"] not in ("hierarchy", "mods", "both"):
        raise ValueError(f"{path}: collection_from must be hierarchy, mods or both")
    if settings["auth"] not in ("token", "basic"):
        raise ValueError(f"{path}: auth must be token or basic")
    thumb_dir = Path(settings["thumbnail_dir"])
    settings["thumbnail_dir"] = thumb_dir if thumb_dir.is_absolute() else base_dir / thumb_dir
    return {
        "solr_url": _expand(raw.get("solr_url", "${SOLR_URL:-http://127.0.0.1:8983/solr/preservica}")),
        # Machine name stamped on every record (source_ssi) and used for ids.
        "source": str(raw.get("source", "preservica")),
        "base_dir": base_dir,
        # Where incremental checkpoints are kept.
        "state_dir": base_dir / _expand(raw.get("state_dir", ".ingest-state")),
        "preservica": settings,
    }
