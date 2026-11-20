"""Preservica's folder tree, from the Entity API.

OAI-PMH doesn't say where an asset sits, so for each asset the resolver asks
the Entity API for its parent folder, then walks up to the root. Folders are
cached for the run, so each folder costs one request however many assets it
holds.

Only public folders appear in an asset's breadcrumbs. If a folder on the way up
is invisible to the service account, or its security tag isn't public, it and
everything above it are left out: their titles must not reach the public index.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .client import NotVisible, PreservicaClient

log = logging.getLogger(__name__)
MAX_DEPTH = 64


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@dataclass(frozen=True)
class EntityInfo:
    kind: str                 # io | so
    ref: str
    title: str | None
    description: str | None
    security_tag: str | None
    parent: str | None


def parse_entity(root: ET.Element, kind: str, ref: str) -> EntityInfo:
    """Read Ref, Title, Description, SecurityTag and Parent from an EntityResponse, whatever its XIP version."""
    wanted = "InformationObject" if kind == "io" else "StructuralObject"
    obj = next((e for e in root.iter() if _local(e.tag) == wanted), None)
    if obj is None:
        raise ValueError(f"Entity API response for {kind}:{ref} has no {wanted}")
    values: dict[str, str] = {}
    for child in obj:
        name = _local(child.tag)
        text = "".join(child.itertext()).strip()
        if text and name not in values:
            values[name] = text
    return EntityInfo(kind=kind, ref=values.get("Ref", ref), title=values.get("Title"),
                      description=values.get("Description"), security_tag=values.get("SecurityTag"),
                      parent=values.get("Parent"))


class Hierarchy:
    def __init__(self, client: PreservicaClient, public_tags: list[str], skip_top_levels: int = 0):
        self.client = client
        self.public = {t.lower() for t in public_tags}
        self.skip_top_levels = int(skip_top_levels or 0)
        self._folders: dict[str, EntityInfo | None] = {}
        self.requests = 0

    def is_public_tag(self, tag: str | None) -> bool:
        # An entity always has a security tag in Preservica; a missing one is treated as not public.
        return bool(tag) and tag.lower() in self.public

    def entity(self, kind: str, ref: str) -> EntityInfo | None:
        """Entity info, or None if the service account can't see it."""
        self.requests += 1
        try:
            return parse_entity(self.client.entity(kind, ref), kind, ref)
        except NotVisible:
            return None

    def folder(self, ref: str) -> EntityInfo | None:
        if ref not in self._folders:
            self._folders[ref] = self.entity("so", ref)
        return self._folders[ref]

    def chain(self, folder_ref: str | None) -> list[EntityInfo]:
        """Public folders from the top down to folder_ref (inclusive)."""
        path: list[EntityInfo] = []
        complete = False
        ref, seen = folder_ref, set()
        while ref:
            if ref in seen or len(path) >= MAX_DEPTH:
                log.warning("folder hierarchy above %s loops or is too deep; truncated", folder_ref)
                break
            seen.add(ref)
            info = self.folder(ref)
            if info is None or not self.is_public_tag(info.security_tag):
                # Hide this folder and everything above it.
                break
            path.append(info)
            ref = info.parent
        else:
            complete = True
        path.reverse()
        if complete and self.skip_top_levels:
            path = path[self.skip_top_levels:]
        return path

    @property
    def folders_seen(self) -> dict[str, EntityInfo]:
        return {ref: info for ref, info in self._folders.items() if info is not None}
