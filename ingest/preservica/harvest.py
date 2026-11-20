"""Turn Preservica's OAI-PMH records, folder tree and thumbnails into Records and Deletions.

The public checks, in order (any failure removes the record from the index):
  1. the service account's role: it should only see the tags you publish
  2. a SecurityTag in the OAI record that isn't in public_security_tags
  3. a MODS accessCondition "restriction on access" saying restricted, closed or embargoed
  4. with resolve_hierarchy: the entity's own SecurityTag from the Entity API,
     and a 403/404 from it (the account can no longer see the entity)
Breadcrumbs include only public folders (see hierarchy.py).
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Iterator

from ..core import Deletion, Record, record_id
from .client import PreservicaClient
from .hierarchy import EntityInfo, Hierarchy
from .metadata import from_oai_record, media_type_for
from .oai import NS, OAI_ID, list_records
from .thumbnails import ThumbnailCache

log = logging.getLogger(__name__)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def security_tags(record: ET.Element) -> list[str]:
    """Any SecurityTag values in the record's header/about/XIP, whatever their namespace."""
    out = []
    for e in record.iter():
        if _local(e.tag) == "SecurityTag":
            t = "".join(e.itertext()).strip()
            if t:
                out.append(t)
    return out


def _fill(template: str | None, **values) -> str | None:
    if not template:
        return None
    try:
        return template.format(**values) or None
    except (KeyError, IndexError, ValueError):
        log.warning("bad URL template %r: use {uuid}", template)
        return None


def prefixes(settings: dict) -> list[str]:
    p = settings.get("metadata_prefix") or "MODS"
    return [p] if isinstance(p, str) else list(p)


