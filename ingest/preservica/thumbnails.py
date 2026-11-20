"""Cache Preservica thumbnails as static files the Blacklight app can serve.

Preservica's Content API needs a token, so the public site can't link to it.
Instead the harvest downloads each public entity's thumbnail once and stores it
as <thumbnail_dir>/<uuid>.<ext>; the Rails app serves that folder (see
bin/setup_blacklight_app). Only entities that pass every public check get a
thumbnail, and a deletion removes the file.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from pathlib import Path

from .client import PreservicaClient

log = logging.getLogger(__name__)

EXTENSIONS = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
REF_RE = re.compile(r"^[0-9a-f-]+$")


class ThumbnailCache:
    def __init__(self, client: PreservicaClient, directory: Path, size: str = "medium", *,
                 refresh: bool = False, dry_run: bool = False):
        self.client = client
        self.dir = Path(directory)
        self.size = size
        self.refresh = refresh
        self.dry_run = dry_run
        self.fetched = 0
        if not dry_run:
            self.dir.mkdir(parents=True, exist_ok=True)

    def existing(self, ref: str) -> str | None:
        for ext in set(EXTENSIONS.values()):
            name = f"{ref}.{ext}"
            if (self.dir / name).exists():
                return name
        return None

    def get(self, kind: str, ref: str, *, changed: bool = False) -> str | None:
        """File name of the entity's thumbnail, downloading it if needed. None if there is none."""
        ref = ref.lower()
        if not REF_RE.match(ref):
            return None
        have = self.existing(ref)
        if have and not (self.refresh or changed):
            return have
        if self.dry_run:
            return have
        got = self.client.thumbnail(kind, ref, self.size)
        if got is None:
            return have
        body, ctype = got
        ext = EXTENSIONS.get(ctype)
        if not ext or not body:
            log.warning("thumbnail for %s has unexpected type %r; skipped", ref, ctype)
            return have
        self.remove(ref)
        name = f"{ref}.{ext}"
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(tmp, 0o644)
        os.replace(tmp, self.dir / name)
        self.fetched += 1
        return name

    def remove(self, ref: str) -> None:
        if self.dry_run:
            return
        ref = ref.lower()
        if not REF_RE.match(ref):
            return
        for ext in set(EXTENSIONS.values()):
            (self.dir / f"{ref}.{ext}").unlink(missing_ok=True)


def prune(directory: Path, keep_refs: set[str]) -> int:
    """After a complete harvest, delete cached thumbnails of entities that are no longer indexed."""
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    removed = 0
    for path in directory.iterdir():
        ref, _, ext = path.name.rpartition(".")
        if path.is_file() and ext in EXTENSIONS.values() and REF_RE.match(ref) and ref not in keep_refs:
            path.unlink()
            removed += 1
    if removed:
        log.info("removed %d thumbnails of records no longer in the index", removed)
    return removed
