"""The record every Preservica entity maps into, and its Solr field names.

Field names use the dynamic-field suffixes of the bundled Solr schema
(solr/conf/schema.xml, see docs/solr-fields.md). Change a name here and in
blacklight/app/controllers/catalog_controller.rb together.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .dates import solr_datetime, year_span

# Controlled list for the "Type" facet. MODS typeOfResource and DCMI types map onto these.
RESOURCE_TYPES = {
    "text", "still image", "sound recording", "moving image", "cartographic",
    "notated music", "three dimensional object", "mixed material", "software, multimedia",
    "dataset", "web archive",
}
MEDIA_TYPES = {"image", "audio", "video", "pdf"}
ENTITY_TYPES = {"asset", "folder"}
# Facet label for each entity type.
ENTITY_LABELS = {"asset": "Item", "folder": "Collection"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
THUMBNAIL_FILE_RE = re.compile(r"^[0-9a-z-]+\.(jpg|png|gif|webp)$")


class RecordError(ValueError):
    """A record that cannot be indexed."""


def safe_url(value: str | None) -> str | None:
    """Return the URL only if it is absolute http(s); anything else (javascript:, data:, relative) is dropped."""
    if not value:
        return None
    value = str(value).strip()
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value
    return None


def _list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [value]
    out, seen = [], set()
    for v in items:
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _one(value) -> str | None:
    items = _list(value)
    return items[0] if items else None


def record_id(source: str, ref: str) -> str:
    """Solr id for a Preservica entity: '<source>-<uuid>', lowercased."""
    return f"{source}-{ref}".lower()


@dataclass
class Record:
    """One discoverable Preservica asset (information object) or folder (structural object)."""

    id: str
    source: str                      # machine name, e.g. "preservica"
    source_label: str                # display label, e.g. "Digital Archive"
    title: str
    resource_type: list[str]
    entity_type: str = "asset"       # asset | folder
    preservica_ref: str | None = None
    # Hierarchy, root first. Only public folders appear here (see hierarchy.py).
    parent_id: str | None = None
    ancestor_ids: list[str] = field(default_factory=list)
    ancestor_titles: list[str] = field(default_factory=list)
    creators: list[str] = field(default_factory=list)
    contributors: list[str] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    date_display: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    subjects: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    abstract: str | None = None
    notes: list[str] = field(default_factory=list)
    full_text: str | None = None
    languages: list[str] = field(default_factory=list)
    collection: list[str] = field(default_factory=list)
    collection_id: str | None = None
    rights_uri: str | None = None
    rights_note: list[str] = field(default_factory=list)
    access_status: str = "public"
    identifiers: list[str] = field(default_factory=list)
    doi: str | None = None
    aspace_ref: str | None = None
    physical_location: str | None = None
    shelf_locator: str | None = None
    url: str | None = None             # public landing page (e.g. Preservica Universal Access)
    media_url: str | None = None       # access copy to preview or play
    media_type: str | None = None      # image | audio | video | pdf
    thumbnail_url: str | None = None   # absolute thumbnail URL from a template
    thumbnail_file: str | None = None  # cached thumbnail file name, served by the Rails app
    captions_url: str | None = None    # WebVTT for audio/video
    iiif_manifest_url: str | None = None
    georeference_url: str | None = None   # IIIF Georeference Annotation (e.g. Allmaps) for a scanned map
    coordinates: list[tuple[float, float]] = field(default_factory=list)   # (latitude, longitude) points
    file_formats: list[str] = field(default_factory=list)
    metadata_format: str | None = None  # mods | oai_dc | entity
    mods_xml: str | None = None         # the public MODS record, for the site's metadata download
    dc_xml: str | None = None           # the public Dublin Core record, for the same
    extra: dict = field(default_factory=dict)   # additional Solr fields, already suffixed

    def validate(self) -> None:
        if not self.id or not ID_RE.match(self.id):
            raise RecordError(f"invalid id {self.id!r}: use lowercase letters, digits, '.', '_' or '-'")
        if not self.title or not self.title.strip():
            raise RecordError(f"{self.id}: title is required")
        if not self.resource_type:
            raise RecordError(f"{self.id}: resource_type is required")
        unknown = [t for t in self.resource_type if t not in RESOURCE_TYPES]
        if unknown:
            raise RecordError(f"{self.id}: unknown resource_type {unknown}")
        if self.entity_type not in ENTITY_TYPES:
            raise RecordError(f"{self.id}: unknown entity_type {self.entity_type!r}")
        if self.media_type and self.media_type not in MEDIA_TYPES:
            raise RecordError(f"{self.id}: unknown media_type {self.media_type!r}")
        if len(self.ancestor_ids) != len(self.ancestor_titles):
            raise RecordError(f"{self.id}: ancestor_ids and ancestor_titles differ in length")
        bad_points = [p for p in self.coordinates
                      if len(p) != 2 or not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180)]
        if bad_points:
            raise RecordError(f"{self.id}: coordinates out of range: {bad_points}")
        if self.thumbnail_file and not THUMBNAIL_FILE_RE.match(self.thumbnail_file):
            raise RecordError(f"{self.id}: unexpected thumbnail file name {self.thumbnail_file!r}")
        bad = [k for k in self.extra if not re.search(r"_(tesim|ssim|ssm|ssi|isim|isi|dtsi|teim|bsi)$", k)]
        if bad:
            raise RecordError(f"{self.id}: extra fields need a Solr suffix: {bad}")

    @property
    def is_public(self) -> bool:
        return self.access_status == "public"

    def to_solr(self, run_id: str) -> dict:
        """Solr document. Refuses non-public records: they must never reach the public index."""
        self.validate()
        if not self.is_public:
            raise RecordError(f"{self.id}: access_status {self.access_status!r} is not public")

        creators = _list(self.creators)
        subjects = _list(self.subjects)
        years = year_span(self.date_start, self.date_end, self.date_display)
        media_url = safe_url(self.media_url)
        doc = {
            "id": self.id,
            "source_ssi": self.source,
            "source_ssim": [self.source_label],
            "entity_type_ssi": self.entity_type,
            "entity_type_ssim": [ENTITY_LABELS[self.entity_type]],
            "preservica_ref_ssi": _one(self.preservica_ref),
            "parent_id_ssi": _one(self.parent_id),
            "ancestor_ids_ssim": list(self.ancestor_ids),
            "ancestor_titles_ssm": list(self.ancestor_titles),
            "depth_isi": len(self.ancestor_ids),
            "resource_type_ssim": _list(self.resource_type),
            "title_tesim": [self.title.strip()],
            "title_ssort": self.title.strip(),
            "creator_tesim": creators,
            "creator_ssim": creators,
            "creator_ssort": creators[0] if creators else None,
            "contributor_tesim": _list(self.contributors),
            "contributor_ssim": _list(self.contributors),
            "publisher_ssim": _list(self.publishers),
            "genre_ssim": _list(self.genres),
            "subject_tesim": subjects,
            "subject_ssim": subjects,
            "place_ssim": _list(self.places),
            "abstract_tesim": _list(self.abstract),
            "note_tesim": _list(self.notes),
            "full_text_teim": _list(self.full_text),
            "date_display_ssm": _list(self.date_display),
            "date_sort_dtsi": solr_datetime(self.date_start) or solr_datetime(self.date_display),
            "year_isim": years,
            "language_ssim": _list(self.languages),
            "collection_ssim": _list(self.collection),
            "collection_id_ssi": _one(self.collection_id),
            "rights_uri_ssi": safe_url(self.rights_uri),
            "rights_note_ssm": _list(self.rights_note),
            "access_status_ssi": self.access_status,
            "identifier_ssim": _list(self.identifiers + [self.doi] if self.doi else self.identifiers),
            "doi_ssi": _one(self.doi),
            "aspace_ref_ssi": _one(self.aspace_ref),
            "physical_location_ssm": _list(self.physical_location),
            "shelf_locator_ssm": _list(self.shelf_locator),
            "url_ssi": safe_url(self.url),
            "media_url_ssi": media_url,
            "media_type_ssi": self.media_type if media_url else None,
            "thumbnail_url_ssm": _list(safe_url(self.thumbnail_url)),
            "thumbnail_file_ssi": self.thumbnail_file,
            "has_thumbnail_bsi": bool(safe_url(self.thumbnail_url) or self.thumbnail_file),
            "captions_url_ssi": safe_url(self.captions_url),
            "iiif_manifest_ssi": safe_url(self.iiif_manifest_url),
            "georeference_url_ssi": safe_url(self.georeference_url),
            # "lat,lon" points: coordinates_srpt is the spatial index (map search), _ssm the stored copy.
            "coordinates_srpt": [f"{lat},{lon}" for lat, lon in self.coordinates],
            "coordinates_ssm": [f"{lat},{lon}" for lat, lon in self.coordinates],
            "has_coordinates_bsi": bool(self.coordinates),
            "file_format_ssim": _list(self.file_formats),
            "metadata_format_ssi": self.metadata_format,
            # Stored, not indexed (_ss string fields): served as the record's metadata downloads.
            "mods_xml_ss": self.mods_xml,
            "dc_xml_ss": self.dc_xml,
            "ingest_run_ssi": run_id,
            "indexed_at_dtsi": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        doc.update(self.extra)
        # Dropping empty values keeps documents and backups readable. False is kept.
        return {k: v for k, v in doc.items() if v not in (None, [], "")}


@dataclass(frozen=True)
class Deletion:
    """A record Preservica says is gone, or that is no longer public: remove it from the index."""

    id: str
    reason: str = "deleted"
    ref: str | None = None   # Preservica reference, so its cached thumbnail can go too


def infer_media_type(*hints: str | None) -> str | None:
    """Guess image/audio/video/pdf from formats, MIME types, resource types or a file URL."""
    text = " ".join(h.lower() for h in hints if h)
    if not text:
        return None
    if re.search(r"\bpdf\b|\.pdf\b|application/pdf", text):
        return "pdf"
    if re.search(r"video|moving ?image|\bfilm\b|\.(mp4|webm|mov|m3u8)\b", text):
        return "video"
    if re.search(r"audio|sound|\.(mp3|m4a|wav|ogg)\b", text):
        return "audio"
    if re.search(r"image|picture|photo|\.(jpe?g|png|gif|webp|tiff?)\b", text):
        return "image"
    return None