class Harvester:
    def __init__(self, settings: dict, source: str, client: PreservicaClient | None = None, *,
                 since: str | None = None, dry_run: bool = False, refresh_thumbnails: bool = False):
        self.s = settings
        self.source = source
        self.since = since
        self.client = client or PreservicaClient(settings)
        self.public = {t.lower() for t in settings.get("public_security_tags", ["open"])}
        self.hierarchy = (Hierarchy(self.client, list(self.public), settings.get("skip_top_levels", 0))
                          if settings.get("resolve_hierarchy", True) else None)
        self.thumbs = (ThumbnailCache(self.client, settings["thumbnail_dir"], settings.get("thumbnail_size", "medium"),
                                      refresh=refresh_thumbnails, dry_run=dry_run)
                       if settings.get("thumbnails") else None)
        self.handled: set[str] = set()          # record ids decided in this run (indexed or removed)
        self.chain_folders: dict[str, EntityInfo] = {}   # public folders that appear in breadcrumbs
        self.split_on = settings.get("dc_split", ";") or None

    # ------------------------------------------------------------------ driver

    def __iter__(self) -> Iterator[Record | Deletion]:
        for prefix in prefixes(self.s):
            log.info("harvesting metadataPrefix=%s%s", prefix, f" since {self.since}" if self.since else "")
            for rec in list_records(self.client, prefix, since=self.since, set_spec=self.s.get("oai_set") or None):
                item = self.item(rec)
                if item is not None:
                    yield item
        if self.hierarchy and self.s.get("include_folders", True):
            for ref, info in self.chain_folders.items():
                rid = record_id(self.source, ref)
                if rid not in self.handled:
                    self.handled.add(rid)
                    yield self.folder_record(info)
        if self.hierarchy:
            log.info("Entity API: %d requests, %d folders", self.hierarchy.requests, len(self.hierarchy.folders_seen))
        if self.thumbs:
            log.info("thumbnails downloaded: %d", self.thumbs.fetched)

    # ------------------------------------------------------------------ one OAI record

    def remove(self, rid: str, ref: str, reason: str) -> Deletion:
        self.handled.add(rid)
        if self.thumbs:
            self.thumbs.remove(ref)
        return Deletion(rid, reason, ref)

    def item(self, record: ET.Element) -> Record | Deletion | None:
        header = record.find("oai:header", NS)
        oai_id = (header.findtext("oai:identifier", "", NS) or "").strip() if header is not None else ""
        m = OAI_ID.match(oai_id)
        if not m:
            log.warning("skipping record with unexpected identifier %r", oai_id)
            return None
        kind, ref = m.groups()
        ref = ref.lower()
        rid = record_id(self.source, ref)
        if rid in self.handled:
            return None   # already decided by an earlier metadata prefix in this run

        if header.get("status") == "deleted":
            return self.remove(rid, ref, "deleted in Preservica")
        if kind == "so" and not self.s.get("include_folders", True):
            return None

        tags = security_tags(record)
        if tags and not any(t.lower() in self.public for t in tags):
            return self.remove(rid, ref, f"security tag {tags[0]!r} is not public")

        f = from_oai_record(record, self.split_on)
        if f is None:
            log.debug("%s has no MODS or Dublin Core in this response; skipped", oai_id)
            return None
        if f["restricted"]:
            return self.remove(rid, ref, "MODS accessCondition restricts access")

        info, chain = None, []
        if self.hierarchy:
            info = self.hierarchy.folder(ref) if kind == "so" else self.hierarchy.entity("io", ref)
            if info is None:
                return self.remove(rid, ref, "not visible to the service account")
            if not self.hierarchy.is_public_tag(info.security_tag):
                return self.remove(rid, ref, f"security tag {info.security_tag!r} is not public")
            if kind == "so":
                own = self.hierarchy.chain(ref)
                if not own or own[-1].ref.lower() != ref:
                    return self.remove(rid, ref, "folder is above skip_top_levels or under a hidden folder")
                chain = own[:-1]
            else:
                chain = self.hierarchy.chain(info.parent)
            for folder in chain:
                self.chain_folders.setdefault(folder.ref.lower(), folder)

        title = f["title"] or (info.title if info else None)
        if not title:
            log.warning("%s has no title; skipped", oai_id)
            return None
        self.handled.add(rid)
        return self.build(kind, ref, title, f, chain)

    # ------------------------------------------------------------------ building records

    def _hierarchy_fields(self, chain: list[EntityInfo]) -> dict:
        ids = [record_id(self.source, c.ref) for c in chain]
        return {
            "parent_id": ids[-1] if ids else None,
            "ancestor_ids": ids,
            "ancestor_titles": [c.title or "Untitled folder" for c in chain],
        }

    def _thumbnail(self, kind: str, ref: str, changed: bool) -> str | None:
        if not self.thumbs:
            return None
        return self.thumbs.get(kind, ref, changed=changed)

    def build(self, kind: str, ref: str, title: str, f: dict, chain: list[EntityInfo], *,
              changed: bool | None = None) -> Record:
        # Records an incremental harvest returns have changed, so their thumbnails are fetched again.
        changed = self.since is not None if changed is None else changed
        is_folder = kind == "so"
        collection, collection_id = [], None
        how = self.s.get("collection_from", "hierarchy")
        if how in ("hierarchy", "both") and chain:
            collection.append(chain[0].title or "Untitled folder")
            collection_id = record_id(self.source, chain[0].ref)
        elif how in ("hierarchy", "both") and is_folder and self.hierarchy:
            # A top-level folder is its own collection, so the facet finds the collection record too.
            collection.append(title)
            collection_id = record_id(self.source, ref)
        if how in ("mods", "both") or (how == "hierarchy" and not chain and not is_folder):
            if f["collection"]:
                collection.append(f["collection"])
                collection_id = collection_id or f["collection_id"]

        media_type = None if is_folder else media_type_for(f)
        values = {"uuid": ref}
        media = None if is_folder else _fill(self.s.get("media_url_template"), **values)
        landing = _fill(self.s.get("folder_landing_url_template" if is_folder else "landing_url_template"), **values)
        thumb_url = _fill(self.s.get("thumbnail_url_template"), **values)
        ids = f["identifiers"]
        aspace = ids.get("aspace") or ids.get("archivesspace") or []

        return Record(
            id=record_id(self.source, ref),
            source=self.source,
            source_label=self.s.get("label", "Preservica"),
            title=title,
            resource_type=[f["resource_type"] or ("mixed material" if is_folder else "text")],
            entity_type="folder" if is_folder else "asset",
            preservica_ref=ref,
            **self._hierarchy_fields(chain),
            creators=f["creators"],
            contributors=f["contributors"],
            publishers=f["publishers"],
            date_display=f["date_display"],
            date_start=f["date_start"],
            date_end=f["date_end"],
            subjects=f["subjects"],
            places=f["places"],
            genres=f["genres"],
            abstract=f["abstract"],
            notes=f["notes"],
            languages=f["languages"],
            collection=collection,
            collection_id=collection_id,
            rights_uri=f["rights_uri"],
            rights_note=f["rights_note"],
            identifiers=[f"oai:{kind}:{ref}"] + [v for vals in ids.values() for v in vals],
            doi=next(iter(ids.get("doi", [])), None),
            aspace_ref=next(iter(aspace), None),
            physical_location=f["physical_location"],
            shelf_locator=f["shelf_locator"],
            url=landing,
            media_url=media,
            media_type=media_type if media else None,
            thumbnail_url=thumb_url or (media if media and media_type == "image" else None),
            thumbnail_file=None if thumb_url else self._thumbnail(kind, ref, changed),
            iiif_manifest_url=None if is_folder else _fill(self.s.get("iiif_manifest_url_template"), **values),
            file_formats=f["file_formats"],
            metadata_format=f["metadata_format"],
            extra={k: v for k, v in {
                "alternative_title_tesim": f["alt_titles"],
                "extent_ssm": f["extent"],
                "digital_origin_ssi": f["digital_origin"],
                "relation_ssm": f["relations"],
            }.items() if v},
        )

    def folder_record(self, info: EntityInfo) -> Record:
        """A collection record for a public folder known only from the Entity API."""
        ref = info.ref.lower()
        chain = self.hierarchy.chain(info.parent) if self.hierarchy else []
        description = info.description if info.description and not re.fullmatch(r"\s*", info.description) else None
        f = {
            "resource_type": "mixed material", "media_hint": "", "creators": [], "contributors": [],
            "publishers": [], "date_display": None, "date_start": None, "date_end": None, "subjects": [],
            "places": [], "genres": [], "abstract": description, "notes": [], "languages": [],
            "collection": None, "collection_id": None, "rights_uri": None, "rights_note": [],
            "identifiers": {}, "physical_location": None, "shelf_locator": None, "file_formats": [],
            "metadata_format": "entity", "alt_titles": [], "extent": [], "digital_origin": None, "relations": [],
        }
        # Not reported as changed by OAI-PMH: keep its cached thumbnail.
        return self.build("so", ref, info.title or "Untitled folder", f, chain, changed=False)


def harvest(settings: dict, source: str, since: str | None = None, client: PreservicaClient | None = None,
            **kwargs) -> Iterator[Record | Deletion]:
    return iter(Harvester(settings, source, client, since=since, **kwargs))
