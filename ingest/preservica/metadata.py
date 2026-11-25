"""Descriptive metadata from OAI-PMH records: MODS (preferred) or simple Dublin Core.

Both mappers return the same dict of plain values so harvest.py can build a
Record without caring which schema the record carried.
"""
from __future__ import annotations

import copy
import logging
import re
import xml.etree.ElementTree as ET

from ..core import infer_media_type
from ..geo import parse_point, parse_points
from .oai import NS

log = logging.getLogger(__name__)

# Prefixes used when the MODS download is written out (ElementTree's registry is global).
ET.register_namespace("mods", NS["mods"])
ET.register_namespace("xlink", NS["xlink"])
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
ET.register_namespace("oai_dc", NS["oai_dc"])
ET.register_namespace("dc", NS["dc"])
# A record larger than this isn't offered for download (Solr stores it in every document).
MAX_DOWNLOAD_BYTES = 256 * 1024

# Words in an access condition that mean the item must not be public.
RESTRICTED = re.compile(r"\b(restricted|closed|embargo(ed)?)\b", re.I)

MODS_TYPE_MAP = {
    "sound recording-musical": "sound recording",
    "sound recording-nonmusical": "sound recording",
}

# DCMI Type vocabulary (and common variants) onto the resource type facet.
DC_TYPE_MAP = {
    "text": "text",
    "image": "still image",
    "still image": "still image",
    "stillimage": "still image",
    "photograph": "still image",
    "sound": "sound recording",
    "audio": "sound recording",
    "moving image": "moving image",
    "movingimage": "moving image",
    "video": "moving image",
    "collection": "mixed material",
    "dataset": "dataset",
    "software": "software, multimedia",
    "interactive resource": "software, multimedia",
    "interactiveresource": "software, multimedia",
    "physical object": "three dimensional object",
    "physicalobject": "three dimensional object",
    "cartographic": "cartographic",
    "map": "cartographic",
    "web archive": "web archive",
    "website": "web archive",
}
RIGHTS_URI = re.compile(r"^https?://(www\.)?(rightsstatements\.org|creativecommons\.org)/", re.I)
DATE_RANGE = re.compile(r"^\s*(\d{4}(?:-\d{2}){0,2})\s*(?:/|-|–|to)\s*(\d{4}(?:-\d{2}){0,2})\s*$")


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    t = "".join(el.itertext()).strip()
    return re.sub(r"\s+", " ", t) or None


def _all(root: ET.Element, path: str) -> list[str]:
    return [t for t in (_text(e) for e in root.findall(path, NS)) if t]


# --------------------------------------------------------------------------- MODS

def _mods_dates(mods: ET.Element) -> tuple[str | None, str | None, str | None]:
    for tag in ("dateCreated", "dateIssued", "copyrightDate", "dateOther"):
        els = mods.findall(f"mods:originInfo/mods:{tag}", NS)
        if not els:
            continue
        start = next((_text(e) for e in els if e.get("point") == "start"), None)
        end = next((_text(e) for e in els if e.get("point") == "end"), None)
        plain = next((_text(e) for e in els if not e.get("point")), None)
        display = plain or (f"{start}–{end}" if start and end else start)
        if not start and plain and re.match(r"^\d{4}(-\d{2}){0,2}$", plain):
            start = plain
        return display, start, end
    return None, None, None


def _mods_names(mods: ET.Element, kind: str) -> list[str]:
    out = []
    for n in mods.findall("mods:name", NS):
        if (n.get("type") or "personal") != kind:
            continue
        display = _text(n.find("mods:displayForm", NS))
        parts = [p for p in _all(n, "mods:namePart") if p]
        if display or parts:
            out.append(display or ", ".join(parts))
    return out


