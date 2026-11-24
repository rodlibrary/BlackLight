"""Publish, update or withdraw one asset's IIIF images and manifest.

The public rule matches the catalog's ingest: the asset's security tag is public, every folder
above it is public, and its MODS doesn't say access is restricted. Anything else is withdrawn,
so a closed item never keeps a public image.
"""
from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import imaging
from .manifest import build_manifest
from .repository import EntityInfo
from .settings import PIPELINE_VERSION, Settings

log = logging.getLogger(__name__)


@dataclass
class Result:
    ref: str
    status: str           # published | unchanged | skipped | withdrawn | expanded | too_large
    detail: str = ""
    queued: list[str] = field(default_factory=list)


class PublicPolicy:
    """Remembers folder answers, so a batch of assets in one folder costs one lookup per folder."""

    def __init__(self, repo, settings: Settings):
        self.repo, self.tags = repo, {t.lower() for t in settings.public_security_tags}
        self._folders: dict[str, bool] = {}

    def folder_public(self, ref: str | None) -> bool:
        chain, ok = [], True
        while ref:
            if ref in self._folders:
                ok = self._folders[ref]
                break
            chain.append(ref)
            info = self.repo.folder(ref)
            if info is None or not self.tag_ok(info.security_tag):
                ok = False
                break
            ref = info.parent
        for r in chain:        # each folder in the chain is at or below the first closed one, if any
            self._folders[r] = ok
        return ok

    def tag_ok(self, tag: str | None) -> bool:
        return (tag or "").lower() in self.tags

    def entity_public(self, info: EntityInfo | None) -> bool:
        return bool(info) and self.tag_ok(info.security_tag) and self.folder_public(info.parent)


def fingerprint(files, fields: dict | None = None) -> str:
    """Changes when a file, the descriptive metadata or the pipeline version changes."""
    raw = json.dumps([PIPELINE_VERSION, fields or {}] + [[f.content_object, f.filename, f.length,
                                                          sorted(f.fixity.items())] for f in files],
                     sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def image_id(ref: str, n: int) -> str:
    return f"{ref}_{n:04d}"


def withdraw(ref: str, store, settings: Settings, reason: str) -> Result:
    tiles = store.list_tiles(f"{ref}_")
    had = store.head(settings.manifest_key(ref)) is not None
    store.delete_tiles(tiles)
    store.delete_json([settings.manifest_key(ref), settings.status_key(ref)])
    if had or tiles:
        store.invalidate([f"/{settings.manifest_key(ref)}", f"/iiif/2/{ref}_*", f"/iiif/3/{ref}_*"])
        log.info("%s: withdrawn (%s)", ref, reason)
    return Result(ref, "withdrawn", reason)


def _skip(ref: str, store, settings: Settings, reason: str, fp: str = "") -> Result:
    """No images to publish: remove any old ones, and leave a note so the nightly run doesn't retry it."""
    withdraw(ref, store, settings, reason)
    store.put_json(settings.status_key(ref), {"ref": ref, "status": "skipped", "reason": reason},
                   {"fingerprint": fp, "pipeline-version": PIPELINE_VERSION})
    return Result(ref, "skipped", reason)


def process(ref: str, repo, store, settings: Settings, *, enqueue: Callable[[list[str]], None] | None = None,
            policy: PublicPolicy | None = None, force: bool = False) -> Result:
    policy = policy or PublicPolicy(repo, settings)
    info = repo.asset(ref)

    if info is None:
        folder = repo.folder(ref)
        if folder is not None:
            # A folder moved or changed its tag: re-check everything under it.
            refs = list(_assets_under(repo, ref))
            if enqueue and refs:
                enqueue(refs)
            return Result(ref, "expanded", f"{len(refs)} assets", queued=refs)
        return withdraw(ref, store, settings, "not found")

    if not policy.entity_public(info):
        return withdraw(ref, store, settings, "not public")

    fields = repo.metadata(ref)
    if fields.get("restricted"):
        return withdraw(ref, store, settings, "MODS says access is restricted")

    files = repo.files(ref, settings.representation_order)
    images = [f for f in files if imaging.can_convert(f.suffix)]
    if not images:
        kinds = ", ".join(sorted({f.suffix or "?" for f in files})) or "no files"
        return _skip(ref, store, settings, f"no convertible images ({kinds})")

    fp, files_fp = fingerprint(images, fields), fingerprint(images)
    old = store.head(settings.manifest_key(ref)) or {}
    if not force and old.get("fingerprint") == fp:
        return Result(ref, "unchanged")

    pages = None
    if not force and old.get("files") == files_fp:
        pages = _pages_from(store.get_json(settings.manifest_key(ref)), images, fields, info)   # metadata only
    converted = pages is None
    if converted:
        too_big = [f.filename for f in images if settings.max_source_bytes and f.length > settings.max_source_bytes]
        if too_big:
            return Result(ref, "too_large", ", ".join(too_big))
        pages = []
        with tempfile.TemporaryDirectory(prefix="iiif-") as tmp:
            for n, f in enumerate(images, 1):
                src = Path(tmp) / f"src{f.suffix}"
                out = Path(tmp) / "out.tif"
                repo.download(f, str(src))
                width, height = imaging.to_pyramid_tiff(str(src), str(out), settings.tile_size, settings.jpeg_quality)
                iid = image_id(ref, n)
                store.put_tile(f"{iid}.tif", str(out))
                pages.append({"image_id": iid, "width": width, "height": height,
                              "label": _label(n, images, fields, info)})
                src.unlink(missing_ok=True)
                out.unlink(missing_ok=True)
        keep = {f"{p['image_id']}.tif" for p in pages}
        stale = [k for k in store.list_tiles(f"{ref}_") if k not in keep]
        store.delete_tiles(stale)                       # an item that lost pages

    landing = settings.landing_url_template.format(uuid=ref) if settings.landing_url_template else None
    manifest = build_manifest(settings, ref, fields, info.title, pages, landing)
    store.put_json(settings.manifest_key(ref), manifest,
                   {"fingerprint": fp, "files": files_fp, "pipeline-version": PIPELINE_VERSION})
    store.delete_json([settings.status_key(ref)])
    if old:     # cached copies of the old manifest, and of the old images if they were redone
        store.invalidate([f"/{settings.manifest_key(ref)}"]
                         + ([f"/iiif/2/{ref}_*", f"/iiif/3/{ref}_*"] if converted else []))
    log.info("%s: published %d image(s)", ref, len(pages))
    return Result(ref, "published", f"{len(pages)} image(s)")


def _label(n: int, images, fields: dict, info: EntityInfo) -> str:
    return f"Image {n}" if len(images) > 1 else (fields.get("title") or info.title)


def _pages_from(manifest: dict | None, images, fields: dict, info: EntityInfo) -> list[dict] | None:
    """The image sizes from the last manifest, when only the metadata has changed."""
    pages = []
    try:
        for n, canvas in enumerate((manifest or {}).get("items", []), 1):
            service = canvas["items"][0]["items"][0]["body"]["service"][0]
            iid = (service.get("id") or service.get("@id") or "").rsplit("/", 1)[-1]
            pages.append({"image_id": iid, "width": canvas["width"], "height": canvas["height"],
                          "label": _label(n, images, fields, info)})
    except (KeyError, IndexError, TypeError):
        return None
    return pages if len(pages) == len(images) else None


def _assets_under(repo, folder_ref: str):
    stack = [folder_ref]
    while stack:
        for kind, ref in repo.children(stack.pop()):
            if kind == "folder":
                stack.append(ref)
            else:
                yield ref
