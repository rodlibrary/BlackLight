"""Normalize the many date forms sources send into sortable dates and year lists."""
from __future__ import annotations

import datetime as dt
import re

# Longest span of years written to year_isim; wider ranges are treated as undated
# for faceting so a "1800-2020" record doesn't flood every year.
MAX_YEAR_SPAN = 200

_ISO = re.compile(r"^\s*(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?\s*$")
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_YEAR = re.compile(r"^\s*([A-Za-z]{3,9})\.?\s+(\d{4})\s*$")


def parse_date(value: str | None, *, end: bool = False) -> dt.date | None:
    """Parse YYYY, YYYY-MM, YYYY-MM-DD, ISO datetimes or 'Month YYYY'.

    Partial dates resolve to the first day of the period, or the last day when
    ``end`` is true, so a range of "1952" to "1952" covers the whole year.
    """
    if not value:
        return None
    value = str(value).strip()
    m = _ISO.match(value)
    if m:
        y, mo, d = int(m.group(1)), m.group(2), m.group(3)
        try:
            if d:
                return dt.date(y, int(mo), int(d))
            if mo:
                mo = int(mo)
                if end:
                    nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
                    return nxt - dt.timedelta(days=1)
                return dt.date(y, mo, 1)
            return dt.date(y, 12, 31) if end else dt.date(y, 1, 1)
        except ValueError:
            return None
    m = _MONTH_YEAR.match(value)
    if m and m.group(1)[:3].lower() in _MONTHS:
        return parse_date(f"{m.group(2)}-{_MONTHS[m.group(1)[:3].lower()]:02d}", end=end)
    return None


def year_span(start: str | None, end: str | None = None, display: str | None = None) -> list[int]:
    """Every year covered by a start/end pair, falling back to years found in display text."""
    s = parse_date(start)
    e = parse_date(end, end=True) or (parse_date(start, end=True) if start else None)
    if s and e and e >= s:
        years = list(range(s.year, e.year + 1))
    elif s:
        years = [s.year]
    else:
        found = sorted({int(y) for y in _YEAR.findall(display or "") if 1000 <= int(y) <= 2100})
        years = list(range(found[0], found[-1] + 1)) if found else []
    if len(years) > MAX_YEAR_SPAN:
        return []
    return years


def solr_datetime(value: str | None) -> str | None:
    """Start of a date as a Solr datetime string (for sorting), or None."""
    d = parse_date(value)
    return f"{d.isoformat()}T00:00:00Z" if d else None