def mods_fields(mods: ET.Element) -> dict:
    title_el = next((t for t in mods.findall("mods:titleInfo", NS) if not t.get("type")), None)
    title = _text(title_el.find("mods:title", NS)) if title_el is not None else None
    subtitle = _text(title_el.find("mods:subTitle", NS)) if title_el is not None else None
    display, start, end = _mods_dates(mods)

    use = next((a for a in mods.findall("mods:accessCondition", NS)
                if a.get("type") in ("use and reproduction", "useAndReproduction")), None)
    restriction = _all(mods, "mods:accessCondition[@type='restriction on access']") + \
        _all(mods, "mods:accessCondition[@type='restrictionOnAccess']")

    ids: dict[str, list[str]] = {}
    for i in mods.findall("mods:identifier", NS):
        if _text(i):
            ids.setdefault((i.get("type") or "local").lower(), []).append(_text(i))

    host = next((r for r in mods.findall("mods:relatedItem", NS) if r.get("type") == "host"), None)
    shelf = _all(mods, "mods:location/mods:shelfLocator") or \
        _all(mods, "mods:location/mods:holdingSimple/mods:copyInformation/mods:shelfLocator")
    type_of_resource = _text(mods.find("mods:typeOfResource", NS))
    formats = _all(mods, "mods:physicalDescription/mods:internetMediaType")

    return {
        "title": " : ".join(x for x in (title, subtitle) if x) or None,
        "alt_titles": [t for t in (_text(ti.find("mods:title", NS)) for ti in mods.findall("mods:titleInfo", NS)
                                   if ti.get("type")) if t],
        "creators": _mods_names(mods, "personal") + _mods_names(mods, "corporate") + _mods_names(mods, "family"),
        "contributors": [],
        "publishers": _all(mods, "mods:originInfo/mods:publisher"),
        "resource_type": MODS_TYPE_MAP.get((type_of_resource or "").strip(), (type_of_resource or "").strip()) or None,
        "media_hint": " ".join([type_of_resource or ""] + formats),
        "genres": _all(mods, "mods:genre"),
        "date_display": display, "date_start": start, "date_end": end,
        "languages": _all(mods, "mods:language/mods:languageTerm"),
        "extent": _all(mods, "mods:physicalDescription/mods:extent"),
        "digital_origin": _text(mods.find("mods:physicalDescription/mods:digitalOrigin", NS)),
        "file_formats": formats,
        "abstract": _text(mods.find("mods:abstract", NS)),
        "notes": _all(mods, "mods:note"),
        "subjects": (_all(mods, "mods:subject/mods:topic")
                     + [", ".join(_all(n, "mods:namePart")) for n in mods.findall("mods:subject/mods:name", NS)
                        if _all(n, "mods:namePart")]
                     + _all(mods, "mods:subject/mods:temporal")),
        "places": _all(mods, "mods:subject/mods:geographic") + _all(mods, "mods:subject/mods:hierarchicalGeographic/*"),
        "rights_uri": use.get(f"{{{NS['xlink']}}}href") if use is not None else None,
        "rights_note": [_text(use)] if use is not None and _text(use) else [],
        "restricted": any(RESTRICTED.search(r) for r in restriction),
        "identifiers": ids,
        "collection": _text(host.find("mods:titleInfo/mods:title", NS)) if host is not None else None,
        "collection_id": _text(host.find("mods:identifier", NS)) if host is not None else None,
        "physical_location": _text(mods.find("mods:location/mods:physicalLocation", NS)),
        "shelf_locator": shelf[0] if shelf else None,
        "relations": [],
        "coordinates": parse_points(_all(mods, "mods:subject/mods:cartographics/mods:coordinates")),
        "metadata_format": "mods",
    }


def check_strip_paths(paths: list[str] | None, setting: str = "mods_download_strip") -> list[str]:
    """A *_download_strip setting, checked: each entry must be a valid ElementTree path."""
    out = []
    for p in paths or []:
        try:
            ET.Element("check").findall(str(p), NS)
        except (SyntaxError, KeyError, TypeError) as exc:
            raise ValueError(f"{setting}: {p!r} is not a valid path ({exc})") from exc
        out.append(str(p))
    return out


