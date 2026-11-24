"""Read point coordinates written in common catalogue forms.

Accepted (one point per value):
    41.5, -92.3            decimal latitude, longitude
    41.5 -92.3             the same, space separated
    41.5N, 92.3W           hemisphere letters instead of signs (either order: N 41.5)
    lat 41.5 lon -92.3     labelled
    POINT(-92.3 41.5)      WKT, longitude first
A four-number bounding box (W, E, N, S as in MODS cartographics decimal form,
or WKT ENVELOPE(minX, maxX, maxY, minY)) is reduced to its centre point.
Anything else, including degrees-minutes-seconds, is ignored rather than guessed.
"""
from __future__ import annotations

import re

NUM = r"[-+]?\d{1,3}(?:\.\d+)?"
_HEMI = re.compile(rf"^\s*(?:([NS])\s*)?({NUM})\s*([NS])?\s*[,; ]\s*(?:([EW])\s*)?({NUM})\s*([EW])?\s*$", re.I)
_WKT_POINT = re.compile(rf"^\s*POINT\s*\(\s*({NUM})\s+({NUM})\s*\)\s*$", re.I)
_ENVELOPE = re.compile(rf"^\s*ENVELOPE\s*\(\s*({NUM})\s*,\s*({NUM})\s*,\s*({NUM})\s*,\s*({NUM})\s*\)\s*$", re.I)
_LABELLED = re.compile(rf"lat(?:itude)?\s*[:=]?\s*({NUM}).*?lo?ng?(?:itude)?\s*[:=]?\s*({NUM})", re.I)
_FOUR = re.compile(rf"^\s*({NUM})\s*[,; ]\s*({NUM})\s*[,; ]\s*({NUM})\s*[,; ]\s*({NUM})\s*$")


def _valid(lat: float, lon: float) -> tuple[float, float] | None:
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return round(lat, 6), round(lon, 6)
    return None


def parse_point(value: str | None) -> tuple[float, float] | None:
    """(latitude, longitude) from one value, or None if it isn't a recognisable point."""
    if not value:
        return None
    text = str(value).strip()
    m = _WKT_POINT.match(text)
    if m:
        return _valid(float(m.group(2)), float(m.group(1)))
    m = _ENVELOPE.match(text)
    if m:
        min_x, max_x, max_y, min_y = map(float, m.groups())
        return _valid((max_y + min_y) / 2, (min_x + max_x) / 2)
    m = _FOUR.match(text)
    if m:
        west, east, north, south = map(float, m.groups())
        return _valid((north + south) / 2, (west + east) / 2)
    m = _LABELLED.search(text)
    if m:
        return _valid(float(m.group(1)), float(m.group(2)))
    m = _HEMI.match(text)
    if m:
        ns1, lat, ns2, ew1, lon, ew2 = m.groups()
        lat, lon = float(lat), float(lon)
        ns, ew = (ns1 or ns2 or "").upper(), (ew1 or ew2 or "").upper()
        if ns == "S":
            lat = -abs(lat)
        if ew == "W":
            lon = -abs(lon)
        return _valid(lat, lon)
    return None


def parse_points(values) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for v in values or []:
        p = parse_point(v)
        if p and p not in out:
            out.append(p)
    return out
