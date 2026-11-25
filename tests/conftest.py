import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingest.preservica.client import NotVisible  # noqa: E402


class FakeHits:
    def __init__(self, hits):
        self.hits = hits


class FakeSolr:
    """Just enough of pysolr.Solr: an in-memory dict of documents with term-free query support."""

    def __init__(self, docs=None):
        self.docs = {d["id"]: d for d in (docs or [])}
        self.commits = 0

    def add(self, docs, commit=False, **kw):
        for d in docs:
            self.docs[d["id"]] = d

    def _match(self, q):
        # Supports: source_ssi:"x"  and  source_ssi:"x" AND -ingest_run_ssi:"y"
        parts = [p.strip() for p in q.split(" AND ")]

        def ok(d):
            for p in parts:
                neg = p.startswith("-")
                field, value = p.lstrip("-").split(":", 1)
                hit = d.get(field) == value.strip('"')
                if hit == neg:
                    return False
            return True
        return [d for d in self.docs.values() if ok(d)]

    def search(self, q, rows=0, **kw):
        return FakeHits(len(self._match(q)))

    def delete(self, id=None, q=None, commit=False, **kw):
        if id is not None:
            for i in (id if isinstance(id, list) else [id]):
                self.docs.pop(i, None)
            return
        for d in self._match(q):
            del self.docs[d["id"]]

    def commit(self, **kw):
        self.commits += 1


# --------------------------------------------------------------------------- fake Preservica

OAI_HEAD = ('<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" '
            'xmlns:mods="http://www.loc.gov/mods/v3" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<responseDate>2026-11-20T18:00:00Z</responseDate>')
OAI_TAIL = "</OAI-PMH>"


def oai_record(oai_id, metadata="", tag=None, deleted=False):
    status = ' status="deleted"' if deleted else ""
    about = (f'<about><XIP xmlns="http://preservica.com/XIP/v6.0"><SecurityTag>{tag}</SecurityTag></XIP></about>'
             if tag else "")
    meta = f"<metadata>{metadata}</metadata>" if metadata and not deleted else ""
    return (f"<record><header{status}><identifier>{oai_id}</identifier>"
            f"<datestamp>2026-11-01T00:00:00Z</datestamp></header>{meta}{about}</record>")


def oai_page(records, token=None):
    tok = f"<resumptionToken>{token}</resumptionToken>" if token else "<resumptionToken/>"
    return ET.fromstring(f"{OAI_HEAD}<ListRecords>{''.join(records)}{tok}</ListRecords>{OAI_TAIL}")


def oai_error(code):
    return ET.fromstring(f'{OAI_HEAD}<error code="{code}">message</error>{OAI_TAIL}')


def entity_xml(kind, ref, title, tag="open", parent=None, description=None, version="7.0", fragments=()):
    el = "InformationObject" if kind == "io" else "StructuralObject"
    parts = [f"<xip:Ref>{ref}</xip:Ref>", f"<xip:Title>{title}</xip:Title>"]
    if description:
        parts.append(f"<xip:Description>{description}</xip:Description>")
    parts.append(f"<xip:SecurityTag>{tag}</xip:SecurityTag>")
    if parent:
        parts.append(f"<xip:Parent>{parent}</xip:Parent>")
    frags = "".join(f'<Fragment schema="{schema}">{url}</Fragment>' for schema, url in fragments)
    return ET.fromstring(
        f'<EntityResponse xmlns="http://preservica.com/EntityAPI/v{version}" '
        f'xmlns:xip="http://preservica.com/XIP/v{version}"><xip:{el}>{"".join(parts)}</xip:{el}>'
        f'<AdditionalInformation><Metadata>{frags}</Metadata></AdditionalInformation></EntityResponse>')


class FakePreservica:
    """Stands in for PreservicaClient. pages: {prefix: [page, ...]}; entities: {(kind, ref): Element}."""

    def __init__(self, pages=None, entities=None, thumbnails=None, fragments=None, get_records=None):
        self.pages = {k: list(v) for k, v in (pages or {}).items()}
        self.all_pages = {k: list(v) for k, v in (pages or {}).items()}   # for GetRecord
        # Records only GetRecord returns, e.g. folders missing from ListRecords: {prefix: [oai_record(...)]}
        for prefix, records in (get_records or {}).items():
            self.all_pages.setdefault(prefix, []).append(oai_page(records))
        self.entities = entities or {}
        self.thumbnails = thumbnails or {}
        self.fragments = fragments or {}
        self.oai_calls, self.entity_calls, self.thumbnail_calls, self.fragment_calls = [], [], [], []

    def oai(self, params):
        self.oai_calls.append(dict(params))
        if params.get("verb") == "GetRecord":
            return self.get_record(params["identifier"], params["metadataPrefix"])
        prefix = params.get("metadataPrefix") or self._last_prefix
        self._last_prefix = prefix
        queue = self.pages.get(prefix)
        if not queue:
            return oai_error("noRecordsMatch")
        return queue.pop(0)

    def get_record(self, identifier, prefix):
        """GetRecord answered from the ListRecords pages set up for that prefix."""
        for page in self.all_pages.get(prefix, []):
            for rec in page.iter("{http://www.openarchives.org/OAI/2.0/}record"):
                if rec.findtext("{http://www.openarchives.org/OAI/2.0/}header/"
                                "{http://www.openarchives.org/OAI/2.0/}identifier") == identifier:
                    return ET.fromstring(f"{OAI_HEAD}<GetRecord>{ET.tostring(rec, encoding='unicode')}"
                                         f"</GetRecord>{OAI_TAIL}")
        return oai_error("idDoesNotExist")

    def entity(self, kind, ref):
        self.entity_calls.append((kind, ref))
        if (kind, ref) not in self.entities:
            raise NotVisible(f"{kind}:{ref}")
        return self.entities[(kind, ref)]

    def fragment(self, url):
        self.fragment_calls.append(url)
        if url not in self.fragments:
            raise NotVisible(url)
        return self.fragments[url]

    def thumbnail(self, kind, ref, size="medium"):
        self.thumbnail_calls.append((kind, ref, size))
        return self.thumbnails.get(ref)


@pytest.fixture
def fake_solr():
    return FakeSolr()


@pytest.fixture
def root():
    return ROOT