def metadata_document(root: ET.Element, keep_ns: tuple[str, ...], strip: list[str] | None = None,
                      record_ref: str = "") -> str | None:
    """A harvested metadata record as a standalone XML document, for the site's "Download metadata" links.

    It is the record Preservica's OAI-PMH provider returned for this public entity, with two changes:
      - elements outside `keep_ns` are dropped (e.g. other schemas inside mods:extension), so the
        file carries no foreign markup such as XHTML
      - elements matching `strip` (paths relative to the root, e.g. "mods:note[@type='admin']")
        are dropped, for fields the library keeps off the public site
    The harvested element is left unchanged. Returns None if the result is larger than MAX_DOWNLOAD_BYTES.
    """
    root = copy.deepcopy(root)
    remove = {id(e) for path in (strip or []) for e in root.findall(path, NS)}
    prefixes = tuple(f"{{{ns}}}" for ns in keep_ns)
    for parent in list(root.iter()):
        for child in list(parent):
            if id(child) in remove or not str(child.tag).startswith(prefixes):
                parent.remove(child)
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    if len(text.encode("utf-8")) > MAX_DOWNLOAD_BYTES:
        log.warning("%s: metadata is larger than %d KB; no download", record_ref, MAX_DOWNLOAD_BYTES // 1024)
        return None
    return text


def mods_document(mods: ET.Element, strip: list[str] | None = None, record_ref: str = "") -> str | None:
    """<mods:mods> as a download: MODS elements only."""
    return metadata_document(mods, (NS["mods"],), strip, record_ref)


def dc_document(dc: ET.Element, strip: list[str] | None = None, record_ref: str = "") -> str | None:
    """<oai_dc:dc> as a download: Dublin Core elements only."""
    return metadata_document(dc, (NS["dc"],), strip, record_ref)


# --------------------------------------------------------------------------- Dublin Core

def _split(values: list[str], sep: str | None) -> list[str]:
    if not sep:
        return values
    out = []
    for v in values:
        out.extend(p.strip() for p in v.split(sep) if p.strip())
    return out


def dc_fields(dc: ET.Element, split_on: str | None = ";") -> dict:
    """Map an <oai_dc:dc> element. Repeated subjects separated by `split_on` are split."""
    titles = _all(dc, "dc:title")
    descriptions = _all(dc, "dc:description")
    dates = _all(dc, "dc:date")
    display = dates[0] if dates else None
    start = end = None
    if display:
        m = DATE_RANGE.match(display)
        if m:
            start, end = m.groups()
        elif re.match(r"^\d{4}(-\d{2}){0,2}", display):
            start = display[:10]

    types = _all(dc, "dc:type")
    rtype = next((DC_TYPE_MAP[t.lower()] for t in types if t.lower() in DC_TYPE_MAP), None)
    formats = _all(dc, "dc:format")
    rights = _all(dc, "dc:rights")
    rights_uri = next((r for r in rights if RIGHTS_URI.match(r)), None)

    ids: dict[str, list[str]] = {}
    for i in _all(dc, "dc:identifier"):
        kind = "doi" if re.match(r"^(doi:|https?://(dx\.)?doi\.org/|10\.\d{4,})", i, re.I) else "local"
        ids.setdefault(kind, []).append(re.sub(r"^doi:\s*", "", i, flags=re.I))

    return {
        "title": titles[0] if titles else None,
        "alt_titles": titles[1:],
        "creators": _all(dc, "dc:creator"),
        "contributors": _all(dc, "dc:contributor"),
        "publishers": _all(dc, "dc:publisher"),
        "resource_type": rtype,
        "media_hint": " ".join(types + formats),
        "genres": [t for t in types if t.lower() not in DC_TYPE_MAP],
        "date_display": display, "date_start": start, "date_end": end,
        "languages": _split(_all(dc, "dc:language"), split_on),
        "extent": [],
        "digital_origin": None,
        "file_formats": formats,
        "abstract": descriptions[0] if descriptions else None,
        "notes": descriptions[1:],
        "subjects": _split(_all(dc, "dc:subject"), split_on),
        "places": _split([c for c in _all(dc, "dc:coverage") if not parse_point(c)], split_on),
        "rights_uri": rights_uri,
        "rights_note": [r for r in rights if r != rights_uri],
        "restricted": False,  # dc:rights is a use statement, not an access condition
        "identifiers": ids,
        "collection": None,
        "collection_id": None,
        "physical_location": None,
        "shelf_locator": None,
        "relations": _all(dc, "dc:relation") + _all(dc, "dc:source"),
        # Coverage is split on dc_split, but a "lat; lon" pair must stay whole, so parse the raw values.
        "coordinates": parse_points(_all(dc, "dc:coverage")),
        "metadata_format": "oai_dc",
    }


def from_oai_record(record: ET.Element, split_on: str | None = ";") -> dict | None:
    """Fields from the record's MODS or Dublin Core, whichever it carries; None if neither."""
    mods = record.find("oai:metadata/mods:mods", NS)
    if mods is not None:
        return mods_fields(mods)
    dc = record.find("oai:metadata/oai_dc:dc", NS)
    if dc is not None:
        return dc_fields(dc, split_on)
    return None


def media_type_for(fields: dict) -> str | None:
    return infer_media_type(fields.get("media_hint"), fields.get("resource_type"))
