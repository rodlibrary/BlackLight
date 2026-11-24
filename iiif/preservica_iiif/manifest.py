"""IIIF Presentation 3 manifests, one per Preservica asset, with navPlace when it has coordinates."""
from __future__ import annotations

import re

PRESENTATION_CONTEXT = "http://iiif.io/api/presentation/3/context.json"
NAVPLACE_CONTEXT = "http://iiif.io/api/extension/navplace/context.json"

# IIIF's `rights` property only accepts these; anything else goes in the metadata as a note.
RIGHTS_URI = re.compile(r"^https?://(creativecommons\.org/(licenses|publicdomain)/|rightsstatements\.org/vocab/)")


def _lang(value) -> dict:
    values = value if isinstance(value, list) else [value]
    return {"none": [str(v) for v in values if v]}


def _en(value) -> dict:
    values = value if isinstance(value, list) else [value]
    return {"en": [str(v) for v in values if v]}


def _rights(uri: str | None) -> str | None:
    if not uri or not RIGHTS_URI.match(uri):
        return None
    return "http://" + uri.split("://", 1)[1]      # the spec's form is http://, even for https sites


def image_service(settings, image_id: str) -> dict:
    base = f"{settings.image_api_base}/{image_id}"
    if settings.image_api_version == 2:
        return {"@id": base, "@type": "ImageService2", "profile": "http://iiif.io/api/image/2/level2.json"}
    return {"id": base, "type": "ImageService3", "profile": "level2"}


def build_manifest(settings, ref: str, fields: dict, title: str, pages: list[dict],
                   landing_url: str | None = None) -> dict:
    """`pages`: [{"image_id", "width", "height", "label"}] in reading order."""
    mid = settings.manifest_url(ref)
    canvases = []
    for n, p in enumerate(pages, 1):
        cid = f"{mid}/canvas/{n}"
        full = f"{settings.image_api_base}/{p['image_id']}/full/max/0/default.jpg"
        canvases.append({
            "id": cid, "type": "Canvas", "label": _lang(p.get("label") or f"Image {n}"),
            "width": p["width"], "height": p["height"],
            "items": [{
                "id": f"{cid}/page", "type": "AnnotationPage",
                "items": [{
                    "id": f"{cid}/page/image", "type": "Annotation", "motivation": "painting", "target": cid,
                    "body": {"id": full, "type": "Image", "format": "image/jpeg",
                             "width": p["width"], "height": p["height"],
                             "service": [image_service(settings, p["image_id"])]},
                }],
            }],
        })

    m: dict = {
        "@context": PRESENTATION_CONTEXT,
        "id": mid, "type": "Manifest",
        "label": _lang(fields.get("title") or title or ref),
    }
    if fields.get("abstract"):
        m["summary"] = _lang(fields["abstract"])

    meta = []
    for label, key in (("Date", "date_display"), ("Creator", "creators"), ("Type", "resource_type"),
                       ("Genre", "genres"), ("Subject", "subjects"), ("Place", "places"),
                       ("Collection", "collection"), ("Rights", "rights_note")):
        value = fields.get(key)
        if value:
            meta.append({"label": _en(label), "value": _lang(value)})
    if meta:
        m["metadata"] = meta

    rights = _rights(fields.get("rights_uri"))
    if rights:
        m["rights"] = rights
    m["requiredStatement"] = {"label": _en("Attribution"), "value": _en(settings.attribution)}
    m["provider"] = [{
        "id": settings.provider_homepage, "type": "Agent", "label": _en(settings.provider_label),
        "homepage": [{"id": settings.provider_homepage, "type": "Text", "label": _en(settings.provider_label),
                      "format": "text/html"}],
    }]
    if landing_url:
        m["homepage"] = [{"id": landing_url, "type": "Text", "label": _en("View in Preservica"), "format": "text/html"}]
    if pages:
        first = pages[0]
        thumb = f"{settings.image_api_base}/{first['image_id']}/full/!400,400/0/default.jpg"
        m["thumbnail"] = [{"id": thumb, "type": "Image", "format": "image/jpeg",
                           "service": [image_service(settings, first["image_id"])]}]

    points = fields.get("coordinates") or []
    if points:
        m["@context"] = [NAVPLACE_CONTEXT, PRESENTATION_CONTEXT]
        m["navPlace"] = {
            "id": f"{mid}/feature-collection", "type": "FeatureCollection",
            "features": [{"id": f"{mid}/feature/{n}", "type": "Feature", "properties": {},
                          "geometry": {"type": "Point", "coordinates": [lon, lat]}}   # GeoJSON: longitude first
                         for n, (lat, lon) in enumerate(points, 1)],
        }
    m["items"] = canvases
    return m
