"""What the pipeline needs from Preservica, through pyPreservica.

`Repository` is the only class that talks to Preservica; the tests use a fake with the same methods.
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterator

log = logging.getLogger(__name__)

MODS_NS = "http://www.loc.gov/mods/v3"
DC_NS = "http://www.openarchives.org/OAI/2.0/oai_dc/"


@dataclass
class EntityInfo:
    ref: str
    kind: str                     # "asset" or "folder"
    title: str = ""
    description: str = ""
    security_tag: str = ""
    parent: str | None = None


@dataclass
class SourceFile:
    """One file to turn into an image: a content object's file in the chosen representation."""
    content_object: str
    filename: str
    length: int
    fixity: dict = field(default_factory=dict)
    representation: str = ""
    handle: object = None         # pyPreservica's Bitstream, for download()

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.filename).suffix.lower()


def metadata_fields(xml_text: str | None) -> dict:
    """MODS or Dublin Core, mapped with the ingest's own mappers so titles and rights match the catalog."""
    if not xml_text:
        return {}
    from ingest.preservica.metadata import dc_fields, mods_fields

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.warning("unreadable metadata fragment")
        return {}
    mods = root if root.tag == f"{{{MODS_NS}}}mods" else root.find(f".//{{{MODS_NS}}}mods")
    if mods is not None:
        return mods_fields(mods)
    dc = root if root.tag == f"{{{DC_NS}}}dc" else root.find(f".//{{{DC_NS}}}dc")
    if dc is not None:
        return dc_fields(dc)
    return {}


class Repository:
    """pyPreservica-backed access to entities, representations and files."""

    def __init__(self, entity_api=None):
        if entity_api is None:
            from pyPreservica import EntityAPI

            from .settings import read_secret

            entity_api = EntityAPI(
                username=os.environ.get("PRESERVICA_USERNAME")
                or read_secret("PRESERVICA_SECRET_ARN", "PRESERVICA_USERNAME", "username"),
                password=read_secret("PRESERVICA_SECRET_ARN", "PRESERVICA_PASSWORD", "password"),
                tenant=os.environ.get("PRESERVICA_TENANT"),
                server=os.environ.get("PRESERVICA_SERVER"),
            )
        self.api = entity_api

    # -- entities ---------------------------------------------------------------------------
    @staticmethod
    def _info(e, kind: str) -> EntityInfo:
        return EntityInfo(ref=e.reference, kind=kind, title=e.title or "", description=e.description or "",
                          security_tag=e.security_tag or "", parent=e.parent)

    def asset(self, ref: str) -> EntityInfo | None:
        from pyPreservica.common import ReferenceNotFoundException

        try:
            return self._info(self.api.asset(ref), "asset")
        except ReferenceNotFoundException:
            return None

    def folder(self, ref: str) -> EntityInfo | None:
        from pyPreservica.common import ReferenceNotFoundException

        try:
            return self._info(self.api.folder(ref), "folder")
        except ReferenceNotFoundException:
            return None

    def children(self, folder_ref: str | None) -> Iterator[tuple[str, str]]:
        """(kind, ref) of a folder's immediate children; None = the top-level folders."""
        from pyPreservica.common import EntityType

        for e in self.api.descendants(folder_ref):
            kind = "folder" if e.entity_type == EntityType.FOLDER else "asset"
            yield kind, e.reference

    def metadata(self, ref: str) -> dict:
        asset = self.api.asset(ref)
        for schema in (MODS_NS, DC_NS):
            try:
                fields = metadata_fields(self.api.metadata_for_entity(asset, schema))
            except Exception as exc:  # a missing or odd fragment shouldn't stop the image
                log.warning("%s: couldn't read %s metadata: %s", ref, schema, exc)
                continue
            if fields:
                return fields
        return {}

    # -- files ------------------------------------------------------------------------------
    def files(self, ref: str, order: list[str]) -> list[SourceFile]:
        """The active generation's first file of each content object, from the first representation
        in `order` that has any (usually Access, then Preservation)."""
        asset = self.api.asset(ref)
        reps = {}
        for rep in self.api.representations(asset):
            name = getattr(rep.rep_type, "value", rep.rep_type)
            reps.setdefault(str(name).lower(), []).append(rep)
        for wanted in order:
            for rep in reps.get(wanted.lower(), []):
                out = []
                for co in self.api.content_objects(rep):
                    gens = [g for g in self.api.generations(co) if g.active] or self.api.generations(co)
                    if not gens or not gens[-1].bitstreams:
                        continue
                    b = gens[-1].bitstreams[0]
                    out.append(SourceFile(content_object=co.reference, filename=b.filename, length=int(b.length or 0),
                                          fixity=dict(b.fixity or {}), representation=wanted, handle=b))
                if out:
                    return out
        return []

    def download(self, f: SourceFile, path: str) -> None:
        self.api.bitstream_content(f.handle, path)
