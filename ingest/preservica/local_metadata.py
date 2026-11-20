"""Fields from Preservica metadata fragments that OAI-PMH doesn't carry, such as a local DCDS_local schema.

Preservica can hold several metadata fragments per entity. OAI-PMH returns one
schema per request, so a local schema kept alongside MODS (for example the
Department of Institutional Repository items) is read from the Entity API
instead: the EntityResponse links each fragment, and the fragment is fetched
only when its schema is configured.

config.yaml:

  local_metadata:
    - schema: "https://library.uni.edu/schemas/dcds_local"   # the fragment's namespace URI
      fields:
        department: department_ssim                          # element name -> Solr field

Element names match whatever namespace prefix the fragment uses. Values are
indexed as plain text; nothing from a fragment is trusted as HTML.
"""
from __future__ import annotations

import logging
import re

from .client import NotVisible, PreservicaClient
from .hierarchy import EntityInfo

log = logging.getLogger(__name__)
SOLR_FIELD = re.compile(r"^[a-z][a-z0-9_]*_(ssim|tesim|ssm)$")


def _norm(uri: str) -> str:
    return uri.strip().rstrip("/").lower()


def validate(config: list) -> list[dict]:
    """Checked local_metadata settings; raises ValueError on a bad entry."""
    out = []
    for i, entry in enumerate(config or []):
        if not isinstance(entry, dict) or not entry.get("schema") or not isinstance(entry.get("fields"), dict):
            raise ValueError(f"local_metadata[{i}] needs a schema and a fields map")
        for element, field in entry["fields"].items():
            if not SOLR_FIELD.match(str(field)):
                raise ValueError(f"local_metadata[{i}]: {field!r} must be a multi-valued Solr field "
                                 "ending _ssim, _tesim or _ssm")
        out.append({"schema": _norm(entry["schema"]), "fields": {str(k): str(v) for k, v in entry["fields"].items()}})
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def local_fields(client: PreservicaClient, info: EntityInfo, config: list[dict]) -> dict[str, list[str]]:
    """Solr fields from the entity's configured fragments; {} when it has none."""
    out: dict[str, list[str]] = {}
    for entry in config:
        for schema, url in info.fragments:
            if _norm(schema) != entry["schema"]:
                continue
            try:
                root = client.fragment(url)
            except NotVisible:
                log.warning("metadata fragment %s for %s is not visible to the service account", url, info.ref)
                continue
            for element, field in entry["fields"].items():
                for e in root.iter():
                    if _local(e.tag) == element:
                        text = re.sub(r"\s+", " ", "".join(e.itertext())).strip()
                        if text and text not in out.setdefault(field, []):
                            out[field].append(text)
    return {k: v for k, v in out.items() if v}
